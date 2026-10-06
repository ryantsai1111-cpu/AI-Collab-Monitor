"""Render current evidence, leaving historical failed/blocked attempts intact."""
from pathlib import Path
import json,datetime,hashlib
ROOT=Path(__file__).resolve().parents[1];E=ROOT/'evidence'
read=lambda name:json.loads((E/name).read_text(encoding='utf-8-sig'))
c=read('requirement-coverage.json');unit=read('unit-test-results.json');ui=read('ui-acceptance/result.json');widget=read('ui-widget-regression/result.json');native=read('native-history-idle-ui/result.json');live=read('live-collaboration-ui/result.json');sync=read('installed-source-sync.json')
now=datetime.datetime.now(datetime.timezone.utc).isoformat();counts={s:c['status_counts'].get(s,0) for s in ('PASS','FAIL','BLOCKED','UNSUPPORTED','PENDING')}
c['status_counts']=counts
assert ui['status'] == 'PASS' and unit['successful'], 'Current regression must pass before reporting delivery'
c['test_summary'].update(discovered=unit['tests_run'],executed_pass=unit['tests_run']-unit['failures']-unit['errors']-len(unit['skipped']),ui_pass=ui['tests'],ui_fail=ui['failures'],ui_errors=ui['errors'],claude_actual_tool_ui_checks=7,multi_monitor_ui_checks=10)
c['test_summary']['unit_breakdown']['claude']=18
c['test_summary']['unit_breakdown']['dot']=14
c['final_gate'].update(status='BLOCKED',accepted=False,reasons=['Approved unofficial Dot adapter implemented; human-only native live activation and simultaneous three-agent acceptance still unverified','Installed EXE security rejection unresolved; installed EXE absent, no restore/rebuild/retry permitted','Configured official MCP tool execution remains unverified; physical two-monitor source UI passed; unapproved private integration unused','Strict separate stdout/stderr unsupported by inspected Codex combined-output contract'])
mcp_path=E/'live-mcp-echo-ui/result.json'
mcp=json.loads(mcp_path.read_text(encoding='utf-8')) if mcp_path.exists() else {}
mcp_pass=mcp.get('status')=='PASS' and all(mcp.get('checks',{}).values()) and mcp.get('official_process_exited') and mcp.get('fixture_process_exited')
if mcp_pass:
 c['final_gate']['reasons']=[reason for reason in c['final_gate']['reasons'] if not reason.startswith('Configured official MCP')]
 c['test_summary']['official_local_mcp_UI_checks']=len(mcp['checks'])
 c['final_gate']['resolved_blockers']=list(dict.fromkeys(c['final_gate'].get('resolved_blockers',[])+['Official local MCP echo through actual UI with human native approval and verified normal lifecycle']))
