"""Save measured continuation results without promoting unreviewed criteria."""
from pathlib import Path
import datetime,json
root=Path(__file__).resolve().parents[1]
e=root/'evidence'
read=lambda name:json.loads((e/name).read_text(encoding='utf-8'))
coverage=read('requirement-coverage.json')
live=read('live-collaboration-ui/result.json')
ui=read('ui-acceptance/result.json')
now=datetime.datetime.now(datetime.timezone.utc).isoformat()
coverage['observed_utc']=now
coverage['final_gate']['reasons']=[
 'No verified approved official Dot bridge; three-agent operation and Claude-to-Dot receipt blocked',
 'Installed compiled EXE launch was rejected by Windows security and installed EXE is now absent; static diagnosis only',
 'New 41-case UI and official two-agent evidence requires complete criterion reconciliation; uncovered workflows remain pending',
 'Strict separate stdout/stderr unsupported by inspected Codex combined-output contract',
 'Multi-monitor and configured official MCP end-to-end acceptance not established']
coverage['final_gate']['resolved_blockers']=[
 'Claude official post-login real backend acceptance passed',
 'Visible Qt suite now 41 PASS with preserved historical failed runs',
 'Actual Codex human-approved file write, patch, diff, commands and test passed',
 'Official Claude/Codex visible handoff, reconnect/resume, streaming and Stop passed']
coverage['test_summary'].update(ui_authored=41,ui_executed=41,ui_pass=41,ui_fail=0,ui_errors=0,ui_skipped=0,ui_status='PASS',ui_scope='41 visible isolated Qt/Core/store/Git cases with synthetic transports; separate official two-agent UI result',official_two_agent_ui_checks=sum(v is True for v in live['checks'].values()))
coverage['continuation_checkpoint']={'observed_utc':now,'criterion_promotion':'Not performed: evidence mapping remains pending','visible_ui':'evidence/ui-acceptance/result.json','official_two_agent_ui':'evidence/live-collaboration-ui/result.json'}
(e/'requirement-coverage.json').write_text(json.dumps(coverage,ensure_ascii=False,indent=2),encoding='utf-8')
checkpoint={'observed_utc':now,'final_status':'BLOCKED / NOT ACCEPTED','ui':ui,'official_two_agent':{'status':live['status'],'checks':live['checks'],'evidence':'evidence/live-collaboration-ui/result.json'},'existing_criterion_counts':coverage['status_counts'],'pending_baseline_classification':{'INDEPENDENT':184,'DOT_DEPENDENT':8,'EXE_DEPENDENT':2,'OTHER_PREREQUISITE':3},'installed_app_updated_this_continuation':False,'exe_restored_rebuilt_executed':False,'remaining':['Complete criterion-to-new-evidence reconciliation','Dot approved official bridge unavailable','Windows security rejected installed EXE; responsible provider unresolved','Multi-monitor and configured MCP acceptance prerequisites','Library prepare_uploads unavailable']}
(e/'CONTINUATION-CHECKPOINT.json').write_text(json.dumps(checkpoint,ensure_ascii=False,indent=2),encoding='utf-8')
(e/'CONTINUATION-CHECKPOINT.md').write_text('''# Continuation checkpoint

Final: **BLOCKED / NOT ACCEPTED**.

- Visible Qt: **41 PASS / 0 FAIL / 0 ERROR / 0 SKIP**. Explicit synthetic transport; real Core/SQLite/Git isolated workflows. Actual export defect fixed and rerun passed.
- Separate official Claude/Codex Qt interaction: **16 checks PASS**. Exact A preserved in assisted handoff; reverse handoff, native Read tool, cwd/session mapping, reconnect/resume, rendered streaming and actual official Stop. Codex gpt-6.1-sol / medium; zero approval grants, unchanged sandbox. Screenshots visually reviewed.
- 197 baseline pending criteria classified: 184 independent / 8 Dot / 2 EXE / 3 other prerequisite. Mapping new evidence to individual criteria remains pending; classification is not acceptance.
- EXE static compiler provenance captured; existing compiler signature Valid/Microsoft Windows. No compile, restore, copy, launcher retry, antivirus exclusion, ACL or security changes. Missing installed EXE remains unresolved. New source changes are not yet installed.
- Dot remains truthfully blocked. Separate stdout/stderr remains unsupported by inspected Codex contract. No final three-agent success claim.

Evidence: `ui-acceptance/result.json`, `live-collaboration-ui/result.json`, public events/messages and screenshots, `launcher-static-build-chain.json`, `PENDING-ACCEPTANCE-PLAN.md` and updated `FINAL-ACCEPTANCE-REPORT.md`.

Historical failed runs retained. Original Monitor/session data untouched. This is a progress checkpoint, not a completed Final delivery.
''',encoding='utf-8')
print(json.dumps({'checkpoint':str(e/'CONTINUATION-CHECKPOINT.md'),'official_live_checks':sum(v is True for v in live['checks'].values()),'ui_tests':ui['tests']}))
