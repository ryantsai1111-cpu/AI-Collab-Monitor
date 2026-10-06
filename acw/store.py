"""SQLite/WAL and redacted JSONL persistence for AI Collaboration Workspace."""
from __future__ import annotations

import gzip
import json
import os
import re
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from .security import sanitize


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def uid(prefix="") -> str:
    return prefix + uuid.uuid4().hex


class Store:
    TABLES = {"projects", "tasks", "sessions", "messages", "events", "handoffs", "artifacts", "settings"}
    JSON_FIELDS = {"metadata", "payload", "value"}

    def __init__(self, data_dir):
        self.data_dir = Path(data_dir).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.raw_dir = self.data_dir / "raw"
        self.raw_dir.mkdir(exist_ok=True)
        self.artifact_dir = self.data_dir / "artifacts"
        self.artifact_dir.mkdir(exist_ok=True)
        if any(path.is_symlink() or not path.resolve().is_relative_to(self.data_dir) for path in (self.raw_dir,self.artifact_dir)):
            raise PermissionError('Managed raw and artifact directories must remain inside the workspace data directory')
        self.lock = threading.RLock()
        self.db_path = self.data_dir / "workspace.sqlite3"
        self.db = sqlite3.connect(self.db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS projects (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, repo_path TEXT NOT NULL,
          default_branch TEXT DEFAULT '', active_branch TEXT DEFAULT '',
          claude_cwd TEXT DEFAULT '', codex_cwd TEXT DEFAULT '', dot_metadata TEXT DEFAULT '',
          notes TEXT DEFAULT '', created_at TEXT NOT NULL, metadata TEXT DEFAULT '{}');
        CREATE TABLE IF NOT EXISTS tasks (
          id TEXT PRIMARY KEY, title TEXT NOT NULL, project_id TEXT REFERENCES projects(id),
          repo TEXT DEFAULT '', branch TEXT DEFAULT '', created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'NEW',
          claude_session TEXT DEFAULT '', dot_session TEXT DEFAULT '', codex_session TEXT DEFAULT '',
          created_by TEXT DEFAULT 'user', current_owner TEXT DEFAULT 'user', notes TEXT DEFAULT '',
          metadata TEXT DEFAULT '{}');
        CREATE TABLE IF NOT EXISTS sessions (
          id TEXT NOT NULL, agent TEXT NOT NULL, task_id TEXT REFERENCES tasks(id),
          project_id TEXT REFERENCES projects(id), title TEXT DEFAULT '', cwd TEXT DEFAULT '',
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, metadata TEXT DEFAULT '{}',
          PRIMARY KEY(agent,id));
        CREATE TABLE IF NOT EXISTS messages (
          id TEXT PRIMARY KEY, task_id TEXT REFERENCES tasks(id), agent TEXT NOT NULL,
          session_id TEXT DEFAULT '', role TEXT NOT NULL, content TEXT NOT NULL,
          timestamp TEXT NOT NULL, raw_ref TEXT DEFAULT '', status TEXT DEFAULT 'complete',
          metadata TEXT DEFAULT '{}');
        CREATE TABLE IF NOT EXISTS events (
          id TEXT PRIMARY KEY, task_id TEXT REFERENCES tasks(id), agent TEXT DEFAULT '',
          session_id TEXT DEFAULT '', type TEXT NOT NULL, status TEXT DEFAULT '',
          timestamp TEXT NOT NULL, summary TEXT DEFAULT '', raw_ref TEXT DEFAULT '',
          payload TEXT DEFAULT '{}');
        CREATE TABLE IF NOT EXISTS handoffs (
          id TEXT PRIMARY KEY, task_id TEXT REFERENCES tasks(id), source_agent TEXT NOT NULL,
          target_agent TEXT NOT NULL, source_message_id TEXT NOT NULL REFERENCES messages(id),
          source_session TEXT DEFAULT '', source_message TEXT NOT NULL,
          handoff_message TEXT NOT NULL, content TEXT NOT NULL, annotation TEXT DEFAULT '',
          timestamp TEXT NOT NULL, project_id TEXT REFERENCES projects(id), branch TEXT DEFAULT '',
          status TEXT DEFAULT 'prepared', metadata TEXT DEFAULT '{}');
        CREATE TABLE IF NOT EXISTS artifacts (
          id TEXT PRIMARY KEY, task_id TEXT REFERENCES tasks(id), agent TEXT DEFAULT '',
          type TEXT NOT NULL, name TEXT NOT NULL, path TEXT DEFAULT '', content TEXT DEFAULT '',
          timestamp TEXT NOT NULL, metadata TEXT DEFAULT '{}');
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS messages_task_agent ON messages(task_id,agent,timestamp);
        CREATE INDEX IF NOT EXISTS events_task_type ON events(task_id,type,timestamp);
        CREATE INDEX IF NOT EXISTS tasks_project_status ON tasks(project_id,status,created_at);
        CREATE INDEX IF NOT EXISTS artifacts_task ON artifacts(task_id);
        ''')
        self.db.commit()
        self.max_raw_bytes = 10 * 1024 * 1024
        self.retention_days = 30
        self._raw_paths = {}
        self.archive_enabled = True
        self._last_maintenance = 0

    @staticmethod
    def _decode(row):
        result = dict(row)
        for key in Store.JSON_FIELDS & result.keys():
            try:
                result[key] = json.loads(result[key])
            except (ValueError, TypeError):
                pass
        return result

    def query(self, sql, params=()):
        if not sql.lstrip().lower().startswith(("select", "pragma table_info")):
            raise ValueError("Public query is read-only")
        with self.lock:
            return [self._decode(row) for row in self.db.execute(sql, params).fetchall()]

    def insert(self, table, values, *, replace=False):
        if table not in self.TABLES:
            raise ValueError("Unknown table")
        clean = sanitize(values)
        encoded = {k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k,v in clean.items()}
        if not all(k.replace('_','').isalnum() for k in encoded):
            raise ValueError("Invalid column")
        names = ','.join(encoded)
        slots = ','.join('?' for _ in encoded)
        action = "INSERT OR REPLACE" if replace else "INSERT"
        with self.lock:
            self.db.execute(f"{action} INTO {table} ({names}) VALUES ({slots})", tuple(encoded.values()))
            self.db.commit()
        return clean

    def update(self, table, identity, values):
        if table not in self.TABLES or not values:
            raise ValueError("Unknown table or no fields")
        if not all(k.replace('_','').isalnum() for k in list(values)+list(identity)):
            raise ValueError("Invalid column")
        clean = sanitize(values)
        encoded = {k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict,list)) else v for k,v in clean.items()}
        where = ' AND '.join(k+'=?' for k in identity)
        assignments = ','.join(k+'=?' for k in encoded)
        with self.lock:
            self.db.execute(f"UPDATE {table} SET {assignments} WHERE {where}", tuple(encoded.values())+tuple(identity.values()))
            self.db.commit()

    def get(self, table, identity):
        if table not in self.TABLES or not all(k.replace('_','').isalnum() for k in identity):
            raise ValueError("Invalid table or field")
        rows = self.query(f"SELECT * FROM {table} WHERE "+' AND '.join(k+'=?' for k in identity),tuple(identity.values()))
        return rows[0] if rows else None

    def get_setting(self, key, default=None):
        found = self.get("settings", {"key": key})
        return found["value"] if found else default

    def set_setting(self, key, value):
        # Sanitize using the key itself, too: even a setting named 'token' is never saved.
        clean = sanitize({str(key): value})[str(key)]
        with self.lock:
            self.db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                            (str(key),json.dumps(clean,ensure_ascii=False)))
            self.db.commit()

    def append_raw(self, agent, event):
        """Append a redacted audit record. References include relative path and byte offset."""
        if agent not in {"claude","dot","codex","workspace"}:
            agent = "workspace"
        record = sanitize(event)
        data = (json.dumps(record,ensure_ascii=False,separators=(',',':'))+'\n').encode('utf-8')
        with self.lock:
            path = self._raw_paths.get(agent)
            if path is None:
                candidates = list(self.raw_dir.glob(f'{agent}*.jsonl'))
                path = max(candidates, key=lambda item:item.stat().st_mtime_ns) if candidates else self.raw_dir/f'{agent}.jsonl'
                if not candidates and (path.with_suffix('.jsonl.gz').exists() or f'raw/{path.name}' in self.get_setting('raw.expired_segments',{})):
                    path=self.raw_dir/f'{agent}-{time.time_ns()}-{uuid.uuid4().hex[:8]}.jsonl'
            rotated = False
            if path.exists() and path.stat().st_size + len(data) > self.max_raw_bytes:
                # Immutable segment names keep references held by live UI and exports valid.
                path = self.raw_dir / f"{agent}-{time.time_ns()}-{uuid.uuid4().hex[:8]}.jsonl"
                rotated = True
            self._raw_paths[agent] = path
            with path.open('ab') as handle:
                offset = handle.tell()
                handle.write(data)
                handle.flush()
            if rotated or time.monotonic() - self._last_maintenance > 60:
                self.archive_logs()
            return f"raw/{path.name}:{offset}"

    def read_raw(self, reference):
        if reference.startswith('expired:'):
            raise FileNotFoundError('Raw event expired by configured retention policy')
        relative, offset = reference.rsplit(':',1)
        path = (self.data_dir/relative).resolve()
        if not path.is_relative_to(self.raw_dir) or path.suffix != '.jsonl':
            raise PermissionError("Invalid raw event reference")
        with self.lock:
            if not path.exists():
                if relative in self.get_setting('raw.expired_segments',{}):
                    raise FileNotFoundError('Raw event expired by configured retention policy')
                archived = path.with_suffix('.jsonl.gz')
                if archived.is_symlink() or not archived.resolve().is_relative_to(self.raw_dir):
                    raise PermissionError('Invalid archived raw event path')
                opener = gzip.open(archived,'rb')
            else:
                opener = path.open('rb')
            with opener as handle:
                handle.seek(int(offset))
                return json.loads(handle.readline().decode('utf-8'))

    def archive_logs(self):
        """Apply retention only to owned segments; compressed references stay resolvable."""
        cutoff = time.time() - self.retention_days*86400
        count = 0
        with self.lock:
            self._last_maintenance = time.monotonic()
            active = set(self._raw_paths.values())
            expired = self.get_setting('raw.expired_segments',{})
            for path in self.raw_dir.iterdir():
                if not re.fullmatch(r'(?:claude|dot|codex|workspace)(?:-\d+(?:-[0-9a-f]{8})?)?\.jsonl(?:\.gz)?',path.name):
                    continue
                if path in active or path.is_symlink() or not path.is_file():
                    continue
                if not path.resolve().is_relative_to(self.raw_dir):
                    raise PermissionError('Retention path escaped workspace raw directory')
                source_name = path.name[:-3] if path.name.endswith('.gz') else path.name
                reference = 'raw/'+source_name
                if path.stat().st_mtime < cutoff:
                    prefix = reference+':'
                    for table in ('messages','events'):
                        self.db.execute(f"UPDATE {table} SET raw_ref='expired:' || raw_ref WHERE raw_ref LIKE ?",(prefix+'%',))
                    expired[reference] = now()
                    # A single validated app-owned file only; never recursive deletion.
                    path.unlink()
                    count += 1
                elif self.archive_enabled and path.suffix=='.jsonl':
                    target=path.with_suffix('.jsonl.gz')
                    if target.is_symlink(): raise PermissionError('Archive target cannot be a symlink')
                    stamp=path.stat().st_mtime
                    with path.open('rb') as source, gzip.open(target,'wb') as dest:
                        while chunk:=source.read(1024*1024): dest.write(chunk)
                    os.utime(target,(stamp,stamp))
                    path.unlink()
                    count += 1
            if expired:
                self.set_setting('raw.expired_segments',expired)
            self.db.commit()
        return count

    def close(self):
        with self.lock:
            self.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            self.db.close()