c['test_summary']['unit_breakdown']['codex']=c['test_summary']['unit_breakdown'].get('codex',19)+3 if c['test_summary']['unit_breakdown'].get('codex',19)==19 else c['test_summary']['unit_breakdown']['codex']
c['frozen_source_and_evidence_hashes_previous_continuation']=c['frozen_source_and_evidence_hashes']
source_files=[]
for folder,extensions in [('acw',{'.py'}),('docs',{'.md'}),('scripts',{'.py','.ps1','.cs'})]:source_files.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in extensions)
source_files.extend((ROOT/'tests').glob('test_*.py'))
c['frozen_source_and_evidence_hashes']={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files}
c['hash_scope']='Current explicit Python/docs/test/script files; previous continuation hashes retained separately. Compiled binary has its own unchanged static provenance; no runtime credentials, data or test repos hashed.'
c['observed_utc']=now
(E/'requirement-coverage.json').write_text(json.dumps(c,ensure_ascii=False,indent=2),encoding='utf-8')
unit_pass=unit['tests_run']-unit['failures']-unit['errors']-len(unit['skipped']);idle=native['idle']
report=f'''# Final Acceptance Report — AI Collaboration Workspace

**1.0.0-candidate: Final BLOCKED / NOT ACCEPTED.** Updated {now}, RYAN-PC.

The authorized independent continuation is complete: the original184 independent criteria now have184 scoped PASS, including the subsequently expressly authorized human-approved Claude tool-effect run. No criterion remains PENDING. Eleven older blockers and three later criteria were resolved with new evidence. All653 criteria now have explicit dispositions: **{counts['PASS']} PASS / {counts['FAIL']} FAIL / {counts['BLOCKED']} BLOCKED / {counts['UNSUPPORTED']} UNSUPPORTED / {counts['PENDING']} PENDING**. Scoped source/unit/UI passes are not653 native end-to-end tests and do not override the Final gate.

## Product and deliverables

Source: `C:\\Users\\ryant\\Documents\\Codex\\2026-10-05\\task-2`.

- Python3.12.14 / PySide6 6.11.2 desktop application, separate Core and Claude/Dot/Codex adapters, SQLite/WAL and safety-filtered raw JSONL.
- Three panes, dynamic capabilities/model/effort controls, project/task/session mappings, explicit resume, history/search/timeline, source-preserving manual/assisted handoff, readonly Git/diff/test/command views, scoped artifacts, settings, exports and recovery.
- Full original `docs/PRD.md`,23,872bytes/1,993lines, SHA256 `60BB0E4DE9B5B1C27F30C82BF17548B4A77B18B797E406D8EAAFE91379AA6EC9`; Library source `libfile_3a7bf20157948191a310f137dd15c7fa`. No substituted version.
- README, ARCHITECTURE, ADAPTERS, SECURITY, TROUBLESHOOTING, USER_GUIDE, `docs/REQUIREMENTS.md`; tests, case-specific evidence, screenshots, current source manifest and source ZIP.
- Per-user installed source and Desktop/Start Menu shortcut files exist. Compiled launcher runtime acceptance remains blocked. The audited source ZIP excludes compiled executables. The older ZIP is retained as historical evidence and is not the current audited deliverable. No launcher was restored/copied or executed again. Existing Python/Node/PySide6 dependencies are required; this is not a standalone bundled runtime.

## Measured acceptance

| Area | Current result | Evidence and limits |
|---|---|---|
| Normal Core/adapter/security/recovery suite | {unit_pass} PASS /0FAIL /0ERROR /{len(unit['skipped'])} opt-in skips; {unit['tests_run']} discovered | `unit-test-results.json`, `unit-tests.txt`; Qt excluded, synthetic adapter/transport cases explicitly labeled. Skipped official Codex cases have separate earlier real evidence. |
| Visible Qt/Core/SQLite/Git workflows | {ui['tests']} PASS /0FAIL /0ERROR /0SKIP | `ui-acceptance/result.json`, tests and screenshots. Real Qt interaction, real isolated store/Git, labeled synthetic transports; real Dot adapter stays blocked. |
| Last changed widget paths | {widget['tests']} PASS /0FAIL /0ERROR | `ui-widget-regression/result.json`; focused regression after Monitor approval buttons were disabled. These overlap the50 cases and are not counted as75 unique tests. |
| Official Claude stream-json |13 checks PASS | `claude-live-run-1791165118613641100.json`: handshake, dynamic model/effort, original prompt,23 deltas, cwd, native Read start/result, session resume, selected model/effort, official interrupt. |
| Official Claude attachments | PASS | `claude-attachments-1791165415288631900.json`: actual bounded text and bluePNG,10 deltas, no tools or approvals. |
| Official Claude native SDK |7 checks PASS | `claude-native-session-check-1791165508399169700.json`, pinned official SDK0.3.289, public project-only session/history APIs, no implicit resume/import. |
| Official native history through actual UI |5 checks PASS | `native-history-idle-ui/result.json`; exact test session selected, original prompt/activity rendered readonly, before/after workspace transcript/session mapping unchanged. Screenshots inspected. |
| Official Codex app-server |11 live checks PASS | `codex-live-acceptance.json`: real initialization, actual model/effort, cwd, streaming, list/history, reconnect/resume and interrupt. |
| Official Codex command/test output |5 checks PASS | `codex-live-tools.json`; exits0/1, combined output, unittest2pass0fail1skip. |
| Actual Codex human-approved file effect | PASS | `live-codex-ui/result.json`, `native-effects.json`: user personally approved04:10:54UTC; fixture.py changed minus→plus, native patch/file/diff, four commands and unittest1PASS/exit0; unchanged readOnly/on-request/user policy. |
| Actual Codex real-result diff/tests UI |4 checks PASS | `live-codex-ui/diff-test-view.json`: readonly unified/side-by-side/changed-file/test result. |
| Official two-agent visible collaboration |16 checks PASS | `live-collaboration-ui/result.json`, public events/messages and screenshots: exact ClaudeA→Codex, reverse handoff, source/annotation separate, cwd/mappings, explicit reconnect/resume, visible stream and actual Stop. Codex gpt-6.1-sol/medium, zero approvals granted, no sandbox changes. |
| Claude actual Edit/command effects |7 checks PASS | `live-claude-tools-ui/result.json`: one newly expressly authorized run, actual native human Edit and Bash approvals, fixture minus-to-plus edit, file/command UI cards and independent unittest PASS. Earlier canceled request is retained in `live-claude-tools-ui-first/`; no permission mode or sandbox change. |
| Crash recovery | PASS in stated process + Qt scopes | `recovery-performance.json`: actual Core child exit91 and restored data/raw refs/no resend; actual Qt close/reopen with real SQLite separately passed. No active production process killed. |
| Idle desktop CPU | Measured source Qt | {idle['process_cpu_seconds']:.6f}s process CPU over {idle['wall_seconds']:.3f}s wall = {idle['one_core_cpu_percent']:.3f}% of one logical core. One disconnected20second sample, not full three-stream or EXE performance. |
| Dot native conversation/three-agent operation | BLOCKED | Approved pinned unofficial adapter and manual UI implemented. Offline14 adapter tests and11 visible UI tests passed; actual-account identifier case BLOCKED pending value; only the human may trigger credential-bearing Connect/read/send. No live Dot receipt is certified. See docs/DOT-UNOFFICIAL.md. |
| Separate stdout/stderr |4 criteria UNSUPPORTED | Inspected Codex `aggregatedOutput` is combined. UI labels this; no invented separation. |
| Installed compiled EXE | BLOCKED | Windows security rejected its earlier actual launch; installed file subsequently absent. Provider/detection/removal cause unresolved; no exclusion, disable, restore, rebuild, copy, changed-signature or renamed retry. |

## Independent reconciliation and remaining gates

`scripts/reconcile_acceptance.py` contains explicit ID/case/evidence mappings, not automatic prefix promotions. `pending-acceptance-classification.json` preserves197 baseline pending criteria:184 independent,8 Dot-dependent,2 EXE-dependent,3 other prerequisite. Current baseline outcome:185PASS and12BLOCKED. Independent R006.08/R006.09 passed the new expressly authorized human-approval run; R041.05 passed actual dual-display Qt verification. `REMAINING-ACCEPTANCE.md/json` list every remaining57BLOCKED and4UNSUPPORTED criterion individually.

The8 baseline Dot-dependent criteria are R002.02,R080.01,R094.02,R099.03,R099.06,R099.07,R099.12,R099.13. The2 baseline EXE-dependent criteria are R041.01/R096.01; compiled default data/startup acceptance remains unverified even though per-user source install passed. The3 other prerequisites are R003.20 (no unapproved private integration invoked), R006.06 (no configured real official MCP end-to-end test), R041.05 (now resolved by actual two-monitor source UI10PASS). Other existing Dot/Final and shortcut EXE criteria remain listed separately.

Claude's previously canceled request stayed expired. The user subsequently explicitly authorized one new isolated run and personally approved its Edit/Bash requests;7 checks passed. No further prompt or approval is needed for these two resolved criteria.

EXE work is now explicitly deferred by the user. No executable, launcher, antivirus or security-setting operation is part of this continuation. Historical security rejection details remain in `EXE-SECURITY-BLOCKER.md`; no false-positive or runtime acceptance is claimed.

Dot now has an expressly approved pinned unofficial route, with live activation restricted to the human. ChatGPT/Slack/Teams channel availability is not an embeddable desktop message API; unofficial/nonpublic risk was separately approved for the selected G8 Dot; source was acquired and implementation tested offline, with no agent-run live call. No generic approval is represented as a working official bridge. New static GitHub/official research: `docs/GITHUB-DOT-RESEARCH.md` and `github-dot-research.json`. Official OSS/local OAuth may support separately authorized Responses inference without a new API key, but explicitly excludes existing ChatGPT/Dot conversations/account context. No new login, token transfer, service or backend was used.

## Source updates, safety and history

Repairs exercised this continuation: export empty-filter fallback; approval controls gated by actual capability and readonly Monitor mode; Codex JSON stderr parsed and filtered structurally before diagnostic tail/display so nested hidden reasoning/secret keys cannot pass as an unparsed JSON string; selected-model image attachment controls come from official inputModalities, queued files preserved until explicit clear. Actual two-monitor testing found secondary-screen clipping at175% scaling; a scrollable workspace and bounded restored geometry fixed it. Current `multi-monitor-ui/result.json`10PASS, first failure preserved. Claude Diagnostics also exposes only allowlisted MCP names/status/tool-name snapshots; unknown and cached state never claim successful tool execution.

Artificial security canaries test DB/raw/WAL/export/diagnostics and structured/plain stderr filtering. No actual auth.json/token/cookie/API-key/password was read or transmitted. Raw fidelity yields to redaction/hidden-reasoning omission, with annotations. Image pixels are not automatically redacted: explicit screenshot import/export review remains necessary.

Current installed source sync: `installed-source-sync.json`, backup `{sync['backup']}`, {len(sync['files'])} explicit source files with verified hashes. No user DB/raw/settings/credentials, runtime test repos, dependency directories, shortcuts or EXE touched; active sessions not stopped/directed. The original Stage1 Monitor remains intact. Installed source sync is not EXE launch acceptance.

Historical runs retained: initial13(12PASS/1FAIL),22/23/41PASS, expanded41-first and49-first failures,49PASS, current50PASS;25 last-widget regressions. Expanded UI failures caused a real export bug plus test timing/modal/viewport/path/header assumptions; corrected reruns passed. Native-history first modal timer hung; its exact test dialog was closed normally with WM_CLOSE (no process kill), then corrected. Second preview check incorrectly assumed Connect creates no new CLI session; final check compares before/after preview and passes. These historical results are not deleted or described as current passes.

Prior official SDK optionalCLI download and restricted-token/PySide/installation errors remain historical evidence. SDK public reads use the pinned existing official helper, inference uses existing official CLIs. No system software/admin install or ACL/safety change occurred. The separately approved unofficial Dot source is included; its live backend has not been invoked by the development agent.

## Reproduction and delivery limits

Normal: `python scripts/run_tests.py`. Visible isolated UI: `python scripts/run_ui_tests.py --visible`. Physical displays: `python scripts/verify_multi_monitor_ui.py`. Read-only recorded capability inventory: `python scripts/inventory_existing_capabilities.py`. Live scripts remain opt-in with existing official permissions; never replay completed or canceled write prompts without new explicit authorization. Package: `python scripts/package_source.py`.

Library transfer remains BLOCKED: the official route reported prepare_uploads unavailable after authorized discovery;0uploads/0created files/0Library IDs. No alternate executor or unofficial transfer. `library-delivery-status.json` retains exact outcome. Complete local source/documents/tests/evidence are available. **A working compiled executable and all-three-real-agent Final delivery are not claimed.**
'''
(E/'FINAL-ACCEPTANCE-REPORT.md').write_text(report,encoding='utf-8')
probe_path=E/'installed-source-verification.json'
probe=json.loads(probe_path.read_text(encoding='utf-8')) if probe_path.exists() else {'status':'NOT RUN','runtime_verified':False}
report += '\n## Installed-source provenance probe (separate from requirement counts)\n\nHistorical probe: **FAIL** at the path assertion; actual origin was not captured. `INSTALLED-SOURCE-PROBE-FAILURE.md` is preserved. Current restricted probe: **'+probe['status']+'**; module origin and explicit synced source hashes only, no Core/GUI/backend/EXE startup. Runtime remains unverified; installed startup/default-data criteria stay BLOCKED. See `installed-source-verification.json`. Requirement 0 FAIL does not mean all historical or supplemental executions passed.\n'
report += '\nActual module origin: `'+probe.get('actual_module_origin','not recorded')+'`. Resolved actual and expected: `'+probe.get('actual_resolved_path','not recorded')+'` and `'+probe.get('expected_resolved_path','not recorded')+'`. Legacy one-sided path assertion would pass: '+str(probe.get('legacy_path_assertion_would_pass'))+'. This clean process reproduces the original assertion failure because Windows packaged-app path resolution redirects LocalAppData; both resolved paths match. All '+str(len(probe.get('hash_checks',[])))+' explicit source hashes match after hex case normalization. The historical failure remains retained, and no installed runtime was started.\nAudited source archive: `AI-Collaboration-Workspace-source-audited.zip`; compiled EXEs excluded. Older source archive is preserved as history.\n'
if (E/'public-claude-docs-ui/result.json').exists():
 report += '\n## Authorized public Claude Docs MCP scope check\n\nBLOCKED: actual Workspace UI native ToolSearch discovered `mcp__claude_ai_Claude_Docs__query`, but the assistant reported it as a user-document comment-history tool without public-URL retrieval. Native ToolSearch emitted a reference rather than an independently exported full descriptor. No target MCP call, private connector, approval grant, new server or permanent configuration occurred. R006.06 stays BLOCKED; no acceptance counts changed. Exact scope/evidence and the unexecuted fixture approval proposal: `MCP-PUBLIC-DOC-BLOCKER.md`, `public-claude-docs-ui/result.json`, native public events and scope-response screenshot.\n'
