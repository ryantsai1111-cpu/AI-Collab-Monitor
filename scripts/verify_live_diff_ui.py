"""Read-only visible rendering acceptance of the actual isolated Codex result."""
from pathlib import Path
import sys,json,datetime
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'vendor'),str(ROOT)]
from PySide6.QtWidgets import QApplication,QDialog,QPushButton,QTabWidget,QPlainTextEdit,QTreeWidget
from PySide6.QtCore import QTimer,Qt
from PySide6.QtTest import QTest
from acw.core import WorkspaceCore
from acw.ui import MainWindow
out=ROOT/'evidence/live-codex-ui';original=json.loads((out/'result.json').read_text(encoding='utf-8'));core=WorkspaceCore(original['data_dir']);app=QApplication([]);window=MainWindow(core);window.show();checks={};error='';finished=False

def inspect():
 global finished,error
 dialogs=[x for x in app.topLevelWidgets() if isinstance(x,QDialog) and x.isVisible() and x.windowTitle().startswith('Project changes and tests')]
 if not dialogs:return
 dialog=dialogs[0];tabs=dialog.findChild(QTabWidget);unified=tabs.widget(0)
 if 'Reading repository status' in unified.toPlainText():return
 finished=True;timer.stop()
 try:
  checks['actual_unified_diff']='-    return a - b' in unified.toPlainText() and '+    return a + b' in unified.toPlainText() and unified.isReadOnly()
  dialog.grab().save(str(out/'actual-unified-diff.png'))
  tabs.setCurrentIndex(1);QTest.qWait(20);editors=[tabs.widget(1).widget(0),tabs.widget(1).widget(1)];checks['actual_side_by_side']=len(editors)==2 and all(x.isReadOnly() for x in editors) and 'return a - b' in editors[0].toPlainText() and 'return a + b' in editors[1].toPlainText();dialog.grab().save(str(out/'actual-side-by-side.png'))
  tabs.setCurrentIndex(2);QTest.qWait(20);files=tabs.widget(2);checks['actual_changed_file']=any(files.topLevelItem(i).text(1)=='fixture.py' for i in range(files.topLevelItemCount()))
  tabs.setCurrentIndex(3);QTest.qWait(20);tests=tabs.widget(3);checks['actual_test_table']=any(tests.topLevelItem(i).text(1)=='unittest' and tests.topLevelItem(i).text(2)=='1' and tests.topLevelItem(i).text(3)=='0' and tests.topLevelItem(i).text(6)=='0' for i in range(tests.topLevelItemCount()));dialog.grab().save(str(out/'actual-test-view.png'))
 except Exception as exc:error=str(exc)
 dialog.accept();QTimer.singleShot(100,finish)
def finish():
 timer.stop();report={'status':'PASS' if len(checks)==4 and all(checks.values()) and not error else 'FAIL','checks':checks,'error':error,'scope':'Visible QTest action opens real task diff/test viewer, read-only isolated result; no adapter connected','observed_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()};(out/'diff-test-view.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report),flush=True);window.close();app.quit()
def start():
 button=next(x for x in window.findChildren(QPushButton) if x.text()=='Diff / Tests');QTest.mouseClick(button,Qt.LeftButton)
timer=QTimer();timer.timeout.connect(inspect);timer.start(100);QTimer.singleShot(100,start);QTimer.singleShot(30000,finish);app.exec();core.close()
