"""No live Dot calls. --ui uses visible Qt and fixture transport only."""
import argparse,datetime,json,sys,unittest
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/'vendor'),str(root),str(root/'tests')]
p=argparse.ArgumentParser();p.add_argument('--ui',action='store_true');args=p.parse_args()
pattern='test_dot_ui.py' if args.ui else 'test_dot.py'
out=root/'evidence'/('dot-offline-ui' if args.ui else 'dot-offline');out.mkdir(parents=True,exist_ok=True)
with (out/'tests.txt').open('w',encoding='utf-8') as stream:
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.discover(str(root/'tests'),pattern=pattern))
report={'timestamp':datetime.datetime.now(datetime.timezone.utc).isoformat(),'status':'PASS' if result.wasSuccessful() else 'FAIL','tests':result.testsRun,'passed':result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),'failures':len(result.failures),'errors':len(result.errors),'skipped':[(str(test),why) for test,why in result.skipped],'scope':'OFFLINE FIXTURES ONLY; no real CLI/authentication/network; not live acceptance','visible_ui':args.ui,'actual_identifier_fixture_status':'BLOCKED pending actual user value' if any('actual_observed_g8' in str(test) for test,why in result.skipped) else 'See individual test provenance; no live claim'}
(out/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
if not result.wasSuccessful():print((out/'tests.txt').read_text(encoding='utf-8')[-10000:])
sys.exit(0 if result.wasSuccessful() else 1)