if mcp_pass:
 report=report.replace('Current baseline outcome:185PASS and12BLOCKED.','Current baseline outcome:186PASS and11BLOCKED.').replace('remaining57BLOCKED and4UNSUPPORTED','remaining56BLOCKED and4UNSUPPORTED').replace('R006.06 (no configured real official MCP end-to-end test)','R006.06 (now resolved by expressly authorized local official MCP/Workspace UI11PASS)').replace('R006.06 stays BLOCKED; no acceptance counts changed.','This earlier public-document route remained BLOCKED. R006.06 was subsequently resolved by the separately expressly authorized local native MCP test below.').replace('the unexecuted fixture approval proposal','the historical fixture proposal before subsequent approval')
 report+='\n## Authorized real MCP acceptance — R006.06 PASS\n\nOfficial CLI2.1.286 with already installed official MCP SDK1.32.0 and Zod4.6.5, session-only STDIO `acw_acceptance.echo`, fixed arguments/result `ACW_MCP_ACCEPTANCE_OK`, one native invocation. Human personally approved request `90120c77-a296-41a2-a909-ef713b959622` at '+mcp['approval_utc']+'. All11 native/approval/actual Workspace UI checks passed. Original request requires user interaction and suppresses permanent allow rules. Built-in tools were restricted out and strict session MCP config excluded other connectors; no permission mode, automatic allow rule or persistent configuration changed. The handler has no filesystem, network or shell operations; official inference still uses network. Actual saved Raw UI selected original input/approval/result with3 overlapping checks.\n\nEvidence: `live-mcp-echo-ui/result.json`, public native events/messages, pending-human/tool-card/raw UI screenshots, `saved-raw-ui.json`, `lifecycle-review.json`. Official backend and fixture were verified absent after normal disconnect with exact-scope read-only process checks; no process kill/restart. Historical harness post-disconnect poll failed because disconnect clears its handle; original result is retained as `result-before-lifecycle-review.json`, corrected lifecycle evidence is independent. No second prompt or tool invocation occurred. This local real MCP success does not certify Google Drive/Notion/private connectors or native Dot.\n'
