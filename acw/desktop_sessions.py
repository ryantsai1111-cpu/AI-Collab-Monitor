"""Read-only view of the Claude desktop app's local Code sessions.

The desktop app keeps one small JSON file per session (title, working directory,
Claude Code session id) and Claude Code keeps the transcript as JSONL. Both are
private, undocumented formats: every field is optional here and anything
unreadable is skipped. Nothing is written, and nothing is read until the user
opens the picker or opens one session.
"""
from __future__ import annotations

import json
import os
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

MAX_METADATA_BYTES = 2 * 1024 * 1024
MAX_MESSAGE_CHARS = 20000


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


def list_desktop_sessions(roots=None):
    """Return whitelisted metadata for every local desktop session, newest first."""
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
            record = {
                'id': session_id.lower(), 'cwd': cwd,
                'title': str(data.get('title') or '').strip() or '（未命名對話）',
                'model': str(data.get('model') or ''), 'effort': str(data.get('effort') or ''),
                'archived': bool(data.get('isArchived')),
                'last_activity': _iso(data.get('lastActivityAt') or data.get('createdAt')),
                'created': _iso(data.get('createdAt')),
                'turns': data.get('completedTurns') if isinstance(data.get('completedTurns'), int) else 0,
                'cwd_exists': Path(cwd).is_dir(),
            }
            known = sessions.get(record['id'])
            if not known or record['last_activity'] > known['last_activity']:
                sessions[record['id']] = record
    return sorted(sessions.values(), key=lambda item: item['last_activity'], reverse=True)


def group_by_project(sessions):
    """Group sessions by working directory; projects ordered by their newest session."""
    groups = {}
    for session in sessions:
        key = os.path.normcase(os.path.normpath(session['cwd']))
        group = groups.setdefault(key, {'cwd': session['cwd'], 'name': Path(session['cwd']).name or session['cwd'],
                                        'cwd_exists': session['cwd_exists'], 'sessions': []})
        group['sessions'].append(session)
    return sorted(groups.values(), key=lambda group: max(s['last_activity'] for s in group['sessions']), reverse=True)


def _visible_text(content):
    # Only what the user typed and what the assistant said: no reasoning, tool input or tool output.
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ''
    return '\n\n'.join(block['text'] for block in content
                       if isinstance(block, dict) and block.get('type') == 'text' and isinstance(block.get('text'), str))


def read_transcript(session_id, limit=200, roots=None):
    """Return the last `limit` visible user/assistant messages of one explicitly chosen session."""
    if not _valid_id(session_id):
        raise ValueError('Invalid Claude session identifier')
    messages = deque(maxlen=max(1, int(limit)))
    for root in transcript_roots() if roots is None else roots:
        for path in Path(root).glob('*/' + session_id + '.jsonl'):
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
                        text = _visible_text(message.get('content')).strip()
                        if not text or text.startswith(('<command-name>', '<local-command-', '<system-reminder>')):
                            continue
                        # Claude Code writes one row per content block; rejoin blocks of the same reply.
                        part = str(message.get('id') or '')
                        if part and messages and messages[-1]['part'] == part and row['type'] == 'assistant':
                            messages[-1]['content'] = (messages[-1]['content'] + '\n\n' + text)[:MAX_MESSAGE_CHARS]
                            continue
                        messages.append({'id': str(row.get('uuid') or ''), 'role': row['type'], 'part': part,
                                         'content': text[:MAX_MESSAGE_CHARS], 'timestamp': str(row.get('timestamp') or '')})
            except OSError:
                continue
            return [{key: value for key, value in item.items() if key != 'part'} for item in messages]
    return []
