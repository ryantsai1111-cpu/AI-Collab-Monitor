"""Check installed acw module origin and synced source hashes only; no GUI/Core/backend."""
from pathlib import Path
import argparse,datetime,hashlib,importlib,json,sys,traceback

ROOT=Path(__file__).resolve().parents[1]
APP=Path(r'C:\Users\ryant\AppData\Local\AI-Collaboration-Workspace\app')

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=ROOT/'evidence/installed-source-verification.json')
    args=parser.parse_args()
    report={'observed_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'status':'FAIL','scope':'Installed acw module origin and explicit synced source hashes only',
            'gui_started':False,'backend_started':False,'exe_executed':False,
            'runtime_verified':False,'user_data_accessed':False,'hash_checks':[],
            'python_executable':sys.executable,'acw_preloaded':'acw' in sys.modules}
    try:
        # Same precedence as run.py: installed APP, then APP/vendor.
        sys.path[:0]=[str(APP),str(APP/'vendor')]
        report['search_prefix']=sys.path[:2]
        expected=APP/'acw/__init__.py'
        report['expected_module_path']=str(expected)
        report['expected_resolved_path']=str(expected.resolve(strict=True))
        acw=importlib.import_module('acw')
        actual=Path(acw.__file__)
        report['actual_module_origin']=str(actual)
        report['actual_resolved_path']=str(actual.resolve(strict=True))
        report['legacy_path_assertion_would_pass']=actual.resolve(strict=True)==expected
        report['resolved_path_match']=actual.resolve(strict=True)==expected.resolve(strict=True)
        if not report['resolved_path_match']:
            raise AssertionError('Installed acw resolved module origin does not match expected installed file')
        sync=json.loads((ROOT/'evidence/installed-source-sync.json').read_text(encoding='utf-8-sig'))
        for row in sync['files']:
            relative=Path(row['path'])
            if relative.is_absolute() or '..' in relative.parts:
                raise ValueError('Invalid synced relative source path')
            source=APP/relative
            if not source.resolve(strict=True).is_relative_to(APP.resolve(strict=True)):
                raise ValueError('Synced source resolves outside installed APP')
            actual_hash=hashlib.sha256(source.read_bytes()).hexdigest()
            expected_hash=row['installed_sha256'].lower()
            report['hash_checks'].append({'path':row['path'],'actual_sha256':actual_hash,
                                         'expected_sha256':expected_hash,'matched':actual_hash==expected_hash})
        mismatches=[r['path'] for r in report['hash_checks'] if not r['matched']]
        if mismatches:
            raise AssertionError('Installed source hash mismatch: '+', '.join(mismatches))
        report['status']='PASS'
        report['reason']='Exact resolved installed module origin and all explicit synced source hashes matched; runtime/UI not tested'
    except Exception as exc:
        report['error_type']=type(exc).__name__
        report['reason']=str(exc)
        report['traceback']=traceback.format_exc()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report['status']=='PASS' else 1

if __name__=='__main__':
    sys.exit(main())
