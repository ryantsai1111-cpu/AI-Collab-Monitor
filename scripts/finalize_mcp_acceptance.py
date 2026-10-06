"""Promote only the genuinely completed authorized native MCP criterion."""
from pathlib import Path
from collections import Counter
import datetime,json,re
ROOT=Path(__file__).resolve().parents[1];E=ROOT/'evidence'
read=lambda p:json.loads((E/p).read_text(encoding='utf-8-sig'))
write=lambda p,v:(E/p).write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
run=read('live-mcp-echo-ui/result.json');lifecycle=read('live-mcp-echo-ui/lifecycle-review.json');raw_ui=read('live-mcp-echo-ui/saved-raw-ui.json')
assert run['status']=='PASS' and all(run['checks'].values())
assert lifecycle['official_backend_exited'] and lifecycle['fixture_exited']
assert raw_ui['status']=='PASS' and all(raw_ui['checks'].values())
events=read('live-mcp-echo-ui/public-events.json');name='mcp__acw_acceptance__echo'
starts=[e for e in events if e['type']=='tool_start'];results=[e for e in events if e['type']=='tool_result']
assert len(starts)==len(results)==1 and starts[0]['payload']['name']==results[0]['payload']['name']==name
assert starts[0]['payload']['arguments']=={'text':'ACW_MCP_ACCEPTANCE_OK'}
assert results[0]['payload']['result']==[{'type':'text','text':'ACW_MCP_ACCEPTANCE_OK'}]
assert results[0]['status']=='completed'
request=run['approval_requests'][0];grants=[e for e in events if e['type']=='approval_response' and e['payload'].get('approved')]
assert len(run['approval_requests'])==len(grants)==1 and grants[0]['payload']['request_id']==request['id']
assert request['request']['details']['requires_user_interaction'] and request['request']['details']['suppress_always_allow_rule']
if run.get('cleanup_error'):
 run['original_cleanup_check_error']=run.pop('cleanup_error')
run.update(official_process_exited=True,fixture_process_exited=True,lifecycle_review='Exact-scope read-only process absence verified; original post-disconnect handle-check error retained in result-before-lifecycle-review.json',approval_utc=grants[0]['timestamp'])
write('live-mcp-echo-ui/result.json',run)
coverage=read('requirement-coverage.json');criteria={r['id']:r for r in coverage['criteria']}
criteria['R006.06'].update(status='PASS',reason='Real official Claude STDIO MCP echo after human native approval through actual Workspace UI: exact tool/args/result/status, one call, no other connector, normal backend/fixture exit. Authorized fixed-string local tool; does not certify private cloud connector access.',evidence=[
 {'path':'evidence/live-mcp-echo-ui/result.json','scope':'11 real official MCP/approval/Workspace UI checks; no synthetic agent backend'},
 {'path':'evidence/live-mcp-echo-ui/public-events.json','scope':'Original exact native tool input/result and matching human approval event'},
 {'path':'evidence/live-mcp-echo-ui/saved-raw-ui.json','scope':'Actual original-record Raw UI selection, overlapping original display checks; screenshots'},
 {'path':'evidence/live-mcp-echo-ui/lifecycle-review.json','scope':'Read-only exact session and fixture absence; no kill/restart'},
 {'path':'evidence/MCP-PUBLIC-DOC-BLOCKER.md','scope':'Earlier public Claude Docs scope attempt remained blocked; preserved history'}])
now=datetime.datetime.now(datetime.timezone.utc).isoformat();coverage['observed_utc']=now
coverage['status_counts']=dict(Counter(r['status'] for r in coverage['criteria']))
coverage['authorized_mcp_acceptance']={'observed_utc':now,'resolved':['R006.06'],'mapping':'scripts/finalize_mcp_acceptance.py','real_checks':11,'native_human_approval_utc':grants[0]['timestamp'],'private_connector_access_verified':False}
for r in coverage['criteria']:
 r['reason']=r.get('reason','').replace('configured MCP execution remains unverified','authorized local MCP echo passed; remaining full scope requires Dot and EXE acceptance')
for section in coverage['sections']:
 counts=Counter(r['status'] for r in coverage['criteria'] if r['section']==section['section']);section['counts']=dict(counts);section['status']=next(s for s in ('FAIL','BLOCKED','PENDING','UNSUPPORTED','PASS') if counts[s])
