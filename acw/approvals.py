"""Approval policy: decide which backend tool requests may be answered without asking.

The default is to ask every time. A looser mode is always the user's explicit choice per role,
and some requests are asked about in every mode because they are destructive or leave the machine.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

MODES = ('ask', 'edits', 'all')
MODE_LABELS = {'ask': '每次都問', 'edits': '自動核准讀取與專案內的檔案編輯', 'all': '自動核准全部（危險操作仍會問）'}
FILE_TOOLS = ('Edit', 'Write', 'MultiEdit', 'NotebookEdit')
READ_TOOLS = ('Read', 'Glob', 'Grep', 'LS', 'NotebookRead', 'TodoWrite', 'TaskCreate', 'TaskUpdate', 'TaskList', 'TaskGet')
# Asked about in every mode: hard to undo, or it publishes or sends something.
ALWAYS_ASK = re.compile(
    r'\brm\s+(-\w*\s+)*-\w*[rf]|\brmdir\s+/s|\bdel\s+/[sqf]|Remove-Item\b[^|;\n]*-(Recurse|Force)|\bformat\s+[a-z]:|\bmkfs\b|\bdd\s+if='
    r'|\bgit\s+push\b|\bgit\s+reset\s+--hard|\bgit\s+clean\s+-\w*[fdx]|\bgit\s+checkout\s+--\s|\bgit\s+branch\s+-D\b|--force\b|--no-verify\b'
    r'|\bshutdown\b|\bRestart-Computer\b|\bStop-Computer\b|\breg\s+(add|delete)\b|\bSet-ExecutionPolicy\b|\bnetsh\b|\bsc\s+(delete|config)\b'
    r'|\b(curl|wget|iwr|Invoke-WebRequest)\b[^|\n]*\|\s*(sh|bash|iex|powershell|pwsh|python)\b|\bInvoke-Expression\b|\biex\b'
    r'|\bnpm\s+publish\b|\bgh\s+(pr\s+merge|release|repo\s+delete)\b|\bdocker\s+(system\s+prune|rm|rmi)\b|\bDROP\s+(TABLE|DATABASE)\b',
    re.IGNORECASE)

LEADING_CD = re.compile(r"""^cd\s+("[^"]*"|'[^']*'|\S+)\s*&&\s*""")
CHAINED = re.compile(r'&&|\|\||[;|`\n]|\$\(')


def describe(details):
    """Normalise a Claude or Codex approval request into kind / tool / command / path."""
    details = details if isinstance(details, dict) else {}
    method = str(details.get('method') or '')
    if method:  # Codex app-server
        if method.endswith('commandExecution/requestApproval'):
            command = details.get('command')
            command = ' '.join(str(part) for part in command) if isinstance(command, list) else str(command or '')
            return {'kind': 'command', 'tool': 'exec', 'command': command, 'path': ''}
        if method.endswith('fileChange/requestApproval'):
            return {'kind': 'edit', 'tool': 'apply_patch', 'command': '', 'path': str(details.get('grantRoot') or ''), 'sandboxed': True}
        return {'kind': 'permission', 'tool': method.split('/')[1] if '/' in method else method, 'command': '', 'path': ''}
    tool = str(details.get('tool_name') or details.get('tool') or '')
    data = details.get('input') if isinstance(details.get('input'), dict) else {}
    if tool == 'Bash' or tool == 'PowerShell':
        return {'kind': 'command', 'tool': tool, 'command': str(data.get('command') or ''), 'path': ''}
    if tool in FILE_TOOLS:
        return {'kind': 'edit', 'tool': tool, 'command': '', 'path': str(data.get('file_path') or data.get('notebook_path') or '')}
    return {'kind': 'tool', 'tool': tool or 'tool', 'command': '', 'path': str(data.get('file_path') or data.get('path') or '')}


def rule_key(request):
    """What a "always allow this" choice covers: one program for commands, one tool otherwise."""
    if request['kind'] == 'command':
        # One leading "cd <folder> &&" is routine; any other chaining means more than one program,
        # which a single-program rule must not cover.
        command = LEADING_CD.sub('', request['command'].strip(), count=1)
        if CHAINED.search(command):
            return ''
        words = command.split()
        skip = {'cd', 'sudo', 'time', 'env'}
        first = next((word for word in words if '=' not in word and word.lower() not in skip and not word.startswith(('"', "'", '/', '.', '-', '&'))), '')
        name = re.sub(r'\.(exe|cmd|bat|ps1)$', '', Path(first).name, flags=re.IGNORECASE).lower()
        return 'cmd:' + name if re.fullmatch(r'[\w.+-]{1,40}', name) else ''
    if request['kind'] in ('edit', 'tool') and request['tool']:
        return 'tool:' + request['tool']
    return ''


def rule_label(key):
    return key.split(':', 1)[1] if key else ''


def _inside(path, folder):
    if not path or not folder:
        return False
    try:
        target = Path(path) if os.path.isabs(path) else Path(folder) / path
        return target.resolve().is_relative_to(Path(folder).resolve())
    except (OSError, ValueError):
        return False


def decide(mode, details, cwd='', rules=()):
    """True when the request may be approved without asking; otherwise the user is asked."""
    request = describe(details)
    if mode not in MODES or request['kind'] == 'permission':
        return False
    if request['kind'] == 'command' and (not request['command'].strip() or ALWAYS_ASK.search(request['command'])):
        return False
    if request['kind'] == 'edit' and not (request.get('sandboxed') or _inside(request['path'], cwd)):
        return False  # edits outside the project folder are always asked about
    if rule_key(request) and rule_key(request) in rules:
        return True
    if mode == 'all':
        return True
    if mode == 'edits':
        return request['kind'] == 'edit' or (request['kind'] == 'tool' and request['tool'] in READ_TOOLS)
    return False
