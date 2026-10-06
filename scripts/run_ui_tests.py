"""One-shot UI acceptance runner. Requires explicit resolution of UI permission blocker.

All tests use FakeCore, isolated temp directories, no network and no agent process.
--visible runs real Qt windows with QTest input. It does not certify live backends.
"""
import sys,os,json,argparse,datetime,unittest,threading
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'vendor'),str(ROOT),str(ROOT/'tests')]
parser=argparse.ArgumentParser();parser.add_argument('--visible',action='store_true');parser.add_argument('--widgets-only',action='store_true');args=parser.parse_args()
os.environ['QT_QPA_PLATFORM']='windows' if args.visible else 'offscreen'
OUT=ROOT/'evidence'/('ui-widget-regression' if args.widgets_only else 'ui-acceptance');OUT.mkdir(parents=True,exist_ok=True)
report={'scope':'Synthetic UI interaction only; no backend/production repo/network','visible':args.visible,'timestamp':datetime.datetime.now(datetime.timezone.utc).isoformat(),'status':'RUNNING'}
def finish_report(): (OUT/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
def deadline():
 report.update(status='TIMEOUT',error='Test-only process exceeded 180 seconds; no backend was started');finish_report();os._exit(124)
watchdog=threading.Timer(180,deadline);watchdog.daemon=True;watchdog.start()
try:
 import test_ui, test_workspace_ui
 from PySide6.QtWidgets import QApplication
 for value in list(vars(test_ui).values())+list(vars(test_workspace_ui).values()):
  if isinstance(value,type) and issubclass(value,unittest.TestCase) and hasattr(value,'tearDown'):
   original=value.tearDown
   def capture_then_close(self,original=original):
    try:
     if getattr(self,'window',None):
      QApplication.processEvents()
      self.window.grab().save(str(OUT/(self._testMethodName+'.png')))
    finally:original(self)
   value.tearDown=capture_then_close
 with (OUT/'tests.txt').open('w',encoding='utf-8') as stream:
  suites=[unittest.defaultTestLoader.loadTestsFromModule(test_ui)]
  if not args.widgets_only:suites.append(unittest.defaultTestLoader.loadTestsFromModule(test_workspace_ui))
  result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.TestSuite(suites))
 report.update(status='PASS' if result.wasSuccessful() else 'FAIL',tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped))
 code=0 if result.wasSuccessful() else 1
except Exception as exc:
 report.update(status='BLOCKED',error=str(exc));code=2
finally:
 watchdog.cancel();finish_report()
print(json.dumps(report,indent=2));sys.exit(code)
