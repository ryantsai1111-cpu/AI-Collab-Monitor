"""Source-only offline tests. No csc, installer, application EXE or live backend."""
import datetime,json,sys,unittest
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path[:0]=[str(root/'tests'),str(root)]
stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
out=root/'evidence/exe-source-remediation2'/('verification-'+stamp);out.mkdir(parents=True,exist_ok=False)
with (out/'offline-tests.txt').open('w',encoding='utf-8') as stream:
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.discover(str(root/'tests'),pattern='test_exe_source_hardening.py'))
report=dict(timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),status='PASS' if result.wasSuccessful() else 'FAIL',
            tests=result.testsRun,passed=result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
            failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),
            scope='Pure deployment policy, mocked observations, trusted PS parser/pure helpers, exact C# regex constants against Windows argv oracle; C# NOT compiled/executed',
            compiler_invoked=False,installer_invoked=False,workspace_exe_executed=False,
            native_csharp_runtime_validation='BLOCKED: compilation/execution not authorized',
            package_identity_scope='Return-code mocks only; real API/virtualization coverage not executed',
            dependency_scope='Temporary regular-file fixtures and mocked reparse metadata; no real junction traversal/copy/flattening',
            evidence_directory=str(out))
(out/'offline-result.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
if not result.wasSuccessful():print((out/'offline-tests.txt').read_text(encoding='utf-8')[-9000:])
sys.exit(0 if result.wasSuccessful() else 1)
