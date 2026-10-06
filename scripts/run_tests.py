"""Reproducible normal-permission test runner; UI is a separately gated suite."""
import sys,os,json,unittest,datetime,platform
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
patterns=['test_dot.py','test_core.py','test_security_review.py','test_inspection.py','test_claude.py','test_codex.py','test_codex_adapter.py','test_recovery_process.py']
suite=unittest.TestSuite()
for pattern in patterns:
 if (ROOT/'tests'/pattern).exists():suite.addTests(unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern=pattern))
evidence=ROOT/'evidence';evidence.mkdir(exist_ok=True)
with (evidence/'unit-tests.txt').open('w',encoding='utf-8') as out:
 result=unittest.TextTestRunner(stream=out,verbosity=2).run(suite)
summary={'timestamp':datetime.datetime.now(datetime.timezone.utc).isoformat(),'machine':platform.node(),'python':sys.version,'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':[(str(t),why) for t,why in result.skipped],'successful':result.wasSuccessful(),'ui_suite':'Qt is excluded from this normal-permission runner; consult evidence/ui-acceptance/result.json for the separately measured visible run.','patterns':patterns}
(evidence/'unit-test-results.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
if not result.wasSuccessful():
 print((evidence/'unit-tests.txt').read_text(encoding='utf-8')[-12000:])
sys.exit(0 if result.wasSuccessful() else 1)
