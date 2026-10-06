"""Explicit live GUI acceptance; human approvals only, original isolated repo only."""
from pathlib import Path
import sys,json,time,tempfile,subprocess,datetime,traceback
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'vendor'),str(ROOT)]
from PySide6.QtCore import QTimer,Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from acw.core import WorkspaceCore
from acw.ui import MainWindow
from acw.adapters.codex import CodexAdapter
from acw.adapters.claude import ClaudeAdapter
from acw.adapters.dot import DotAdapter
from acw.security import sanitize
REPO=ROOT/'tests/codex-write-7z2jdqab';assert REPO.is_dir();assert (REPO/'fixture.py').read_text(encoding='utf-8')=='def add(a, b):\n    return a - b\n'
DATA=Path(tempfile.mkdtemp(prefix='live-codex-ui-',dir=ROOT/'tests'));OUT=ROOT/'evidence/live-codex-ui';OUT.mkdir(exist_ok=True)
app=QApplication([]);core=WorkspaceCore(DATA)
core.set_adapter('claude',ClaudeAdapter(core.make_emitter('claude'),executable=''))
core.set_adapter('dot',DotAdapter(core.make_emitter('dot')))
a=core.set_adapter('codex',CodexAdapter(core.make_emitter('codex'),executable=r'C:\Users\ryant\AppData\Local\OpenAI\Codex\bin\8aaf1547b825b104\codex.exe',timeout=30))
p=core.create_project('ISOLATED HUMAN APPROVAL ACCEPTANCE',str(REPO));core.select_project(p['id']);core.create_task('Real Codex fixture.py approval - human only')
w=MainWindow(core);w.setWindowTitle('AI Collaboration Workspace - ISOLATED Codex human approval');w.show();panel=w.panels['codex']
report={'status':'RUNNING','scope':'Real source Python/Qt UI; NOT compiled EXE launch acceptance','cwd':str(REPO),'data_dir':str(DATA),'model':'gpt-6.1-sol','effort':'medium','automatic_approval':False,'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'approval_cards':[]};stage='connect';started=time.monotonic();seen=set();closing=False;saw_busy=False
def save(): (OUT/'result.json').write_text(json.dumps(sanitize(report),ensure_ascii=False,indent=2),encoding='utf-8')
def note(text): print(text,flush=True);save()
def finish(status,reason):
 global closing
 if closing:return
 closing=True;timer.stop();report.update(status=status,reason=reason,permissions=a.diagnostics().get('permissions'),session=a.session_id)
 try:
  if a.state=='Busy':a.stop()
  a.disconnect()
  git=r'C:\Program Files\Git\cmd\git.exe'
  diff=subprocess.run([git,'-C',str(REPO),'diff','--','fixture.py'],capture_output=True,text=True,encoding='utf-8',timeout=15)
  test=subprocess.run([sys.executable,'-B','-m','unittest','-v','test_fixture.py'],cwd=REPO,capture_output=True,text=True,encoding='utf-8',timeout=15)
  report.update(diff=diff.stdout,verification_exit=test.returncode,verification_output=test.stdout+test.stderr,file_written='return a + b' in (REPO/'fixture.py').read_text(encoding='utf-8'))
  report['checks']={'actual_file_write':report['file_written'],'actual_git_diff':bool(diff.stdout),'tests_passed':test.returncode==0,'native_file_events':any(e['type']=='file' for e in core.events(agent='codex',limit=2000)),'native_diff_events':any(e['type']=='diff' for e in core.events(agent='codex',limit=2000))}
  w.grab().save(str(OUT/'final-window.png'))
 except Exception as exc:report['verification_error']=str(exc)
 save();note('FINISHED '+status+' '+reason)
 for pane in w.panels.values():pane.set_state('Disconnected')
 w.close();QTimer.singleShot(100,app.quit)
def tick():
 global stage,saw_busy
 try:
  if time.monotonic()-started>900:finish('BLOCKED','15 minute human-interaction window elapsed; official cancel, no automatic grant');return
  if stage=='connect':QTest.mouseClick(panel.connect_button,Qt.LeftButton);stage='handshake';note('CONNECTING official Codex, original isolated repo')
  elif stage=='handshake' and a.state=='Connected' and not w.workers:
   w.refresh_agent('codex');mi=panel.model.findData('gpt-6.1-sol');assert mi>=0,'Requested Sol model not advertised';panel.model.setCurrentIndex(mi)
   ei=panel.effort.findData('medium');assert ei>=0,'Medium effort not advertised';panel.effort.setCurrentIndex(ei)
   QTest.mouseClick(panel.new_button,Qt.LeftButton);stage='session'
  elif stage=='session' and a.session_id and not w.workers:
   w.reload_context();w.refresh_agent('codex');panel.model.setCurrentIndex(panel.model.findData('gpt-6.1-sol'));panel.effort.setCurrentIndex(panel.effort.findData('medium'))
   prompt=('Explicit harmless acceptance ONLY in '+str(REPO)+'. Modify only fixture.py: change return a - b to return a + b using native file edit. Then run '+sys.executable+' -B -m unittest -v test_fixture.py and inspect git diff. No unrelated paths, credentials, network, installation or broad permission request. Preserve inherited sandbox; emit official specific approval and wait for the human user. Briefly report actual results.')
   report['prompt']=prompt;panel.input.setPlainText(prompt);assert panel.send_button.isEnabled();QTest.mouseClick(panel.send_button,Qt.LeftButton);stage='turn';report['permissions']=a.diagnostics().get('permissions');note('SENT actual gpt-6.1-sol / medium through visible Send button')
  elif stage=='turn':
   if a.state=='Busy':saw_busy=True
   for request_id,card in list(panel.approvals.items()):
    if request_id not in seen:
     seen.add(request_id);card.toggle.setChecked(True);panel.scroll.ensureWidgetVisible(card);card.repaint();app.processEvents();w.grab().save(str(OUT/('approval-'+request_id.replace(':','-')+'.png')))
     report['approval_cards'].append({'request_id':request_id,'visible':card.isVisible(),'payload':next((e for e in core.events(agent='codex',limit=2000) if (e.get('request_id') or e.get('payload',{}).get('request_id'))==request_id and e['type']=='approval'),{})})
     report['status']='WAITING_USER';note('HUMAN APPROVAL CARD VISIBLE: '+request_id+'; CODEX right panel -> Approve... -> review confirmation -> Yes. Agent will never click these.')
   if saw_busy and a._turn_done.is_set() and a.state!='Busy' and a.session_id and time.monotonic()-started>4:
    responses=[e for e in core.events(agent='codex',limit=2000) if e['type']=='approval_response'];report['human_approval_responses']=responses;report['last_error']=a.last_error
    finish('COMPLETED','Official turn ended after visible user interaction or backend error')
 except Exception as exc:report['traceback']=traceback.format_exc();finish('BLOCKED',str(exc))
timer=QTimer();timer.timeout.connect(tick);timer.start(250);save();app.exec();core.close()
