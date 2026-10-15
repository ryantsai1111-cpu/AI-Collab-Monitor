"""Human-readable local metadata. Labels never act as backend identifiers."""
from datetime import datetime, timezone
from pathlib import PureWindowsPath, PurePosixPath
from .security import sanitize


def compact(value, limit=90):
    text = ' '.join(str(sanitize(value or '')).split())
    return text if len(text) <= limit else text[:limit - 1] + '…'


def path_name(value):
    value = str(value or '')
    return (PureWindowsPath(value) if '\\' in value or (len(value)>1 and value[1]==':')
            else PurePosixPath(value)).name


def path_key(value):
    value = str(value or '').rstrip('/\\')
    return value.replace('/', '\\').casefold() if '\\' in value or ':' in value else value


def timestamp(value):
    if not value: return None
    try:
        if isinstance(value, (int, float)) or str(value).replace('.', '', 1).isdigit():
            number = float(value)
            return datetime.fromtimestamp(number / 1000 if number > 1e11 else number, timezone.utc)
        date = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return date if date.tzinfo else date.replace(tzinfo=timezone.utc)
    except (ValueError, OverflowError, OSError): return None


def time_label(value):
    date = timestamp(value)
    return date.astimezone().strftime('%Y-%m-%d %H:%M %z') if date else '時間未知'


def distinct_path_clue(cwd, others):
    """Shortest real path suffix which distinguishes same-named projects."""
    def parts(value):
        return (PureWindowsPath(value) if '\\' in str(value) or ':' in str(value) else PurePosixPath(value)).parts
    own = parts(cwd)
    for width in range(min(2, len(own)), len(own)+1):
        suffix = own[-width:]
        if all(tuple(p.casefold() for p in parts(value)[-width:]) != tuple(p.casefold() for p in suffix)
               for value in others if path_key(value) != path_key(cwd)):
            return '/'.join(suffix) if width < len(own) else str(cwd)
    return str(cwd)


def project_label(project, projects=()):
    cwd = project.get('repo_path') or project.get('repo') or ''
    name = compact(project.get('name')) or '未命名專案'
    duplicates = sum(compact(p.get('name')) == compact(project.get('name')) for p in projects) > 1
    others = [p.get('repo_path') or p.get('repo') or '' for p in projects if compact(p.get('name')) == compact(project.get('name'))]
    clue = distinct_path_clue(cwd, others) if duplicates and cwd else path_name(cwd)
    return name + (' · ' + clue if clue and (duplicates or clue != name) else '')


def session_identity(row):
    return row.get('session_id') or row.get('backend_session_id') or row.get('id') or row.get('sessionId') or row.get('threadId')


def session_display(row, agent, projects=(), preview=''):
    sid = session_identity(row)
    meta = row.get('metadata') if isinstance(row.get('metadata'), dict) else {}
    cwd = str(row.get('cwd') or row.get('projectPath') or row.get('directory') or meta.get('cwd') or '')
    project = next((p for p in projects if row.get('project_id') and p.get('id') == row['project_id']), None)
    if project is None and cwd:
        project = next((p for p in projects if path_key(p.get('repo_path')) == path_key(cwd)), None)
    context = project_label(project, projects) if project else '未知專案' + ('（' + path_name(cwd) + '） · ' + cwd if cwd else ' · 工作目錄未知')
    # A legacy title equal to an ID is not a conversation name.
    title = next((compact(value, 110) for value in
                  (row.get('title'), row.get('name'), row.get('display_name'), row.get('summary'),
                   row.get('firstPrompt'), row.get('preview'), meta.get('title'), preview)
                  if value and str(value) != str(sid)), '') or '未命名對話'
    updated = (meta.get('updatedAt') or meta.get('updated_at') or row.get('updatedAt') or
               row.get('lastModified') or row.get('updated_at') or row.get('timestamp') or row.get('created_at'))
    source = compact(row.get('source') or meta.get('source') or agent.title(), 45)
    stamp = time_label(updated)
    return {'id': sid, 'project': context, 'title': title, 'cwd': cwd,
            'updated': stamp, 'source': source,
            'label': f'{context} / {title} · {agent.title()} · {stamp}',
            'details': f'專案：{context}\n對話：{title}\n工作目錄：{cwd or "未知"}\n最近時間：{stamp}\n後端：{agent.title()}\n來源：{source}\nSession ID：{sid}',
            'sort_time': timestamp(updated).timestamp() if timestamp(updated) else float('-inf')}


def local_session_displays(core, agent, rows):
    """Only Workspace-owned local visible messages; never calls adapter history."""
    projects = core.list_projects()
    displays = []
    for row in rows:
        sid = session_identity(row); preview = ''
        if hasattr(core, 'store') and sid:
            saved = core.store.query("SELECT substr(content,1,300) AS content FROM messages WHERE agent=? AND session_id=? AND role IN ('user','assistant') AND status='complete' ORDER BY timestamp,id LIMIT 1", (agent, sid))
            preview = saved[0]['content'] if saved else ''
        name = core.agent_name(agent) if hasattr(core, 'provider') and core.provider(agent) != agent else agent
        displays.append((row, session_display(row, name, projects, preview)))
    return sorted(displays, key=lambda pair: (-pair[1]['sort_time'], pair[1]['label'], str(pair[1]['id'])))


def task_label(task, projects=()):
    project = next((p for p in projects if p.get('id') == task.get('project_id')), None)
    context = project_label(project, projects) if project else '未知專案'
    title = compact(task.get('title')) or '未命名任務'
    return f'{title} · {task.get("status") or "狀態未知"} / {context} · {time_label(task.get("updated_at") or task.get("created_at"))}'
