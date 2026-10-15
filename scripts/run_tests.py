"""Run current offline test modules in separate processes with truthful reports."""
from __future__ import annotations

import argparse
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
UI_MODULES = (
    'test_ui_refresh', 'test_workbench', 'test_local_ui', 'test_agent_contexts',
    'test_agent_instances', 'test_collaboration_monitor', 'test_approvals',
    'test_dot_ui', 'test_dot_conversation', 'test_dot_follow',
    'test_desktop_sessions', 'test_first_run', 'test_live_sync',
    'test_session_labels',
)


def available_modules():
    return sorted(path.stem for path in (ROOT / 'tests').glob('test_*.py'))


def child_environment(visible=False):
    env = dict(os.environ)
    env['PYTHONPATH'] = os.pathsep.join(str(ROOT / name) for name in ('vendor', 'tests'))
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONUTF8'] = '1'
    env['QT_QPA_PLATFORM'] = 'windows' if visible else 'offscreen'
    # An inherited opt-in must never turn the offline runner into live inference.
    env.pop('ACW_CODEX_LIVE', None)
    env.pop('ACW_CODEX_TOOLS', None)
    return env


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('modules', nargs='*', help='Top-level test module names')
    parser.add_argument('--list', action='store_true', help='List selected modules without running')
    parser.add_argument('--ui', action='store_true', help='Use the current UI module set')
    parser.add_argument('--visible', action='store_true', help='Show fixture UI windows')
    parser.add_argument('--timeout', type=int, default=180, help='Seconds per module')
    args = parser.parse_args(argv)
    available = available_modules()
    selected = list(dict.fromkeys(args.modules or (UI_MODULES if args.ui else available)))
    unknown = [name for name in selected if name not in available]
    if unknown:
        parser.error('Unknown top-level test modules: ' + ', '.join(unknown))
    if args.timeout < 1:
        parser.error('--timeout must be positive')
    if args.list:
        print('\n'.join(selected))
        return 0
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    out = ROOT / 'evidence' / 'test-runs' / stamp
    out.mkdir(parents=True, exist_ok=False)
    report = {
        'timestamp': stamp,
        'scope': 'Offline fixtures; one process per module; no live opt-ins',
        'visible': args.visible,
        'modules': [],
        'status': 'RUNNING',
    }
    def save():
        (out / 'result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    save()
    env = child_environment(args.visible)
    for name in selected:
        started = time.monotonic()
        log = out / (name + '.log')
        print('RUN ' + name, flush=True)
        with log.open('w', encoding='utf-8') as stream:
            try:
                result = subprocess.run(
                    [sys.executable, '-X', 'utf8', '-m', 'unittest', name, '-v'],
                    cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT,
                    timeout=args.timeout, check=False,
                )
                row = {'module': name, 'status': 'PASS' if result.returncode == 0 else 'FAIL',
                       'exit_code': result.returncode}
            except subprocess.TimeoutExpired:
                row = {'module': name, 'status': 'TIMEOUT', 'exit_code': None}
        row.update(seconds=round(time.monotonic() - started, 3), log=log.name)
        report['modules'].append(row)
        save()
        print(row['status'] + ' ' + name, flush=True)
        if row['status'] != 'PASS':
            print(log.read_text(encoding='utf-8', errors='replace')[-6000:], flush=True)
    report['status'] = 'PASS' if all(row['status'] == 'PASS' for row in report['modules']) else 'FAIL'
    save()
    print('Report: ' + str(out / 'result.json'), flush=True)
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
