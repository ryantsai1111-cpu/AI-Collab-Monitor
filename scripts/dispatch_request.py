"""Submit one request to a running Workspace dispatcher; never start a backend directly."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time

REFUSAL_CODES = ('bad-label', 'bad-request', 'no-worktree', 'no-progress', 'dirty-worktree',
                 'git-failed', 'expired', 'no-spec')
LABEL = re.compile(r'(?!\.)[A-Za-z0-9._-]{1,64}')
LOCAL_PROMPT = '到 {worktree}，讀 {briefs}/PROGRESS.md，照它指的任務卡執行。只做進度檔指的那一步，做完該步的收尾（含 commit 與 push）後就結束並回報。'


def pid_alive(pid):
    if type(pid) is not int or pid <= 0:
        return False
    if os.name == 'nt':
        try:
            result = subprocess.run(['tasklist', '/FI', f'PID eq {pid}', '/NH', '/FO', 'CSV'],
                                    capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
            return any(len(row) > 1 and row[1] == str(pid)
                       for row in csv.reader(result.stdout.decode('utf-8', errors='replace').splitlines()))
        except (OSError, subprocess.TimeoutExpired):
            return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def dispatcher_ready(directory, maximum_age):
    try:
        path = directory / '.dispatcher.json'
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        age = time.time() - path.stat().st_mtime
        # A just-written file's mtime can be a few milliseconds ahead of time.time() on Windows
        # (different clock resolutions), so a small negative age still means "fresh".
        return -2 <= age <= maximum_age and pid_alive(data.get('pid'))
    except (OSError, ValueError, AttributeError):
        return False


def timeline(root, label, actor, event, message):
    if not root or not Path(root).is_dir():
        return
    try:
        path = Path(root) / 'logs'
        path.mkdir(exist_ok=True)
        line = f'{datetime.now().astimezone().isoformat(timespec="seconds")} | {label} | {actor} | {event} | {message}\r\n'
        with (path / 'timeline.log').open('ab') as handle:
            handle.write(line.encode('utf-8'))
    except OSError:
        pass


def worktree_path(value):
    if os.name == 'nt' and re.match(r'^/[a-zA-Z]/', value):
        value = value[1].upper() + ':/' + value[3:]
    return Path(value)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--agent', required=True)
    parser.add_argument('--worktree', type=worktree_path, required=True)
    parser.add_argument('--label', required=True)
    parser.add_argument('--spec')
    parser.add_argument('--briefs')
    parser.add_argument('--prompt-file', type=Path)
    parser.add_argument('--timeout', type=int)
    parser.add_argument('--run-budget', type=int)
    parser.add_argument('--max-turns', type=int)
    parser.add_argument('--allow-dirty', action='store_true')
    default = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.local/share'))) / 'AI-Collaboration-Workspace/data'
    parser.add_argument('--data-dir', type=Path, default=Path(os.environ.get('ACW_DATA_DIR', str(default))))
    parser.add_argument('--monitor-root', type=Path)
    args = parser.parse_args(argv)
    if not LABEL.fullmatch(args.label) or args.label.endswith('.result'):
        parser.error('Invalid label')
    if args.agent not in ('local', 'codex') and not re.fullmatch(r'agent-[0-9a-f]{32}', args.agent):
        parser.error('agent must be local, codex or an instance id')
    if args.agent == 'codex' and not args.spec:
        parser.error('--agent codex requires --spec')
    if args.agent == 'local' and not args.briefs:
        parser.error('--agent local requires --briefs')
    if not args.worktree.is_absolute():
        parser.error('worktree must be absolute')
    if any(value is not None and value <= 0 for value in (args.timeout, args.run_budget, args.max_turns)):
        parser.error('limits must be positive')
    directory = args.data_dir / 'requests'
    if not dispatcher_ready(directory, 15):
        print('workspace: dispatcher not responding', flush=True)
        return 4
    codex = args.agent == 'codex' or (args.agent.startswith('agent-') and args.spec is not None)
    actor = 'CODEX' if codex else 'HERMES'
    try:
        prompt = args.prompt_file.read_text(encoding='utf-8-sig') if args.prompt_file else (
            f'照 {args.spec} 執行；做完開 PR 不要 push main；回報用規格的回報格式' if codex else LOCAL_PROMPT.format(worktree=args.worktree, briefs=args.briefs))
    except OSError as exc:
        parser.error(str(exc))
    request = dict(agent=args.agent, label=args.label, worktree=str(args.worktree), prompt=prompt,
                   created=datetime.now().astimezone().isoformat(timespec='seconds'), allow_dirty=args.allow_dirty)
    for name, value in (('spec', args.spec), ('briefs', args.briefs), ('timeout_seconds', args.timeout),
                        ('run_budget', args.run_budget), ('max_turns', args.max_turns)):
        if value is not None:
            request[name] = value
    if args.monitor_root:
        request['monitor_root'] = str(args.monitor_root)
    path = directory / (args.label + '.json')
    result_path = directory / (args.label + '.result.json')
    if path.exists():
        print('workspace: request label is already in use; choose another --label', flush=True)
        return 2
    result_path.unlink(missing_ok=True)
    temporary = None
    outcome = 'exit=1 interrupted mode=workspace'
    previous = signal.getsignal(signal.SIGTERM)
    def interrupted(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=directory, suffix='.tmp', delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(request, handle, ensure_ascii=False)
        os.replace(temporary, path)
        timeline(args.monitor_root, args.label, actor, 'RUN_STARTED', 'mode=workspace')
        while True:
            try:
                result = json.loads(result_path.read_text(encoding='utf-8-sig'))
            except (OSError, ValueError):
                result = None
            if isinstance(result, dict) and result.get('label') == args.label:
                status = result.get('status')
                code = 0 if status == 'complete' else 1
                reason = str(result.get('reason') or '').split(':', 1)[0]
                if status == 'rejected' and reason in REFUSAL_CODES:
                    code = 3
                print(json.dumps(result, ensure_ascii=False), flush=True)
                print(('codex_exit=' if codex else 'hermes_exit=') + str(result.get('exit_code', 1)), flush=True)
                outcome = f'exit={code} result_exit={result.get("exit_code", 1)} mode=workspace'
                return code
            if not dispatcher_ready(directory, 30):
                outcome = 'exit=1 dispatcher-lost mode=workspace'
                print('workspace: dispatcher lost', flush=True)
                return 1
            time.sleep(1)
    except KeyboardInterrupt:
        return 1
    finally:
        path.unlink(missing_ok=True)
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        timeline(args.monitor_root, args.label, actor, 'RUN_ENDED', outcome)
        signal.signal(signal.SIGTERM, previous)


if __name__ == '__main__':
    raise SystemExit(main())