write('requirement-coverage.json',coverage)
baseline=read('pending-acceptance-classification.json')
for r in baseline['criteria']:
 if r['id']=='R006.06':r.update(status='PASS',reason=criteria[r['id']]['reason'],evidence=criteria[r['id']]['evidence'][0])
baseline['outcome_counts']=dict(Counter(r['status'] for r in baseline['criteria']));baseline['reconciled_utc']=now;write('pending-acceptance-classification.json',baseline)
remaining=[{k:r.get(k) for k in ('id','criterion','status','reason','evidence')} for r in coverage['criteria'] if r['status']!='PASS']
write('REMAINING-ACCEPTANCE.json',{'observed_utc':now,'final_gate':'BLOCKED','counts':coverage['status_counts'],'criteria':remaining})
(E/'REMAINING-ACCEPTANCE.md').write_text('# Remaining acceptance criteria\n\nFinal remains BLOCKED. Local native MCP success does not certify Dot, compiled runtime or private connector access.\n\n| ID | Status | Requirement | Specific blocker or limitation |\n|---|---|---|---|\n'+'\n'.join(f"| {r['id']} | {r['status']} | {r['criterion']} | {r['reason'].replace('|','/')} |" for r in remaining)+'\n',encoding='utf-8')
doc=ROOT/'docs/REQUIREMENTS.md';lines=doc.read_text(encoding='utf-8').splitlines();sections={s['section']:s for s in coverage['sections']}
for n,line in enumerate(lines):
 if line.startswith('| R006.06 /'):
  r=criteria['R006.06'];lines[n]=f"| R006.06 / T-R006.06 | {r['criterion']} | PASS | {r['reason']} Evidence: evidence/live-mcp-echo-ui/result.json; saved-raw-ui.json; lifecycle-review.json |"
 match=re.match(r'\| R(\d{3}) \|',line)
 if match:
  s=sections[int(match[1])];cells=line.split('|');cells[-3]=' '+s['status']+' ';cells[-2]=' '+'; '.join(f'{v} {k}' for k,v in s['counts'].items())+'; see individual rows ';lines[n]='|'.join(cells)
text='\n'.join(lines)+'\n';text=text.replace('592 PASS, 0 FAIL, 57 BLOCKED','593 PASS, 0 FAIL, 56 BLOCKED').replace('Core127PASS/2opt-in skips (129discovered)','Core129PASS/2opt-in skips (131discovered)').replace('configured MCP execution still unverified.','human-approved actual local MCP/Workspace UI11PASS; private connectors not tested.')
text=text.replace('| S4 | Claude Adapter | BLOCKED |','| S4 | Claude Adapter | PASS |')
doc.write_text(text,encoding='utf-8')
for name in ('README.md','docs/CONTINUATION-NOTES.md'):
 p=ROOT/name;s=p.read_text(encoding='utf-8').replace('592PASS/0FAIL/57BLOCKED','593PASS/0FAIL/56BLOCKED').replace('592 scoped criteria PASS /0FAIL /57BLOCKED','593 scoped criteria PASS /0FAIL /56BLOCKED').replace('127PASS/0FAIL/2opt-in skips (129discovered)','129PASS/0FAIL/2opt-in skips (131discovered)').replace('Normal suite127PASS/2opt-in skips (129discovered)','Normal suite129PASS/2opt-in skips (131discovered)').replace('unverified configured MCP tool execution and','').replace('No new MCP service or external tool was invoked.','One subsequently explicitly authorized local STDIO fixed-string MCP tool passed11 native/human-approval/Workspace UI checks and exited; no private connector was called.')
 s+='\nAuthorized MCP follow-up: actual official Claude `mcp__acw_acceptance__echo`, fixed input/result, one human native approval, exact tool/result/status in actual Workspace UI,11 checks PASS; saved Raw UI checks overlap. No persistent config/service/port, private connector, automatic allow rule or permission-mode change. See evidence/live-mcp-echo-ui/result.json. Earlier Claude Docs public-document scope attempt remains historical BLOCKED.\n'
 p.write_text(s,encoding='utf-8')
print(json.dumps({'newly_resolved':['R006.06'],'counts':coverage['status_counts'],'checks':len(run['checks']),'human_approval_utc':grants[0]['timestamp']},indent=2))