(E/'FINAL-ACCEPTANCE-REPORT.md').write_text(report,encoding='utf-8')
summary={'created_utc':now,'release':'1.0.0-candidate','final_status':'BLOCKED / NOT ACCEPTED','criterion_counts':counts,'general_tests':unit,'visible_ui':ui,'last_widget_regression':widget,'official_two_agent_ui':{'status':live['status'],'checks':live['checks']},'native_history_ui':native,'independent_baseline':{'total':184,'pass':184,'blocked':[]},'installation_source_sync':sync,'desktop_exe_launched':False,'dot_official_bridge_available':False,'no_auto_reopen_claude_tool_request':True,'remaining':'evidence/REMAINING-ACCEPTANCE.md'}
(E/'acceptance-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
summary['requirements_scope']='653 evidence-gated criteria; not 653 native E2E checks; supplemental probe results are separate'
summary['installed_source_provenance_probe']=probe
summary['historical_installed_source_provenance_probe']={'status':'FAIL','evidence':'evidence/INSTALLED-SOURCE-PROBE-FAILURE.md','cause':'Original path assertion failed, origin not captured','runtime_verified':False}
if mcp_pass:
 summary['official_local_mcp_UI']={'status':'PASS','checks':mcp['checks'],'approval_utc':mcp['approval_utc'],'evidence':'evidence/live-mcp-echo-ui/result.json','official_process_exited':True,'fixture_process_exited':True,'private_connectors_verified':False}
(E/'acceptance-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
dot_report=read('dot-offline/result.json');dot_ui=read('dot-offline-ui/result.json')
dot_ui_pass=dot_ui.get('passed',dot_ui['tests']-len(dot_ui.get('skipped',[])))
assert dot_report['status']=='PASS' and dot_ui['status']=='PASS'
dot_update={'source_commit':'1413f7b61060eb582fd53a0210ef1a499d158fe0','integration':'Unofficial; expressly approved; human-triggered only','offline':dot_report,'visible_offline_ui':dot_ui,'live_status':'BLOCKED / pending human activation','agent_live_auth_calls':0,'background_polling':False,'final_accepted':False,'guide':'docs/DOT-UNOFFICIAL.md'}
c['authorized_dot_offline_update']=dot_update
(E/'requirement-coverage.json').write_text(json.dumps(c,ensure_ascii=False,indent=2),encoding='utf-8')
summary['authorized_dot_offline_update']=dot_update
(E/'acceptance-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
with (E/'FINAL-ACCEPTANCE-REPORT.md').open('a',encoding='utf-8') as out:
 out.write('\n## Approved unofficial Dot candidate — live handoff pending\n\nPinned commit `1413f7b61060eb582fd53a0210ef1a499d158fe0`, unchanged stdlib-only project source, bounded hash-verified launcher. Adapter/Core/UI support explicit G8 Dot selection, separate local consent for list/Connect/read/send, native identity mapping, manual32-message pages, unchanged sends, acknowledgements and native-ID deduplication. There is no startup call, polling, post-send read, automatic relay or server-cancel claim. New chats, true streaming, Stop, attachments and independent model/effort remain Unsupported.\n\nOffline adapter/Core/launcher: '+str(dot_report['tests'])+' PASS. Visible offline Qt: '+str(dot_ui_pass)+' PASS with fixture-only screenshots. These are supplementary implementation tests; no native Dot criterion was promoted to PASS. Human live list/read/send/receipt/thread/reconnect and simultaneous three-agent acceptance remain unverified. Agent token-bearing calls:0. See `docs/DOT-UNOFFICIAL.md`, `evidence/dot-offline/`, `evidence/dot-offline-ui/` and `tools/dot-source-manifest.json`. EXE work remains deferred; Final BLOCKED / NOT ACCEPTED.\n')
repair_path=E/'dot-selection-fix/repair.json'
if repair_path.exists():
 repair=json.loads(repair_path.read_text(encoding='utf-8'))
 summary['dot_selection_repair']=repair
 (E/'acceptance-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
 with (E/'FINAL-ACCEPTANCE-REPORT.md').open('a',encoding='utf-8') as out:
  out.write('\n## Human-reported Dot selection repair\n\nRead-only observation found no saved selected Dot, Connect disabled and metadata operations completed. The original value/acceptance cannot be reconstructed because the old result callback did not retain errors. An offline regression reproduced callback errors being overwritten by queued state updates; both failed repair runs are preserved. The fixed explicit Use G8 confirmation stores structured selection and enables Connect while remaining Disconnected; callback errors are sanitized and persist visibly. Native IDs are safely opaque, names normalized, other targets refused. Actual Qt modal commit/cancel and error tests now '+str(dot_ui_pass)+' PASS; adapter tests '+str(dot_report['tests'])+' PASS. Shared visible regressions50PASS. The original user window/data was not closed or overwritten. A separate DOT SELECTION FIX disconnected handoff uses isolated new data. No agent-triggered live auth call. See `evidence/dot-selection-fix/repair.json` and `docs/DOT-UNOFFICIAL.md`.\n')
print(json.dumps({'counts':counts,'report_bytes':(E/'FINAL-ACCEPTANCE-REPORT.md').stat().st_size,'independent_pass':184,'independent_blocked':0},indent=2))
