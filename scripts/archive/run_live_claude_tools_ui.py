"""Official Claude isolated file/command UI check; never grants an approval."""
from pathlib import Path
import sys,json,time,tempfile,datetime,subprocess,traceback,argparse
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'vendor'),str(ROOT)]
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer,Qt
from PySide6.QtTest import QTest
from acw.core import WorkspaceCore
from acw.ui import MainWindow,EventCard
from acw.adapters.claude import ClaudeAdapter
from acw.security import sanitize
OUT=ROOT/'evidence/live-claude-tools-ui';OUT.mkdir(exist_ok=True)
parser=argparse.ArgumentParser();parser.add_argument('--repo');args=parser.parse_args()
BASE=Path(tempfile.mkdtemp(prefix='claude-tools-',dir=ROOT/'tests'))
if args.repo:
 REPO=Path(args.repo).resolve();assert REPO.is_relative_to(ROOT/'tests') and REPO.parent.name.startswith('claude-tools-');assert (REPO/'fixture.py').read_text(encoding='utf-8')=='def add(a, b):\n    return a - b\n','Original isolated baseline changed; refusing overwrite'
else:
 REPO=BASE/'repo';REPO.mkdir();(REPO/'fixture.py').write_text('def add(a, b):\n    return a - b\n',encoding='utf-8');(REPO/'test_fixture.py').write_text('import unittest\nfrom fixture import add\nclass TestFixture(unittest.TestCase):\n def test_add(self): self.assertEqual(add(2,3),5)\n',encoding='utf-8')
app=QApplication([]);core=WorkspaceCore(BASE/'data');adapter=core.set_adapter('claude',ClaudeAdapter(core.make_emitter('claude'),executable=r'C:\Users\ryant\AppData\Local\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude-code\2.1.286\635c1867224a\claude.exe',timeout=40));project=core.create_project('OFFICIAL CLAUDE TOOLS - ISOLATED',REPO);core.select_project(project['id']);core.create_task('Claude file edit and command UI');window=MainWindow(core);window.show()
window.setWindowTitle('AI Collaboration Workspace - OFFICIAL CLAUDE TOOLS - ISOLATED')
report={'status':'RUNNING','scope':'Official Claude actual source Qt in isolated fixture; original permissions unchanged; no automatic approval','started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'repo':str(REPO),'checks':{},'approval_requests':[]};start=time.monotonic();stage='connect';busy=False;done=False;seen=set()
def save(): (OUT/'result.json').write_text(json.dumps(sanitize(report),ensure_ascii=False,indent=2),encoding='utf-8')
def finish(status,reason):
 global done
 if done:return
 done=True;timer.stop();window.poll_events();report.update(status=status,reason=reason,session=adapter.session_id,diagnostics=core.diagnostics('claude'));(OUT/'public-events.json').write_text(json.dumps(sanitize([e for e in core.events(agent='claude',limit=10000) if e['type'] not in ('raw','message_delta')]),ensure_ascii=False,indent=2),encoding='utf-8');window.grab().save(str(OUT/'window.png'));save();print(status+' '+reason,flush=True)
 try:
  if adapter.state=='Busy':adapter.stop()
  adapter.disconnect()
 except Exception:pass
 for pane in window.panels.values():pane.set_state('Disconnected')
 window.close();QTimer.singleShot(100,app.quit)
def tick():
 global stage,busy
 try:
  window.poll_events();panel=window.panels['claude']
  for rid,event in panel.pending_approval_events.items():
   if rid not in seen:
    seen.add(rid);report['approval_requests'].append({'id':rid,'request':event});save();window.grab().save(str(OUT/'pending-human.png'));print('PENDING HUMAN APPROVAL '+rid+'; no grant issued by test',flush=True)
  if adapter.state in ('Error','Offline'):finish('BLOCKED',adapter.last_error);return
  if time.monotonic()-start>(900 if report['approval_requests'] else 150):finish('BLOCKED','Official timeout or human approval still pending; canceled without granting');return
  if stage=='connect':QTest.mouseClick(panel.connect_button,Qt.LeftButton);stage='new'
  elif stage=='new' and adapter.state=='Connected' and not window.workers:window.refresh_agent('claude');QTest.mouseClick(panel.new_button,Qt.LeftButton);stage='send'
  elif stage=='send' and adapter.session_id and not window.workers:
   window.reload_context();python=sys.executable.replace('\\','/');prompt='Isolated acceptance repo only: '+str(REPO)+'. Read fixture.py and use Edit to change only return a - b into return a + b. Then use Bash to run exactly "'+python+'" -m unittest -v test_fixture.py in this cwd. No other files, installs, network, services or repo operations. Report the actual result naturally.';report['prompt']=prompt;panel.input.setPlainText(prompt);QTest.mouseClick(panel.send_button,Qt.LeftButton);stage='result';save()
  elif stage=='result':
   if adapter.state=='Busy':busy=True
   responses=[m for m in core.messages(agent='claude') if m['role']=='assistant' and m['status']=='complete']
   if busy and adapter.state=='Connected' and not window.workers and responses:
    events=core.events(agent='claude',limit=10000);cards=panel.findChildren(EventCard);body='\n'.join(c.body.toPlainText() for c in cards);file=(REPO/'fixture.py').read_text(encoding='utf-8');run=subprocess.run([sys.executable,'-m','unittest','-v','test_fixture.py'],cwd=REPO,capture_output=True,text=True,encoding='utf-8',timeout=15)
    report['independent_test']={'exit_code':run.returncode,'stdout':run.stdout,'stderr':run.stderr};report['checks']={'actual_file_edit':file=='def add(a, b):\n    return a + b\n','native_file_event':any(e['type'] in ('file','file_edit') and e.get('payload',{}).get('operation') in ('Edit','Write') for e in events),'native_command_event':any(e['type']=='command' for e in events),'command_output_in_actual_UI':'test_add' in body and 'OK' in body,'file_edit_in_actual_UI':'Edit' in body,'independent_test_pass':run.returncode==0,'cwd':adapter.cwd==str(REPO)};finish('PASS' if all(report['checks'].values()) else 'FAIL','Official file/command effects and visible Qt cards checked')
 except Exception as exc:report['traceback']=traceback.format_exc();finish('BLOCKED',str(exc))
timer=QTimer();timer.timeout.connect(tick);timer.start(150);save();app.exec();core.close()
