"""Official scoped readonly native history + measured source-Qt idle CPU."""
from pathlib import Path
import sys,json,time,tempfile,datetime
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'vendor'),str(ROOT)]
from PySide6.QtWidgets import QApplication,QPlainTextEdit,QLabel
from PySide6.QtCore import Qt,QTimer
from PySide6.QtTest import QTest
from acw.core import WorkspaceCore
from acw.ui import MainWindow,NativeSessionDialog,NativeHistoryDialog
from acw.adapters.claude import ClaudeAdapter
from acw.security import sanitize
origin=json.loads((ROOT/'evidence/live-claude-tools-ui/result.json').read_text(encoding='utf-8'));REPO=Path(origin['repo']);SID=origin['session'];OUT=ROOT/'evidence/native-history-idle-ui';OUT.mkdir(exist_ok=True);DATA=Path(tempfile.mkdtemp(prefix='native-history-ui-',dir=ROOT/'tests'))
app=QApplication([]);core=WorkspaceCore(DATA);adapter=core.set_adapter('claude',ClaudeAdapter(core.make_emitter('claude'),executable=r'C:\Users\ryant\AppData\Local\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude-code\2.1.286\635c1867224a\claude.exe',timeout=40));core.set_setting('legacy.root',str(DATA/'no-legacy'));project=core.create_project('ISOLATED NATIVE HISTORY UI',REPO);core.select_project(project['id']);core.create_task('Read-only native history preview');window=MainWindow(core);window.show();stage='connect';start=time.monotonic();idle_start=idle_cpu=None;done=False
report={'status':'RUNNING','started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'scope':'Official public SDK read-only history for exact isolated test session; no resume/query/import; actual source Qt idle measurement, not EXE/three-stream acceptance','repo':str(REPO),'session':SID,'checks':{}}
def finish(status,reason):
 global done
 if done:return
 done=True;timer.stop();report.update(status=status,reason=reason);(OUT/'result.json').write_text(json.dumps(sanitize(report),ensure_ascii=False,indent=2),encoding='utf-8');window.grab().save(str(OUT/'idle-window.png'));adapter.disconnect()
 for pane in window.panels.values():pane.set_state('Disconnected')
 window.close();QTimer.singleShot(100,app.quit);print(status+' '+reason,flush=True)
def tick():
 global stage,idle_start,idle_cpu
 try:
  if time.monotonic()-start>150:finish('BLOCKED','Scoped read/UI timeout');return
  window.poll_events();active=app.activeModalWidget()
  if stage=='connect':QTest.mouseClick(window.panels['claude'].connect_button,Qt.LeftButton);stage='discover'
  elif stage=='discover' and adapter.state=='Connected' and not window.workers:
   window.refresh_agent('claude');report['before_preview']={'messages':len(core.messages()),'session_ids':[s['id'] for s in core.sessions('claude')],'task_session':core.current_task['claude_session'],'adapter_session':adapter.session_id};stage='select';QTimer.singleShot(0,lambda:QTest.mouseClick(window.panels['claude'].discover_button,Qt.LeftButton))
  elif stage=='select' and isinstance(active,NativeSessionDialog) and active.table.topLevelItemCount():
   match=next((active.table.topLevelItem(i) for i in range(active.table.topLevelItemCount()) if active.table.topLevelItem(i).text(1)==SID),None)
   assert match is not None,'Exact isolated native session missing';active.table.setCurrentItem(match);assert active.history_button.isEnabled();active.grab().save(str(OUT/'native-discovery.png'));stage='history';QTest.mouseClick(active.history_button,Qt.LeftButton)
  elif stage=='history' and isinstance(active,NativeHistoryDialog):
   bodies=[x.toPlainText() for x in active.findChildren(QPlainTextEdit)];after={'messages':len(core.messages()),'session_ids':[s['id'] for s in core.sessions('claude')],'task_session':core.current_task['claude_session'],'adapter_session':adapter.session_id};report['after_preview']=after;report['checks'].update(official_native_session_list=True,original_session_selected=any(SID in label.text() for label in active.findChildren(QLabel)),history_original_prompt=any('fixture.py' in x for x in bodies),history_readonly=all(x.isReadOnly() for x in active.findChildren(QPlainTextEdit)),no_transcript_import_or_resume=after==report['before_preview']);active.grab().save(str(OUT/'native-history.png'));active.accept();stage='close_discovery'
  elif stage=='close_discovery' and isinstance(active,NativeSessionDialog):active.reject();stage='disconnect'
  elif stage=='disconnect' and not window.workers:adapter.disconnect();window.refresh_agent('claude');stage='settle';idle_start=time.monotonic()
  elif stage=='settle' and time.monotonic()-idle_start>=2:idle_start=time.monotonic();idle_cpu=time.process_time();stage='idle'
  elif stage=='idle' and time.monotonic()-idle_start>=20:
   wall=time.monotonic()-idle_start;cpu=time.process_time()-idle_cpu;report['idle']={'wall_seconds':wall,'process_cpu_seconds':cpu,'one_core_cpu_percent':cpu/wall*100,'agents_connected':False,'source_qt':True,'metric':'Process CPU/wall, one logical core=100%; one 20-second disconnected source-Qt sample, no streaming claim'};finish('PASS' if all(report['checks'].values()) else 'FAIL','Readonly native history and actual idle CPU measured')
 except Exception as exc:finish('BLOCKED',str(exc))
timer=QTimer();timer.timeout.connect(tick);timer.start(150);app.exec();core.close()
