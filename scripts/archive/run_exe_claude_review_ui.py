"""One authorized official-Claude review in a new visible isolated Workspace.
No compile/install/EXE execution, Dot calls, auto approval, or existing-session use.
The review window remains open for the human; this is not an orchestrator.
"""
from pathlib import Path
import argparse, datetime, hashlib, json, shutil, sys, tempfile, time, traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'vendor'), str(ROOT)]
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from acw.core import WorkspaceCore
from acw.ui import MainWindow
from acw.adapters.claude import ClaudeAdapter
from acw.security import sanitize

OUT = ROOT / 'evidence' / 'exe-claude-primary-review'; OUT.mkdir(exist_ok=True)
parser = argparse.ArgumentParser()
parser.add_argument('--resume-existing', action='store_true')
options = parser.parse_args()
previous = json.loads((OUT / 'result.json').read_text(encoding='utf-8')) if options.resume_existing else None
if previous:
    BASE = Path(previous['data']).resolve().parent
    if not BASE.is_relative_to(ROOT / 'tests') or not BASE.name.startswith('exe-claude-review-'):
        raise ValueError('Refuse resuming outside the original isolated review directory')
    archive = OUT / ('previous-attempt-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    archive.mkdir()
    for file in OUT.iterdir():
        if file.is_file() and file.suffix in ('.json', '.md', '.png'):
            shutil.copy2(file, archive / file.name)
else:
    BASE = Path(tempfile.mkdtemp(prefix='exe-claude-review-', dir=ROOT / 'tests'))
REPO = BASE / 'review-input'; REPO.mkdir(exist_ok=True)
sources = ['scripts/Launcher.cs', 'install.ps1',
           'evidence/EXE-SECURITY-BLOCKER.md',
           'evidence/LAUNCHER-STATIC-REVIEW.md',
           'evidence/launcher-static-build-chain.json',
           'evidence/source-launcher-provenance.json']
inputs = []
for name in sources:
    original = ROOT / name
    raw = original.read_bytes()
    text = sanitize(raw.decode('utf-8-sig'))
    destination = REPO / original.name
    destination.write_text(text, encoding='utf-8')
    inputs.append({'source': name, 'sha256': hashlib.sha256(raw).hexdigest(),
                   'review_copy': str(destination), 'text': text})

PROMPT = '''You are Claude, the PRIMARY REVIEWER for this real collaboration task.
Review only the supplied text below. This is a proposal stage, NOT implementation.
The user selected EXE investigation as the Claude -> G8 Dot second review -> Codex
implementation collaboration task. Reply in Traditional Chinese naturally.

Latest human evidence (supersedes older unknown/absent statements in records):
McAfee detected Real Protect-LS!3078cfed47ee on 2026-10-05 at 12:04 local.
The human later restored the file manually. Restored file: 5120 bytes,
SHA256 EF202EE2CAF2171805B21F0C22FAB1069FE1CC92EABE7889ED12A02A8BB39005,
matching prior source/install hash; NotSigned. Actual installed location is under
Codex package LocalCache/Local/AI-Collaboration-Workspace/app.
Existing Microsoft csc.exe signature is Valid. A complete original compiler
command/output has not been recovered. Hash agreement does not prove full binary
provenance, a false positive, or runtime safety. No security rejection cause is
established by the launcher code alone.

Produce a concrete review/proposal covering: verified facts versus unknown cause;
source changes that can safely improve launcher/config/argv/runtime identity and
startup readiness; transparent reproducible build/provenance and legitimate signing
or vendor review options; precise approval boundaries; meaningful tests and rollback.
Point out any installer deployment/data safety implications. Prefer small defensible
changes; do not claim that reliability improvements will remove malware detection.

Do NOT run commands, compile, execute EXEs, install/copy/restore a blocked binary,
modify files, contact vendors/hash services, browse, use connectors/MCP/subagents,
read credentials/auth/tokens/cookies, change security settings, add exclusions,
disable defenses, use bypass/acceptEdits, or evade detection by renaming, moving,
obfuscating or changing packaging. No tools are needed: all review inputs follow.
Any permission request must remain for human review; no automatic grants.
Do not promote Qt/Python launch success into compiled-EXE acceptance.
Stop after your proposal; G8 Dot will perform the second review before Codex changes.
'''
for item in inputs:
    PROMPT += '\n\n--- REVIEW INPUT: ' + item['source'] + ' ---\n' + item['text']
(OUT / 'input-manifest.json').write_text(json.dumps(
    [{k: v for k, v in item.items() if k != 'text'} for item in inputs], indent=2), encoding='utf-8')
if previous:
    # Retry exactly the already reviewed safe prompt, not a new task or scope.
    PROMPT = (OUT / 'prompt.md').read_text(encoding='utf-8')
else:
    (OUT / 'prompt.md').write_text(PROMPT, encoding='utf-8')

app = QApplication([])
core = WorkspaceCore(BASE / 'data')
core.set_setting('legacy.root', str(BASE / 'no-legacy'))
adapter = core.set_adapter('claude', ClaudeAdapter(core.make_emitter('claude'),
    executable=r'C:\Users\ryant\AppData\Local\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude-code\2.1.286\635c1867224a\claude.exe', timeout=45))
if previous:
    task = core.current_task
    if not task or task['id'] != previous['task_id'] or task.get('claude_session') != previous['session_id']:
        raise ValueError('Original review task/session mapping changed; no retry performed')
    project = core.current_project
    adapter.session_id = previous['session_id']; adapter._resume = True
else:
    project = core.create_project('EXE SECURITY REVIEW - ISOLATED', REPO)
    core.select_project(project['id'])
    task = core.create_task('Claude primary review: EXE security and launcher proposal',
                            status='REVIEWING', current_owner='claude')
window = MainWindow(core)
window.setWindowTitle('AI Collaboration Workspace - CLAUDE PRIMARY EXE REVIEW (NO BUILD)' + (' - RESUME SAME TASK' if previous else ''))
window.show()
report = {'status': 'RUNNING', 'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'task_id': task['id'], 'project_id': project['id'], 'data': str(BASE / 'data'),
          'repo': str(REPO), 'scope': 'Official Claude primary review only, source Qt UI; no EXE execution',
          'approval_requests': [], 'dot_calls': 0, 'auto_approvals': 0,
          'compile_or_exe_execution': False, 'existing_sessions_modified': False}
if previous:
    report.update(resume_existing_task=True, resumed_session=previous['session_id'],
                  previous_attempt_archive=str(archive), automatic_retries=0,
                  existing_sessions_modified=True, only_original_review_session_resumed=True,
                  original_user_sessions_modified=False)
stage = 'connect'; seen = set(); started = time.monotonic(); done = False
baseline_messages = {m['id'] for m in core.messages(agent='claude')}

def save():
    (OUT / 'result.json').write_text(json.dumps(sanitize(report), ensure_ascii=False, indent=2), encoding='utf-8')

def finish(status, reason):
    global done
    if done: return
    done = True; timer.stop(); window.poll_events()
    report.update(status=status, reason=reason, session_id=adapter.session_id,
                  diagnostics=core.diagnostics('claude'),
                  completed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    events = [e for e in core.events(agent='claude', limit=10000) if e['type'] not in ('raw', 'message_delta')]
    (OUT / 'public-events.json').write_text(json.dumps(sanitize(events), ensure_ascii=False, indent=2), encoding='utf-8')
    (OUT / 'messages.json').write_text(json.dumps(sanitize(core.messages(agent='claude')), ensure_ascii=False, indent=2), encoding='utf-8')
    window.grab().save(str(OUT / 'window.png')); save()
    print(status + ': ' + reason, flush=True)
    # Leave this new review window/session visible. No old windows are touched.

def tick():
    global stage
    try:
        window.poll_events(); panel = window.panels['claude']
        for rid, event in panel.pending_approval_events.items():
            if rid not in seen:
                seen.add(rid); report['approval_requests'].append({'id': rid, 'request': event}); save()
                print('PENDING HUMAN PERMISSION: ' + rid + '; no approval issued', flush=True)
        if adapter.state in ('Error', 'Offline'):
            finish('BLOCKED', adapter.last_error); return
        if time.monotonic() - started > 240:
            finish('BLOCKED', 'Review timeout; no retry or permission grant'); return
        if stage == 'connect':
            QTest.mouseClick(panel.connect_button, Qt.LeftButton); stage = 'resume-connected' if previous else 'new'
        elif stage == 'resume-connected' and adapter.state == 'Connected' and not window.workers:
            window.refresh_agent('claude'); stage = 'send'
        elif stage == 'new' and adapter.state == 'Connected' and not window.workers:
            window.refresh_agent('claude'); QTest.mouseClick(panel.new_button, Qt.LeftButton); stage = 'send'
        elif stage == 'send' and adapter.session_id and not window.workers:
            window.reload_context(); panel.input.setPlainText(PROMPT)
            QTest.mouseClick(panel.send_button, Qt.LeftButton); stage = 'response'; save()
        elif stage == 'response' and adapter.state == 'Connected' and not window.workers:
            responses = [m for m in core.messages(agent='claude') if m['role'] == 'assistant' and m['status'] == 'complete' and m['id'] not in baseline_messages]
            if not responses: return
            message = responses[-1]
            (OUT / 'claude-proposal.md').write_text(message['content'], encoding='utf-8')
            preview = core.prepare_handoff(message['id'], 'dot',
                annotation='G8 Dot second review requested. Draft only; human sends via approved Dot UI. No implementation/build authorized yet.')
            (OUT / 'handoff-draft.json').write_text(json.dumps(sanitize(preview), ensure_ascii=False, indent=2), encoding='utf-8')
            report['source_message_id'] = message['id']; report['handoff_id'] = preview['id']
            finish('REVIEW_READY', 'Official Claude proposal preserved; Dot handoff prepared but NOT sent')
    except Exception as exc:
        report['traceback'] = traceback.format_exc(); finish('BLOCKED', str(exc))

timer = QTimer(); timer.timeout.connect(tick); timer.start(150); save()
print('VISIBLE REVIEW TASK ' + task['id'] + ' DATA ' + str(BASE / 'data'), flush=True)
app.exec(); core.close()
