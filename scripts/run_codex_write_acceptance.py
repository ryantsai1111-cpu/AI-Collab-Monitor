from pathlib import Path
import sys,json,subprocess,tempfile,time,threading,datetime
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from acw.adapters.codex import CodexAdapter
from acw.security import sanitize
repo=Path(tempfile.mkdtemp(prefix='codex-write-',dir=ROOT/'tests'))
git=r'C:\Program Files\Git\cmd\git.exe'
def gitcmd(*args):return subprocess.run([git,'-C',str(repo),*args],capture_output=True,text=True,check=True)
gitcmd('init','--quiet')
(repo/'fixture.py').write_text('def add(a, b):\n    return a - b\n',encoding='utf-8')
(repo/'test_fixture.py').write_text('import unittest\nfrom fixture import add\nclass TestAdd(unittest.TestCase):\n    def test_add(self): self.assertEqual(add(2, 3), 5)\n',encoding='utf-8')
gitcmd('add','fixture.py','test_fixture.py');gitcmd('-c','user.name=ACW Fixture','-c','user.email=acw-fixture@example.invalid','commit','--quiet','-m','isolated baseline')
uid=str(time.time_ns()); events=[];approval=threading.Event()
def emit(kind,**data):
 events.append(sanitize({'type':kind,**data}))
 if kind=='approval':approval.set()
a=CodexAdapter(emit,r'C:\Users\ryant\AppData\Local\OpenAI\Codex\bin\8aaf1547b825b104\codex.exe',timeout=30)
report={'scope':'isolated real official backend write/diff/test acceptance','cwd':str(repo),'model':'gpt-6.1-sol','effort':'medium','sandbox_changed':False,'approvals_granted':0,'status':'RUNNING'}
try:
 a.set_project(str(repo));a.connect()
 if report['model'] not in a.list_models() or report['effort'] not in a.list_efforts(report['model']):raise RuntimeError('Requested Sol/medium not advertised; no substitute used')
 report['session']=a.create_session();report['permissions']=a.diagnostics()['permissions']
 prompt=('This is an explicitly authorized harmless acceptance test ONLY in '+str(repo)+'. Use gpt-6.1-sol with medium effort. Modify only fixture.py: change return a - b to return a + b using your normal native file edit tool. Then run the existing test_fixture.py with '+sys.executable+' -B -m unittest -v test_fixture.py and inspect git diff. Do not inspect unrelated paths, credentials or use network/install software. Preserve the inherited sandbox; do not bypass it or request broad permissions. If permission approval is needed, emit the normal official request and wait. Briefly report the actual result.')
 report['prompt']=prompt;a.send_message(prompt,model=report['model'],effort=report['effort'])
 deadline=time.monotonic()+90
 while not a._turn_done.wait(.2):
  if approval.is_set():
   report.update(status='BLOCKED',blocker='Official backend requested human approval; no approval granted',approval_requests=[e for e in events if e['type']=='approval']);a.stop();break
  if time.monotonic()>deadline:
   report.update(status='BLOCKED',blocker='Official backend turn timed out at90s');a.stop();break
 a._turn_done.wait(10)
 diff=gitcmd('diff','--','fixture.py').stdout
 result=subprocess.run([sys.executable,'-B','-m','unittest','-v','test_fixture.py'],cwd=repo,capture_output=True,text=True)
 report['checks']={'file_written': 'return a + b' in (repo/'fixture.py').read_text(encoding='utf-8'),'git_diff':bool(diff),'native_file_event':any(e['type']=='file' for e in events),'native_diff_event':any(e['type']=='diff' for e in events),'tests_passed':result.returncode==0}
 report.update(diff=diff,verification_exit=result.returncode,verification_output=result.stdout+result.stderr)
 if report['status']=='RUNNING':report['status']='PASS' if all(report['checks'].values()) else 'FAIL'
except Exception as exc:report.update(status='BLOCKED',blocker=str(exc))
finally:
 a.disconnect();report['last_error']=a.last_error
 out=ROOT/'evidence';(out/('codex-write-run-'+uid+'.json')).write_text(json.dumps(sanitize(report),ensure_ascii=False,indent=2),encoding='utf-8')
 (out/('codex-write-run-'+uid+'-events.jsonl')).write_text(''.join(json.dumps(e,ensure_ascii=False)+'\n' for e in events),encoding='utf-8')
 print(json.dumps(sanitize(report),ensure_ascii=False,indent=2));print('evidence=codex-write-run-'+uid+'.json')
