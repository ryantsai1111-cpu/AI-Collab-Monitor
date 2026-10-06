"""Focused visible offline UI regression; no real adapter connect/read/send."""
import datetime,json,sys,unittest
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/'vendor'),str(root),str(root/'tests')]
out=root/'evidence/session-labels-ui';out.mkdir(parents=True,exist_ok=True)
with (out/'tests.txt').open('w',encoding='utf-8') as stream:
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.discover(str(root/'tests'),pattern='test_session_labels.py'))
report=dict(timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),status='PASS' if result.wasSuccessful() else 'FAIL',
            tests=result.testsRun,passed=result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
            failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),visible_ui=True,
            scope='Isolated local synthetic sessions and existing-metadata shapes; no live backend, credentials or remote history')
(out/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
if not result.wasSuccessful():print((out/'tests.txt').read_text(encoding='utf-8')[-10000:])
sys.exit(0 if result.wasSuccessful() else 1)
