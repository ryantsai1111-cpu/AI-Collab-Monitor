"""Official Claude/Codex real UI collaboration acceptance. Dot stays blocked.
Fresh test-owned sessions only; no approval callback invoked by this script.
"""
from pathlib import Path
import sys,json,time,tempfile,datetime,traceback
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'vendor'),str(ROOT)]
from PySide6.QtWidgets import QApplication,QDialog,QLineEdit,QPlainTextEdit,QPushButton
from PySide6.QtCore import QTimer,Qt
from PySide6.QtTest import QTest
from acw.core import WorkspaceCore
from acw.ui import MainWindow,HandoffDialog
from acw.adapters.claude import ClaudeAdapter
from acw.adapters.codex import CodexAdapter
from acw.adapters.dot import DotAdapter
from acw.security import sanitize
OUT=ROOT/'evidence/live-collaboration-ui';OUT.mkdir(exist_ok=True)
DATA=Path(tempfile.mkdtemp(prefix='live-collaboration-',dir=ROOT/'tests'));REPO=ROOT/'tests/sandbox-claude';assert (REPO/'acw-fixture.txt').exists()
app=QApplication([]);core=WorkspaceCore(DATA);core.set_setting('legacy.root',str(DATA/'no-legacy'))
claude=core.set_adapter('claude',ClaudeAdapter(core.make_emitter('claude'),executable=r'C:\Users\ryant\AppData\Local\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude-code\2.1.286\635c1867224a\claude.exe',timeout=40))
codex=core.set_adapter('codex',CodexAdapter(core.make_emitter('codex'),executable=r'C:\Users\ryant\AppData\Local\OpenAI\Codex\bin\8aaf1547b825b104\codex.exe',timeout=40))
core.set_adapter('dot',DotAdapter(core.make_emitter('dot')));project=core.create_project('OFFICIAL LIVE UI - ISOLATED',REPO);core.select_project(project['id']);task=core.create_task('Claude A to Codex and back - official UI')
window=MainWindow(core);window.setWindowTitle('AI Collaboration Workspace - OFFICIAL ISOLATED TWO AGENT TEST');window.show()
report={'status':'RUNNING','scope':'Real official Claude/Codex through actual source Qt UI, isolated repo/data. NOT Dot or compiled EXE acceptance','data_dir':str(DATA),'cwd':str(REPO),'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'codex_model':'gpt-6.1-sol','codex_effort':'medium','checks':{},'approval_requests':[]};stage='connect';stage_time=time.monotonic();seen=set();finished=False;first_A=None;codex_response=None;resume_sid=None;had_busy=False;stopping=False;seen_delta=False;heartbeat=0

def save(): (OUT/'result.json').write_text(json.dumps(sanitize(report),ensure_ascii=False,indent=2),encoding='utf-8')
def note(text): print(text,flush=True);save()
def transition(next_stage):
 global stage,stage_time,had_busy
 stage=next_stage;stage_time=time.monotonic();had_busy=False;note('STAGE '+stage)
def ready():return not window.workers and all(a.state=='Connected' for a in (claude,codex))
def click(text):
 control=next(x for x in window.findChildren(QPushButton) if x.text().replace('&','').replace('\u2026','...')==text);QTest.mouseClick(control,Qt.LeftButton)
def send(agent,prompt):
 panel=window.panels[agent];window.refresh_agent(agent)
 if agent=='codex':
  panel.model.setCurrentIndex(panel.model.findData('gpt-6.1-sol'));panel.effort.setCurrentIndex(panel.effort.findData('medium'))
 panel.input.setPlainText(prompt);assert panel.send_button.isEnabled();QTest.mouseClick(panel.send_button,Qt.LeftButton)
def completed(agent,after):return [m for m in core.messages(agent=agent) if m['role']=='assistant' and m['status']=='complete' and m.get('timestamp','')>=after]
def finish(status,reason):
 global finished
 if finished:return
 finished=True;timer.stop();report.update(status=status,reason=reason,session_mapping={a:core.current_task.get(a+'_session') for a in ('claude','dot','codex')},diagnostics={a:core.diagnostics(a) for a in ('claude','codex')},handoffs=core.handoffs())
 public_events=[e for e in core.events(limit=10000) if e['type'] not in ('raw','event','message_delta')]
 (OUT/'public-events.json').write_text(json.dumps(sanitize(public_events),ensure_ascii=False,indent=2),encoding='utf-8');(OUT/'messages.json').write_text(json.dumps(sanitize(core.messages()),ensure_ascii=False,indent=2),encoding='utf-8');window.grab().save(str(OUT/'final-window.png'));save();note('FINISHED '+status+' '+reason)
 for a in (claude,codex):
  try:
   if a.state=='Busy':a.stop()
   a.disconnect()
  except Exception:pass
 for panel in window.panels.values():panel.set_state('Disconnected')
 window.close();QTimer.singleShot(100,app.quit)
def tick():
 global first_A,codex_response,resume_sid,had_busy,stopping,seen_delta,heartbeat
 heartbeat+=1
 try:
  window.poll_events()
  for agent,panel in window.panels.items():
   for rid,card in panel.approvals.items():
    if (agent,rid) not in seen:
     seen.add((agent,rid));report['approval_requests'].append({'agent':agent,'id':rid});report['status']='WAITING_USER';card.toggle.setChecked(True);panel.scroll.ensureWidgetVisible(card.approval_actions[-1]);window.grab().save(str(OUT/('pending-'+agent+'-'+rid.replace(':','-')+'.png')));note('HUMAN APPROVAL NEEDED '+agent+' '+rid+' - no automatic grant; Review button is fixed above activity viewport')
  if any(a.state in ('Error','Offline') for a in (claude,codex)):
   finish('BLOCKED','Official backend error: '+str({a.agent:a.last_error for a in (claude,codex) if a.last_error}));return
  if time.monotonic()-stage_time>150 and not report['approval_requests']:finish('BLOCKED','Stage timeout '+stage+'; no policy changed');return
  if time.monotonic()-stage_time>900:finish('BLOCKED','Human interaction window expired; official cancel');return
  if stage=='connect':
   for agent in ('claude','codex'):QTest.mouseClick(window.panels[agent].connect_button,Qt.LeftButton)
   transition('handshake')
  elif stage=='handshake' and ready():
   for agent in ('claude','codex'):window.refresh_agent(agent)
   assert 'gpt-6.1-sol' in codex.list_models() and 'medium' in codex.list_efforts('gpt-6.1-sol');core.set_setting('agent.codex',{'default_model':'gpt-6.1-sol','default_effort':'medium'});report['checks']['actual_model_effort_capability']=True
   for agent in ('claude','codex'):QTest.mouseClick(window.panels[agent].new_button,Qt.LeftButton)
   transition('sessions')
  elif stage=='sessions' and ready() and claude.session_id and codex.session_id:
   window.reload_context();report['checks']['two_test_sessions_mapped']=all(core.current_task.get(a.agent+'_session')==a.session_id for a in (claude,codex));click('Sync to agents');transition('sync')
  elif stage=='sync' and ready():
   report['checks']['project_cwd_sync']=claude.cwd==codex.cwd==str(REPO);report['checks']['dot_metadata_only']=core.adapters['dot'].cwd=='' and core.adapters['dot'].metadata['project_name']==project['name'];report['claude_prompt_time']=datetime.datetime.now(datetime.timezone.utc).isoformat()
   send('claude','Harmless isolated acceptance: use Read only on '+str(REPO/'acw-fixture.txt')+'. Then reply exactly A. No other tools, writes, installs or services.');transition('literal_A')
  elif stage=='literal_A' and ready() and completed('claude',report['claude_prompt_time']):
   first_A=completed('claude',report['claude_prompt_time'])[-1];report['checks']['actual_claude_literal_A']=first_A['content'].strip()=='A';report['checks']['actual_claude_tool_UI']=any(e['type']=='tool_result' for e in core.events(agent='claude',limit=1000)) and bool(window.panels['claude'].findChildren(__import__('acw.ui',fromlist=['EventCard']).EventCard));window.grab().save(str(OUT/'claude-literal-A.png'));report['handoff_to_codex_time']=datetime.datetime.now(datetime.timezone.utc).isoformat()
   window.handoff_mode.setCurrentText('Assisted')
   def confirm():
    d=app.activeModalWidget()
    if not isinstance(d,HandoffDialog):QTimer.singleShot(30,confirm);return
    assert d.findChild(QPlainTextEdit,'handoff_source').toPlainText()==first_A['content'];d.annotation.setPlainText('Isolated acceptance: acknowledge original A with exactly A. No tools, writes, installs or services.');d.grab().save(str(OUT/'actual-claude-to-codex-preview.png'));QTest.mouseClick(d.send_button,Qt.LeftButton)
   QTimer.singleShot(40,confirm);window.forward(first_A,'codex');transition('codex_handoff')
  elif stage=='codex_handoff' and ready() and completed('codex',report['handoff_to_codex_time']):
   codex_response=completed('codex',report['handoff_to_codex_time'])[-1];h=core.handoffs()[0];report['checks']['actual_claude_to_codex_exact_original']=h['source_message']==first_A['content'] and ('Original content:\n'+first_A['content']) in h['handoff_message'] and h['status']=='sent';report['checks']['source_annotation_separate']=h['annotation'] not in h['source_message'];report['handoff_back_time']=datetime.datetime.now(datetime.timezone.utc).isoformat()
   def confirm():
    d=app.activeModalWidget()
    if not isinstance(d,HandoffDialog):QTimer.singleShot(30,confirm);return
    d.annotation.setPlainText('Harmless isolated acceptance: reply exactly C. No tools, writes, installs or services.');d.grab().save(str(OUT/'actual-codex-to-claude-preview.png'));QTest.mouseClick(d.send_button,Qt.LeftButton)
   QTimer.singleShot(40,confirm);window.forward(codex_response,'claude');transition('claude_handoff')
  elif stage=='claude_handoff' and ready() and completed('claude',report['handoff_back_time']):
   hs=core.handoffs();report['checks']['actual_codex_to_claude']=len(hs)==2 and all(h['status']=='sent' for h in hs);report['checks']['task_notes_not_automatically_sent']=not core.current_task['notes'];resume_sid=codex.session_id;QTest.mouseClick(window.panels['codex'].connect_button,Qt.LeftButton);transition('disconnect')
  elif stage=='disconnect' and codex.state=='Disconnected' and not window.workers:
   window.refresh_agent('codex');report['checks']['disconnect_shown']=window.panels['codex'].state.text()=='Disconnected';QTest.mouseClick(window.panels['codex'].connect_button,Qt.LeftButton);transition('reconnect')
  elif stage=='reconnect' and ready():
   window.reload_context();window.refresh_agent('codex');p=window.panels['codex'];p.session.setCurrentIndex(p.session.findData(resume_sid));assert p.resume_button.isEnabled();QTest.mouseClick(p.resume_button,Qt.LeftButton);transition('resume')
  elif stage=='resume' and ready():
   report['checks']['actual_UI_explicit_resume']=codex.session_id==resume_sid;send('codex','Harmless isolated streaming/cancel acceptance: output150 numbered lines about counting. No tools, file writes or services.');transition('stop_turn')
  elif stage=='stop_turn':
   if codex.state=='Busy':had_busy=True
   deltas=[e for e in core.events(agent='codex',limit=5000) if e['type']=='message_delta']
   if had_busy and len(deltas)>3 and not stopping:
    report['checks']['UI_render_during_real_stream']=any(c.body.toPlainText().strip() for c in window.panels['codex'].cards.values());window.grab().save(str(OUT/'real-stream-before-stop.png'));QTest.mouseClick(window.panels['codex'].stop_button,Qt.LeftButton);stopping=True;note('Requested official Stop through actual Qt Stop button')
   if stopping and ready():
    report['checks']['actual_UI_stop']=any(e['type']=='stop' for e in core.events(agent='codex',limit=5000));report['checks']['UI_heartbeat_during_live_work']=heartbeat>20;report['checks']['codex_policy_not_changed']=codex.diagnostics()['permissions']['sandbox']['type']=='readOnly';finish('PASS' if all(report['checks'].values()) else 'FAIL','Official two-agent UI handoff/resume/stream/stop checks completed')
 except Exception as exc:report['traceback']=traceback.format_exc();finish('BLOCKED',str(exc))
timer=QTimer();timer.timeout.connect(tick);timer.start(150);save();app.exec();core.close()
