"""One authorized official-Claude read-only change review, same isolated session.
No compiler/installer/Workspace EXE, Dot call, auto approval or old window close.
"""
from pathlib import Path
import datetime,json,sys,time,traceback
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'vendor'),str(ROOT)]
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer,Qt
from PySide6.QtTest import QTest
from acw.core import WorkspaceCore
from acw.ui import MainWindow
from acw.adapters.claude import ClaudeAdapter
from acw.security import sanitize

primary=json.loads((ROOT/'evidence/exe-claude-primary-review/result.json').read_text(encoding='utf-8'))
OUT=ROOT/'evidence/exe-claude-change-review';OUT.mkdir(exist_ok=True)
if (OUT/'result.json').exists():raise RuntimeError('Existing change-review attempt; inspect rather than overwrite/retry')
data=Path(primary['data']).resolve()
if not data.is_relative_to(ROOT/'tests') or primary['session_id']!='45bbb2bc-f8af-4d64-888b-5b69643fb16b':
    raise ValueError('Only the original explicit isolated review session may be resumed')
PROMPT='''G8 Dot completed the second review: APPROVE_WITH_CONDITIONS for source/offline tests/docs ONLY. Codex has prepared the attached source-only changes. You are the actual Claude reviewer of these changes, not the implementer. Reply naturally in Traditional Chinese. Assess correctness, regression risk, fail-closed quarantine/preflight behavior, argv/source policy evidence limits, and whether the code respects G8 conditions. Distinguish blockers from optional improvements. Do NOT assert compiler/deployment/EXE/antivirus acceptance: none were run. Do not repeat unverified claims that old binary must be retired or that compiler determinism/MVID was verified. Path virtualization is an alias observation, not proof the human shortcut is wrong.

All required inputs are inline. DO NOT use tools, shell, filesystem, connectors/MCP, browser, subagents, credentials/auth/tokens/cookies, security settings, compilation, installation, EXE launch, signing, uploads, edits or permission changes. Do not auto-approve. Review source text only, ending with your actual recommendation and precise remaining issues. No implementation or live tests in this turn.
'''
for relative in ['evidence/exe-source-hardening/G8-SECOND-REVIEW.md',
                 'evidence/exe-source-hardening/offline-result.json',
                 'evidence/exe-source-hardening/SECURITY-ADDENDUM.md',
                 'evidence/exe-source-hardening/source.diff']:
    PROMPT+='\n\n--- REVIEW INPUT '+relative+' ---\n'+(ROOT/relative).read_text(encoding='utf-8')
PROMPT=sanitize(PROMPT)
(OUT/'prompt.md').write_text(PROMPT,encoding='utf-8')
app=QApplication([]);core=WorkspaceCore(data)
task=core.current_task
if not task or task['id']!=primary['task_id'] or task.get('claude_session')!=primary['session_id']:
    raise ValueError('Original task/session mapping changed; do not create a replacement task')
adapter=core.set_adapter('claude',ClaudeAdapter(core.make_emitter('claude'),
    executable=primary['diagnostics']['executable'],timeout=45))
adapter.session_id=primary['session_id'];adapter._resume=True
window=MainWindow(core)
window.setWindowTitle('AI Collaboration Workspace - CLAUDE SOURCE CHANGE REVIEW - SAME TASK - NO BUILD')
window.show()
baseline={m['id'] for m in core.messages(agent='claude')}
report=dict(status='RUNNING',started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    task_id=task['id'],session_id=adapter.session_id,data=str(data),scope='Official Claude read-only source change review',
    dot_calls=0,auto_approvals=0,compiler_invoked=False,installer_invoked=False,workspace_exe_executed=False,
    original_user_windows_closed=False,approval_requests=[])
stage='connect';started=time.monotonic();done=False;seen=set()

def save():
    (OUT/'result.json').write_text(json.dumps(sanitize(report),ensure_ascii=False,indent=2),encoding='utf-8')

def finish(status,reason):
    global done
    if done:return
    done=True;timer.stop();window.poll_events()
    report.update(status=status,reason=reason,completed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  diagnostics=core.diagnostics('claude'))
    events=[e for e in core.events(agent='claude',limit=10000) if e['type'] not in ('raw','message_delta') and e['timestamp']>=report['started_utc']]
    (OUT/'public-events.json').write_text(json.dumps(sanitize(events),ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'messages.json').write_text(json.dumps(sanitize([m for m in core.messages(agent='claude') if m['id'] not in baseline]),ensure_ascii=False,indent=2),encoding='utf-8')
    window.grab().save(str(OUT/'window.png'));save();print(status+': '+reason,flush=True)
    # Keep only this newly created window open. Existing windows are untouched.

def tick():
    global stage
    try:
        window.poll_events();panel=window.panels['claude']
        for rid,event in panel.pending_approval_events.items():
            if rid not in seen:
                seen.add(rid);report['approval_requests'].append({'id':rid,'request':event});save()
                print('PENDING HUMAN APPROVAL '+rid+'; no grant issued',flush=True)
        if adapter.state in ('Error','Offline'):finish('BLOCKED',adapter.last_error);return
        if time.monotonic()-started>240:finish('BLOCKED','Official review timeout; no retry or permission grant');return
        if stage=='connect':
            QTest.mouseClick(panel.connect_button,Qt.LeftButton);stage='send'
        elif stage=='send' and adapter.state=='Connected' and not window.workers:
            window.refresh_agent('claude');window.reload_context()
            panel.input.setPlainText(PROMPT);window.workspace_scroll.ensureWidgetVisible(panel.send_button)
            QTest.mouseClick(panel.send_button,Qt.LeftButton);stage='result';save()
        elif stage=='result' and adapter.state=='Connected' and not window.workers:
            responses=[m for m in core.messages(agent='claude') if m['id'] not in baseline and m['role']=='assistant' and m['status']=='complete']
            if not responses:return
            message=responses[-1];(OUT/'claude-change-review.md').write_text(message['content'],encoding='utf-8')
            draft=core.prepare_handoff(message['id'],'dot',annotation='G8 Dot review of Claude source-change assessment; draft only, not sent. No build/deployment/EXE approval.')
            (OUT/'handoff-draft.json').write_text(json.dumps(sanitize(draft),ensure_ascii=False,indent=2),encoding='utf-8')
            report.update(source_message_id=message['id'],handoff_id=draft['id'])
            finish('REVIEW_READY','Actual official Claude change assessment saved; handoff NOT sent')
    except Exception as error:report['traceback']=traceback.format_exc();finish('BLOCKED',str(error))

timer=QTimer();timer.timeout.connect(tick);timer.start(150);save()
print('SAME TASK '+task['id']+' SAME CLAUDE SESSION '+adapter.session_id,flush=True)
app.exec();core.close()
