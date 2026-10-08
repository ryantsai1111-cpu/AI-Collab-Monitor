"""SQLite/WAL and redacted JSONL persistence for AI Collaboration Workspace."""
from __future__ import annotations

import errno
import gzip
import json
import os
import re
import sqlite3
import stat
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from .security import reject_link_ancestors, sanitize


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def uid(prefix="") -> str:
    return prefix + uuid.uuid4().hex


class Store:
    TABLES = {"projects", "tasks", "sessions", "messages", "events", "handoffs", "artifacts", "settings"}
    JSON_FIELDS = {"metadata", "payload", "value"}
    RAW_SEGMENT = re.compile(r'(?:claude|dot|codex|local|workspace)(?:-\d+(?:-[0-9a-f]{8})?)?\.jsonl(?:\.gz)?')

    def __init__(self, data_dir):
        # Check the supplied spelling before resolve() hides links or junctions.
        self._reject_managed_links(Path(data_dir))
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.raw_dir = self.data_dir / "raw"
        self.artifact_dir = self.data_dir / "artifacts"
        for path in (self.raw_dir, self.artifact_dir):
            self._reject_managed_links(path)
            path.mkdir(exist_ok=True)
            self._validate_managed_directory(path)
        self.lock = threading.RLock()
        self._closed = False
        self.db_path = self.data_dir / "workspace.sqlite3"
        # SQLite opens its own database and journal/WAL sidecars. Reject existing
        # redirected files before connect or any pragma/schema operation.
        for suffix in ('', '-wal', '-shm', '-journal'):
            self._validate_managed_file(self.data_dir / ('workspace.sqlite3' + suffix), self.data_dir)
        self.db = sqlite3.connect(self.db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS projects (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, repo_path TEXT NOT NULL,
          default_branch TEXT DEFAULT '', active_branch TEXT DEFAULT '',
          claude_cwd TEXT DEFAULT '', codex_cwd TEXT DEFAULT '', local_cwd TEXT DEFAULT '', dot_metadata TEXT DEFAULT '',
          notes TEXT DEFAULT '', created_at TEXT NOT NULL, metadata TEXT DEFAULT '{}');
        CREATE TABLE IF NOT EXISTS tasks (
          id TEXT PRIMARY KEY, title TEXT NOT NULL, project_id TEXT REFERENCES projects(id),
          repo TEXT DEFAULT '', branch TEXT DEFAULT '', created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'NEW',
          claude_session TEXT DEFAULT '', dot_session TEXT DEFAULT '', codex_session TEXT DEFAULT '', local_session TEXT DEFAULT '',
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
        for table, column in (('projects', 'local_cwd'), ('tasks', 'local_session')):
            columns = {row['name'] for row in self.db.execute(f'PRAGMA table_info({table})')}
            if column not in columns:
                self.db.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT DEFAULT ''")
        self.native_lookup_index=False
        self._native_metadata="CASE WHEN json_valid(metadata) THEN metadata ELSE '{}' END"
        try:
            self.db.execute("SELECT json_valid('{}')")
            self.db.execute("CREATE INDEX IF NOT EXISTS messages_native_scope ON messages(agent,session_id,task_id,"
                "COALESCE(json_extract("+self._native_metadata+",'$.native_room_id'),''),"
                "COALESCE(json_extract("+self._native_metadata+",'$.native_id'),''))")
            self.native_lookup_index=True
        except sqlite3.OperationalError as exc:
            if 'no such function' not in str(exc).lower(): raise
        self.db.commit()
        self.max_raw_bytes = 10 * 1024 * 1024
        self.retention_days = 30
        self._raw_paths = {}
        self.archive_enabled = True
        self._last_maintenance = 0

    @staticmethod
    def _reject_managed_links(path):
        reject_link_ancestors(path)
        absolute = Path(path).expanduser().absolute()
        for part in (absolute, *absolute.parents):
            try:
                metadata = part.lstat()
            except FileNotFoundError:
                continue
            # Python versions before Path.is_junction still expose the Windows
            # reparse attribute via lstat. Fail closed for all reparse types.
            if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400):
                raise PermissionError('Managed persistence paths cannot be symlinks or reparse points')

    def _validate_managed_directory(self, path):
        self._reject_managed_links(path)
        if path != self.data_dir and path.parent != self.data_dir:
            raise PermissionError('Managed directory is outside the workspace data directory')
        if not path.is_dir() or path.resolve() != path:
            raise PermissionError('Managed persistence directory is missing or unsafe')

    def _validate_managed_file(self, path, parent):
        self._validate_managed_directory(parent)
        if path.parent != parent:
            raise PermissionError('Managed file is outside its persistence directory')
        self._reject_managed_links(path)
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            return None
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise PermissionError('Managed persistence files must be regular, unshared files')
        return metadata

    def _validate_raw_path(self, path):
        if not self.RAW_SEGMENT.fullmatch(path.name):
            raise PermissionError('Invalid managed raw segment name')
        return self._validate_managed_file(path, self.raw_dir)

    def _open_raw(self, path, *, append=False, write=False):
        """Validate before opening and before writing, using no-follow when available.

        These checks reject static redirects; they do not promise protection
        against every concurrent ancestor replacement on every platform.
        """
        self._validate_raw_path(path)
        flags = os.O_WRONLY | os.O_CREAT if append or write else os.O_RDONLY
        if append:
            flags |= os.O_APPEND
        flags |= getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NONBLOCK', 0)
        try:
            descriptor = os.open(path, flags, 0o666)
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise PermissionError('Managed persistence files cannot be symlinks') from exc
            raise
        try:
            opened = os.fstat(descriptor)
            current = self._validate_raw_path(path)
            if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or current is None or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
                raise PermissionError('Managed raw segment changed while opening')
            if append:
                os.lseek(descriptor, 0, os.SEEK_END)
            elif write:
                # Truncate only after validating the opened file, never in open().
                os.ftruncate(descriptor, 0)
            return os.fdopen(descriptor, 'ab' if append else 'wb' if write else 'rb')
        except BaseException:
            os.close(descriptor)
            raise

    def _set_raw_mtime(self, path, handle, stamp):
        if os.utime in os.supports_fd:
            os.utime(handle.fileno(), (stamp, stamp))
            return
        # Windows Python may support neither descriptor utime nor no-follow
        # utime. Keep the same static redirect/reparse checks as _open_raw and
        # verify this is still the opened file before using its pathname.
        opened = os.fstat(handle.fileno())
        current = self._validate_raw_path(path)
        if current is None or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise PermissionError('Managed raw segment changed before timestamp update')
        options = {'follow_symlinks': False} if os.utime in os.supports_follow_symlinks else {}
        os.utime(path, (stamp, stamp), **options)

    def _ensure_open(self):
        if self._closed:
            raise RuntimeError('Store is closed')

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
            self._ensure_open()
            return [self._decode(row) for row in self.db.execute(sql, params).fetchall()]

    def find_native_message(self,agent,session_id,task_id,room_id,native_id):
        if not native_id: return None
        scope=(agent,session_id,task_id)
        table='messages INDEXED BY messages_native_scope' if self.native_lookup_index else 'messages'
        sql='SELECT * FROM '+table+' WHERE agent=? AND session_id=? AND task_id IS ?'
        if self.native_lookup_index:
            sql+=" AND COALESCE(json_extract("+self._native_metadata+",'$.native_room_id'),'')=?"
            sql+=" AND COALESCE(json_extract("+self._native_metadata+",'$.native_id'),'')=? ORDER BY timestamp DESC,rowid DESC LIMIT 1"
            rows=self.query(sql,scope+(room_id or '',native_id))
            return rows[0] if rows else None
        # Older SQLite builds retain correctness; diagnostics explicitly expose the scan fallback.
        rows=self.query(sql+' ORDER BY timestamp DESC,rowid DESC',scope)
        return next((row for row in rows if isinstance(row.get('metadata'),dict)
            and row['metadata'].get('native_id')==native_id and (row['metadata'].get('native_room_id') or '')==(room_id or '')),None)

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
            self._ensure_open()
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
            self._ensure_open()
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
            self._ensure_open()
            self.db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                            (str(key),json.dumps(clean,ensure_ascii=False)))
            self.db.commit()

    def append_raw(self, agent, event):
        """Append a redacted audit record. References include relative path and byte offset."""
        if agent not in {"claude","dot","codex","local","workspace"}:
            agent = "workspace"
        record = sanitize(event)
        data = (json.dumps(record,ensure_ascii=False,separators=(',',':'))+'\n').encode('utf-8')
        with self.lock:
            self._ensure_open()
            self._validate_managed_directory(self.raw_dir)
            path = self._raw_paths.get(agent)
            if path is None:
                candidates = []
                for item in self.raw_dir.glob(f'{agent}*.jsonl'):
                    if self.RAW_SEGMENT.fullmatch(item.name):
                        metadata = self._validate_raw_path(item)
                        if metadata is not None:
                            candidates.append((item, metadata))
                path = max(candidates, key=lambda item:item[1].st_mtime_ns)[0] if candidates else self.raw_dir/f'{agent}.jsonl'
                archived = self._validate_raw_path(path.with_suffix('.jsonl.gz'))
                if not candidates and (archived is not None or f'raw/{path.name}' in self.get_setting('raw.expired_segments',{})):
                    path=self.raw_dir/f'{agent}-{time.time_ns()}-{uuid.uuid4().hex[:8]}.jsonl'
            rotated = False
            metadata = self._validate_raw_path(path)
            if metadata is not None and metadata.st_size + len(data) > self.max_raw_bytes:
                # Immutable segment names keep references held by live UI and exports valid.
                path = self.raw_dir / f"{agent}-{time.time_ns()}-{uuid.uuid4().hex[:8]}.jsonl"
                rotated = True
            self._raw_paths[agent] = path
            with self._open_raw(path, append=True) as handle:
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
        supplied = Path(relative)
        if len(supplied.parts) != 2 or supplied.parts[0] != 'raw' or supplied.suffix != '.jsonl':
            raise PermissionError("Invalid raw event reference")
        path = self.data_dir / supplied
        with self.lock:
            self._ensure_open()
            if self._validate_raw_path(path) is None:
                if relative in self.get_setting('raw.expired_segments',{}):
                    raise FileNotFoundError('Raw event expired by configured retention policy')
                archived = path.with_suffix('.jsonl.gz')
                with self._open_raw(archived) as source, gzip.GzipFile(fileobj=source, mode='rb') as handle:
                    handle.seek(int(offset))
                    return json.loads(handle.readline().decode('utf-8'))
            else:
                opener = self._open_raw(path)
            with opener as handle:
                handle.seek(int(offset))
                return json.loads(handle.readline().decode('utf-8'))

    def archive_logs(self):
        """Apply retention only to owned segments; compressed references stay resolvable."""
        cutoff = time.time() - self.retention_days*86400
        count = 0
        with self.lock:
            self._ensure_open()
            self._validate_managed_directory(self.raw_dir)
            self._last_maintenance = time.monotonic()
            active = set(self._raw_paths.values())
            expired = self.get_setting('raw.expired_segments',{})
            for path in self.raw_dir.iterdir():
                if not self.RAW_SEGMENT.fullmatch(path.name):
                    continue
                metadata = self._validate_raw_path(path)
                if metadata is None or path in active:
                    continue
                source_name = path.name[:-3] if path.name.endswith('.gz') else path.name
                reference = 'raw/'+source_name
                if metadata.st_mtime < cutoff:
                    prefix = reference+':'
                    for table in ('messages','events'):
                        self.db.execute(f"UPDATE {table} SET raw_ref='expired:' || raw_ref WHERE raw_ref LIKE ?",(prefix+'%',))
                    expired[reference] = now()
                    # A single validated app-owned file only; never recursive deletion.
                    self._validate_raw_path(path)
                    path.unlink()
                    count += 1
                elif self.archive_enabled and path.suffix=='.jsonl':
                    target=path.with_suffix('.jsonl.gz')
                    stamp=metadata.st_mtime
                    with self._open_raw(path) as source, self._open_raw(target, write=True) as output:
                        with gzip.GzipFile(filename='', mode='wb', fileobj=output) as dest:
                            while chunk:=source.read(1024*1024): dest.write(chunk)
                        output.flush()
                        self._set_raw_mtime(target, output, stamp)
                    self._validate_raw_path(path)
                    path.unlink()
                    count += 1
            if expired:
                self.set_setting('raw.expired_segments',expired)
            self.db.commit()
        return count

    def close(self):
        with self.lock:
            if self._closed:
                return
            try:
                self.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            finally:
                self.db.close()
                self._closed = True
