"""Read-only view of locally saved Claude desktop and Codex conversations.

The Claude desktop app keeps one small JSON file per Code session and Claude Code
keeps the transcript as JSONL; Codex keeps a title index and one rollout JSONL per
thread. These are private, undocumented formats: every field is optional here and
anything unreadable is skipped. Nothing is written, and nothing is read until the
user opens the navigator or opens one conversation.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

MAX_METADATA_BYTES = 2 * 1024 * 1024
MAX_MESSAGE_CHARS = 20000
MAX_TOOL_CHARS = 4000
MAX_CODEX_FILES = 400
FILE_TOOLS = ('Edit', 'Write', 'MultiEdit', 'NotebookEdit')


def session_roots():
    roots = []
    local, roaming = os.environ.get('LOCALAPPDATA'), os.environ.get('APPDATA')
    if local and (Path(local) / 'Packages').is_dir():
        roots.extend(sorted((Path(local) / 'Packages').glob('Claude_*/LocalCache/Roaming/Claude/claude-code-sessions')))
    if roaming:
        roots.append(Path(roaming) / 'Claude' / 'claude-code-sessions')
    return [root for root in roots if root.is_dir()]


def transcript_roots():
    configured = os.environ.get('CLAUDE_CONFIG_DIR')
    root = (Path(configured) if configured else Path.home() / '.claude') / 'projects'
    return [root] if root.is_dir() else []


def codex_roots():
    configured = os.environ.get('CODEX_HOME')
    root = Path(configured) if configured else Path.home() / '.codex'
    return [root] if root.is_dir() else []


def _iso(milliseconds):
    try:
        return datetime.fromtimestamp(float(milliseconds) / 1000, timezone.utc).isoformat(timespec='seconds')
    except (TypeError, ValueError, OverflowError, OSError):
        return ''


def _valid_id(value):
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value.lower()
    except ValueError:
        return False


def _clip(value, limit=MAX_TOOL_CHARS):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + f'\n…（已截斷，原長 {len(text)} 字元）'


_REPO_CACHE = {}


def repo_label(cwd):
    """(key, name) for grouping: the git origin repository when there is one, else the folder."""
    cached = _REPO_CACHE.get(cwd)
    if cached:
        return cached
    folder = Path(cwd)
    result = (os.path.normcase(os.path.normpath(cwd)), folder.name or cwd)
    try:
        marker = folder / '.git'
        config = marker / 'config'
        if marker.is_file():  # worktree: follow gitdir -> commondir to the main repository
            gitdir = Path(marker.read_text(encoding='utf-8', errors='replace').split('gitdir:', 1)[1].strip())
            gitdir = gitdir if gitdir.is_absolute() else folder / gitdir
            common = gitdir / 'commondir'
            base = (gitdir / common.read_text(encoding='utf-8').strip()).resolve() if common.is_file() else gitdir
            config = base / 'config'
        if config.is_file() and config.stat().st_size < MAX_METADATA_BYTES:
            match = re.search(r'\[remote "origin"\][^\[]*?url\s*=\s*(\S+)', config.read_text(encoding='utf-8', errors='replace'))
            if match:
                url = re.sub(r'^(\w+://)?[^@/]*@', r'\1', match.group(1)).rstrip('/')  # never keep embedded credentials
                name = re.sub(r'\.git$', '', re.split(r'[/:]', url)[-1])
                if name:
                    result = ('origin:' + re.sub(r'^\w+://', '', url).lower(), name)
    except (OSError, IndexError, ValueError):
        pass
    _REPO_CACHE[cwd] = result
    return result


def _record(agent, session_id, cwd, title, last_activity, created='', model='', archived=False, turns=0):
    key, name = repo_label(cwd)
    return {'agent': agent, 'id': session_id.lower(), 'cwd': cwd, 'title': title or '（未命名對話）',
            'model': model, 'archived': bool(archived), 'last_activity': last_activity, 'created': created,
            'turns': turns, 'cwd_exists': Path(cwd).is_dir(), 'project': name, 'project_key': key}


def list_desktop_sessions(roots=None):
    """Whitelisted metadata for every local Claude desktop session, newest first."""
    sessions = {}
    for root in session_roots() if roots is None else roots:
        for path in Path(root).glob('*/*/local_*.json'):
            try:
                if path.stat().st_size > MAX_METADATA_BYTES:
                    continue
                data = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
            session_id = data.get('cliSessionId') if isinstance(data, dict) else None
            cwd = data.get('cwd') or data.get('originCwd') if isinstance(data, dict) else None
            if not _valid_id(session_id) or not isinstance(cwd, str) or not cwd.strip():
                continue
            record = _record('claude', session_id, cwd, str(data.get('title') or '').strip(),
                             _iso(data.get('lastActivityAt') or data.get('createdAt')), _iso(data.get('createdAt')),
                             str(data.get('model') or ''), data.get('isArchived'),
                             data.get('completedTurns') if isinstance(data.get('completedTurns'), int) else 0)
            known = sessions.get(record['id'])
            if not known or record['last_activity'] > known['last_activity']:
                sessions[record['id']] = record
    return sorted(sessions.values(), key=lambda item: item['last_activity'], reverse=True)


def list_codex_sessions(roots=None, limit=MAX_CODEX_FILES):
    """Whitelisted metadata for the most recent local Codex threads, newest first."""
    sessions = {}
    for root in codex_roots() if roots is None else roots:
        titles = {}
        try:
            with (Path(root) / 'session_index.jsonl').open(encoding='utf-8', errors='replace') as lines:
                for line in lines:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(row, dict) and _valid_id(row.get('id')):
                        titles[row['id'].lower()] = (str(row.get('thread_name') or '').strip(), str(row.get('updated_at') or ''))
        except OSError:
            pass
        files = sorted(Path(root).glob('sessions/*/*/*/rollout-*.jsonl'), reverse=True)[:max(1, int(limit))]
        for path in files:
            try:
                with path.open(encoding='utf-8', errors='replace') as lines:
                    meta = json.loads(lines.readline(MAX_METADATA_BYTES))
            except (OSError, ValueError):
                continue
            payload = meta.get('payload') if isinstance(meta, dict) and meta.get('type') == 'session_meta' else None
            if not isinstance(payload, dict):
                continue
            session_id, cwd = payload.get('id') or payload.get('session_id'), payload.get('cwd')
            if not _valid_id(session_id) or not isinstance(cwd, str) or not cwd.strip():
                continue
            title, updated = titles.get(session_id.lower(), ('', ''))
            created = str(payload.get('timestamp') or meta.get('timestamp') or '')
            stamp = updated or created
            record = _record('codex', session_id, cwd, title, stamp[:19] + '+00:00' if stamp else '',
                             created, str(payload.get('model_provider') or ''))
            # Untitled threads and Codex's own review sub-threads are noise in a conversation list.
            record['system'] = not title or title == 'Guardian review'
            sessions[session_id.lower()] = record
    return sorted(sessions.values(), key=lambda item: item['last_activity'], reverse=True)


def group_by_project(sessions):
    """Group conversations the way the desktop sidebar does: by repository, else by folder."""
    groups = {}
    for session in sessions:
        key = session.get('project_key') or os.path.normcase(os.path.normpath(session['cwd']))
        group = groups.setdefault(key, {'cwd': session['cwd'], 'name': session.get('project') or Path(session['cwd']).name or session['cwd'],
                                        'cwd_exists': session['cwd_exists'], 'sessions': []})
        if session['cwd_exists'] and not group['cwd_exists']:
            group.update(cwd=session['cwd'], cwd_exists=True)
        group['sessions'].append(session)
    return sorted(groups.values(), key=lambda group: max(s['last_activity'] for s in group['sessions']), reverse=True)


def _visible_text(content):
    # Only what the user typed and what the assistant said: never reasoning.
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ''
    return '\n\n'.join(block['text'] for block in content
                       if isinstance(block, dict) and str(block.get('type')).lower() in ('text', 'input_text', 'output_text')
                       and isinstance(block.get('text'), str))


def _claude_tool(block, timestamp):
    name, data = str(block.get('name') or 'tool'), block.get('input') if isinstance(block.get('input'), dict) else {}
    if name == 'Bash':
        kind, summary = 'command', str(data.get('command') or '')
    elif name in FILE_TOOLS:
        kind, summary = 'file_edit', str(data.get('file_path') or data.get('notebook_path') or '')
    else:
        kind = 'tool_start'
        summary = str(data.get('description') or data.get('pattern') or data.get('file_path') or data.get('query') or data.get('url') or '')
    return {'kind': 'tool', 'id': str(block.get('id') or ''), 'type': kind, 'tool': name, 'summary': _clip(summary, 300),
            'input': {key: _clip(value) for key, value in data.items()}, 'output': '', 'timestamp': timestamp}


def _read_claude(session_id, messages, tools, roots):
    for root in transcript_roots() if roots is None else roots:
        for path in Path(root).glob('*/' + session_id + '.jsonl'):
            pending = {}
            try:
                with path.open(encoding='utf-8', errors='replace') as lines:
                    for line in lines:
                        try:
                            row = json.loads(line)
                        except ValueError:
                            continue
                        if not isinstance(row, dict) or row.get('type') not in ('user', 'assistant'):
                            continue
                        if row.get('isSidechain') or row.get('isMeta') or row.get('isCompactSummary'):
                            continue
                        message = row.get('message') if isinstance(row.get('message'), dict) else {}
                        content, timestamp = message.get('content'), str(row.get('timestamp') or '')
                        for block in content if isinstance(content, list) else []:
                            if not isinstance(block, dict):
                                continue
                            if block.get('type') == 'tool_use' and row['type'] == 'assistant':
                                item = _claude_tool(block, timestamp)
                                pending[item['id']] = item
                                tools.append(item)
                            elif block.get('type') == 'tool_result' and block.get('tool_use_id') in pending:
                                pending[block['tool_use_id']]['output'] = _clip(_visible_text(block.get('content')) or '')
                        text = _visible_text(content).strip()
                        if not text or text.startswith(('<command-name>', '<local-command-', '<system-reminder>')):
                            continue
                        # Claude Code writes one row per content block; rejoin blocks of the same reply.
                        part = str(message.get('id') or '')
                        if part and messages and messages[-1]['part'] == part and row['type'] == 'assistant':
                            messages[-1]['content'] = (messages[-1]['content'] + '\n\n' + text)[:MAX_MESSAGE_CHARS]
                            continue
                        messages.append({'kind': 'message', 'id': str(row.get('uuid') or ''), 'role': row['type'], 'part': part,
                                         'content': text[:MAX_MESSAGE_CHARS], 'timestamp': timestamp})
            except OSError:
                continue
            return True
    return False


def _read_codex(session_id, messages, tools, roots):
    for root in codex_roots() if roots is None else roots:
        for path in Path(root).glob('sessions/*/*/*/rollout-*' + session_id + '.jsonl'):
            try:
                with path.open(encoding='utf-8', errors='replace') as lines:
                    for line in lines:
                        try:
                            row = json.loads(line)
                        except ValueError:
                            continue
                        payload = row.get('payload') if isinstance(row, dict) else None
                        item = payload.get('item') if isinstance(payload, dict) and payload.get('type') == 'item_completed' else None
                        if not isinstance(item, dict):
                            continue
                        kind, timestamp, item_id = item.get('type'), str(row.get('timestamp') or ''), str(item.get('id') or '')
                        if kind in ('UserMessage', 'AgentMessage'):
                            text = _visible_text(item.get('content')).strip()
                            if text:
                                messages.append({'kind': 'message', 'id': item_id, 'role': 'user' if kind == 'UserMessage' else 'assistant',
                                                 'part': '', 'content': text[:MAX_MESSAGE_CHARS], 'timestamp': timestamp})
                        elif kind == 'CommandExecution':
                            parsed = item.get('parsed_cmd') if isinstance(item.get('parsed_cmd'), list) else []
                            command = next((p.get('cmd') for p in parsed if isinstance(p, dict) and p.get('cmd')), None) \
                                or ' '.join(str(part) for part in item.get('command') or [])
                            tools.append({'kind': 'tool', 'id': item_id, 'type': 'command', 'tool': 'exec', 'summary': _clip(command, 300),
                                          'input': {'command': _clip(command), 'cwd': str(item.get('cwd') or '')},
                                          'output': _clip('\n'.join(part for part in (item.get('stdout'), item.get('stderr')) if part)),
                                          'timestamp': timestamp})
                        elif kind == 'FileChange' and isinstance(item.get('changes'), dict):
                            changes = item['changes']
                            tools.append({'kind': 'tool', 'id': item_id, 'type': 'file_edit', 'tool': 'apply_patch',
                                          'summary': _clip(', '.join(Path(name).name for name in changes), 300),
                                          'input': {name: _clip((change or {}).get('unified_diff') or (change or {}).get('type') or '')
                                                    for name, change in changes.items() if isinstance(change, dict)},
                                          'output': '', 'timestamp': timestamp})
            except OSError:
                continue
            return True
    return False


def read_history(agent, session_id, limit=200, tool_limit=300, roots=None):
    """Last visible messages and tool activity of one explicitly chosen conversation, oldest first."""
    if not _valid_id(session_id):
        raise ValueError('Invalid session identifier')
    if agent not in ('claude', 'codex'):
        raise ValueError('Local history is available for Claude and Codex only')
    messages, tools = deque(maxlen=max(1, int(limit))), deque(maxlen=max(1, int(tool_limit)))
    (_read_claude if agent == 'claude' else _read_codex)(session_id.lower(), messages, tools, roots)
    first = messages[0]['timestamp'] if messages else ''
    items = [{key: value for key, value in item.items() if key != 'part'} for item in messages]
    items += [tool for tool in tools if tool['id'] and tool['timestamp'] >= first]
    return sorted(items, key=lambda item: item['timestamp'])


def read_transcript(session_id, limit=200, roots=None):
    """Visible Claude user/assistant messages only."""
    return [{key: value for key, value in item.items() if key != 'kind'}
            for item in read_history('claude', session_id, limit, roots=roots) if item['kind'] == 'message']


_HISTORY_FILES = {}
_HISTORY_MISSES = {}
_HISTORY_MISS_TTL = 30.0


def history_stamp(agent, session_id, cached_miss=True):
    """(modified, size) of a conversation's local file, or None. Cheap enough to poll.

    A missing file is remembered for _HISTORY_MISS_TTL seconds so polling does not glob every time;
    one-shot existence checks pass cached_miss=False to always look."""
    if agent not in ('claude', 'codex') or not _valid_id(session_id):
        return None
    key = (agent, session_id.lower())
    path = _HISTORY_FILES.get(key)
    if path is None or not path.is_file():
        missed = _HISTORY_MISSES.get(key)
        if cached_miss and missed is not None and time.monotonic() - missed < _HISTORY_MISS_TTL:
            return None
        pattern = '*/' + key[1] + '.jsonl' if agent == 'claude' else 'sessions/*/*/*/rollout-*' + key[1] + '.jsonl'
        path = next((match for root in (transcript_roots() if agent == 'claude' else codex_roots())
                     for match in Path(root).glob(pattern)), None)
        if path is None:
            _HISTORY_MISSES[key] = time.monotonic()
            return None
        _HISTORY_MISSES.pop(key, None)
        _HISTORY_FILES[key] = path
    try:
        status = path.stat()
    except OSError:
        return None
    return status.st_mtime_ns, status.st_size
