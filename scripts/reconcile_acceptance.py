"""Explicit criterion evidence mapping; never infer PASS from an ID prefix."""
from pathlib import Path
import json,datetime,collections,re
ROOT=Path(__file__).resolve().parents[1];E=ROOT/'evidence'
load=lambda n:json.loads((E/n).read_text(encoding='utf-8'))
coverage=load('requirement-coverage.json');baseline=load('pending-acceptance-classification.json');ui=load('ui-acceptance/result.json')
assert ui['status']=='PASS', 'Do not promote criteria while the latest UI run has failures'
live=load('live-collaboration-ui/result.json');assert live['status']=='PASS'
mapping={}
def record(ids,path,case,scope):
 for rid in ids.split():
  assert rid not in mapping,rid
  mapping[rid]={'path':path,'case':case,'scope':scope}
def widget(ids,case,scope='Actual visible isolated Qt interaction with explicit synthetic transport; real Core/SQLite/Git where test_workspace_ui is named'):
 record(ids,'evidence/ui-acceptance/tests.txt',case,scope)
def official(ids,case,scope='Official Claude/Codex visible UI in isolated data/repo, no permissions granted or sandbox changes; Dot excluded'):
 record(ids,'evidence/live-collaboration-ui/result.json',case,scope)

official('R001.05 R001.06 R003.14 R003.15 R004.08 R005.07 R006.05 R010.01 R068.05 R068.06 R075.02 R075.03','project_cwd_sync; two_test_sessions_mapped; actual_UI_explicit_resume')
official('R003.11 R003.12 R052.01 R052.03 R099.04 R099.05','actual_model_effort_capability; actual_claude_literal_A; UI_render_during_real_stream')
widget('R003.13 R003.17 R050.01','test_only_discovered_model_and_effort_choices; test_startup_never_connects_and_dot_is_honestly_blocked','Actual Qt unsupported/default labels and disabled selectors, plus official backend discovery in live-collaboration-ui/result.json; no separate invented Thinking selector')
widget('R003.16 R005.19','test_unsupported_approval_is_readonly_and_never_dispatches; test_pending_approval_remains_visible_after_event_burst_and_requires_user_action','Actual Qt approval-capability gating with explicitly synthetic request; real human-approved Codex write independently in live-codex-ui/result.json')
widget('R004.10 R028.10','test_only_discovered_model_and_effort_choices; test_state_capability_no_fake_web_terminal_voice_and_known_branch_counts; test_real_qt_click_sends_selected_values_through_core')
widget('R004.11 R057.01 R057.02 R057.03','test_actual_local_drop_requires_capability_and_dispatches_attachment_contract','Actual Qt local MIME drag/drop into input and real Core attachment dispatch to explicit synthetic adapter; unsupported branch rejects; no claim of native filesystem attachment execution')
widget('R005.03','test_session_new_rename_select_and_explicit_resume_use_real_mapping','Actual UI local rename alias persisted in SQLite; backend session ID unchanged, not a native CLI title mutation')
widget('R001.07 R005.08 R024.01 R024.02 R024.03 R024.04 R024.05 R024.06 R024.07 R024.08 R099.14','test_history_filters_search_and_double_click_restore_real_store; test_history_filters_and_search_are_forwarded_to_core')
widget('R005.12 R005.13 R056.01 R056.02','test_copy_plain_metadata_and_open_raw_are_actual_readonly_widgets')
widget('R005.14 R005.15 R020.05 R099.16','test_actual_utility_buttons_resolve_logs_project_and_scoped_diff_file','Actual Qt utility controls with real scoped Core paths and mocked QDesktopServices boundary; invalid path rejected before dispatch. Does not certify OS file-handler launch.')
widget('R005.18 R005.20 R005.21 R005.22','test_state_capability_no_fake_web_terminal_voice_and_known_branch_counts','No invented standalone MCP/Web/Terminal/Voice controls. Native tool events remain activity; configured live MCP is separately blocked, not passed by absence of a button.')
widget('R014.01 R014.03 R062.01 R062.02 R062.03 R062.04','test_forward_menu_lists_other_agents_and_blocked_dot_preview_is_disabled','Actual other-agent Forward menu, Dot preview disabled; source agent omitted to prevent self-forward. Dot option presence does not certify delivery.')
official('R015.02 R015.03 R061.03 R061.05 R063.01 R063.02 R063.03 R063.04 R064.01 R068.04 R074.01 R074.04','actual_claude_literal_A; actual_claude_to_codex_exact_original; source_annotation_separate; actual_codex_to_claude')
widget('R017.01','test_real_qt_click_sends_selected_values_through_core; test_copy_plain_metadata_and_open_raw_are_actual_readonly_widgets')
widget('R017.03 R017.04 R017.05 R017.06 R017.07 R017.08 R017.10 R018.01 R018.02 R018.03 R018.04 R018.05 R018.06 R018.07 R019.01 R019.02 R019.03 R019.04 R019.05','test_event_rendering_replays_public_claude_tool_and_command_fields','Actual Qt public recorded official Claude Read tool/file replay plus labeled command/system/error fixtures; real Codex command rendering separately verified in live-codex-ui/native-effects.json and diff-test-view.json')
widget('R020.06 R020.07','test_diff_copy_and_save_write_real_safe_patch_and_original_repo_unchanged','Actual Qt diff clipboard and real safe patch write; source repo not edited by viewer')
widget('R022.02 R022.03 R022.04 R022.05 R022.06 R022.07 R022.08 R022.09 R022.10 R022.11 R022.12 R099.17','test_timeline_contains_each_recorded_semantic_event','Real Core persisted semantic events and actual Qt timeline; fixture events are labeled, native official events independently in live-collaboration-ui/public-events.json')
widget('R023.01','test_raw_event_index_renders_sanitized_store_record','Actual readonly Qt raw index and persisted sanitized event; three panes share implementation, no Dot native JSON claim')
widget('R037.01 R037.02 R037.03 R037.04 R037.05 R037.06 R037.07 R037.08','test_settings_all_pages_save_only_local_values_and_gate_backend_choices')
widget('R038.01 R038.02 R038.03 R038.04 R038.05 R038.06 R038.07 R038.08 R038.09','test_agent_settings_actual_controls_store_discovered_defaults_and_fixed_audit_policy','Actual Qt enabled/executable/timeout/discovered model/effort/project controls and real persisted values. Backend identity is readonly; streaming and filtered raw audit exposed as required fixed policy, not fake editable settings.')
widget('R041.04 R041.06 R041.07 R041.08 R041.09','test_window_geometry_fullscreen_topmost_minimize_and_no_default_tray','Actual Qt window size restoration/F11/flag/minimize state/no tray instance; EXE execution and multi-monitor excluded')
widget('R045.01 R046.01','test_each_agent_stop_and_global_stop_requires_actual_confirmation','Actual Qt independent Stop and real No/Yes global dialog, adapter-only synthetic cancellation; official Codex Stop separately PASS')
official('R048.01 R048.02','disconnect_shown; actual_UI_explicit_resume')
widget('R049.01 R049.02 R089.01 R089.02','test_offline_history_and_actionable_backend_error_remain_visible')
widget('R054.02','test_comparison_shows_two_original_responses_without_verdict')
widget('R055.03','test_notes_and_assisted_handoff_keep_source_and_annotation_separate')
widget('R058.01 R058.02 R075.01 R099.02','test_ui_project_selection_syncs_real_core_and_discards_only_confirmed_draft')
widget('R059.01 R059.02 R059.03 R059.04 R059.05 R059.06 R059.07 R059.08 R059.09','test_git_branch_dirty_divergence_and_non_git_display; test_state_capability_no_fake_web_terminal_voice_and_known_branch_counts','Actual Qt branch/dirty/known-count presentation; real isolated Git upstream extraction independently tested by test_existing_upstream_reports_actual_ahead_behind. No upstream is displayed unknown, not zero.')
official('R068.01 R068.02 R068.03','actual_claude_tool_UI; UI_render_during_real_stream; source_annotation_separate')
widget('R076.01 R086.01','test_close_reopen_restores_task_project_session_history_without_resend','Actual source Qt close/reopen with real SQLite; process-crash recovery independently recorded in recovery-performance.json')
widget('R084.01 R084.02','test_legacy_monitor_actual_incremental_logs_and_timeline_are_readonly','Actual fixture four-log legacy monitor integration, incremental reads and unchanged hashes; original monitor kept untouched')
widget('R087.02 R087.03 R087.04 R087.05 R087.06','test_state_capability_no_fake_web_terminal_voice_and_known_branch_counts','Actual independent Qt Connecting/Connected/Busy/Error states; native Connected/Busy separately observed in official live run')
widget('R090.01 R090.02 R090.03 R090.04 R090.05 R090.06 R090.07 R090.08','test_diagnostics_shows_version_session_cwd_error_and_exports_safe_zip','Actual readonly Qt diagnostics with real Core keys and safe ZIP; executable/backend/session fields also in official live diagnostics')
widget('R091.01 R091.02 R091.03 R091.04','test_exports_actual_task_all_four_formats_through_ui_and_redact','Actual export button, real Core output files and contents/redaction; chooser destination explicitly mocked to isolated path')
record('R099.08 R099.09 R099.10 R099.11','evidence/live-codex-ui/diff-test-view.json','native-effects.json; unified; side_by_side; changed_files; tests','Actual human-approved official Codex effects and visible real-result Diff/Tests UI, no synthetic native write claim')
record('R099.15','evidence/recovery-performance.json','actual crash recovery child exit 91','Actual child process crash, restored project/task/session/history/raw refs, no resend; Qt close/reopen independently tested')
record('R099.18','evidence/unit-test-results.json','test_all_known_secret_split_indices_stay_out_of_database_and_raw; test_tool_and_safe_raw_content_survive_persistence_with_secret_redaction; visible UI secret canaries','Known artificial secret/redaction regression suite plus UI raw/export/diagnostic canaries; does not claim proof for every possible unknown secret encoding')
record('R099.19','evidence/unit-test-results.json','test_prompt_and_notes_do_not_force_format_or_transmit_notes','Original prompt contract and original native replies persisted; explicit test prompt literal A is a user request, not forced application output formatting')

now=datetime.datetime.now(datetime.timezone.utc).isoformat();criteria={r['id']:r for r in coverage['criteria']};changed=[];unmapped=[]
for row in baseline['criteria']:
 rid=row['id'];actual=criteria[rid]
 if row['group']=='INDEPENDENT':
  if rid in mapping:
   ev=mapping[rid];actual.update(status='PASS',evidence=[ev,{'path':'evidence/ui-acceptance/result.json','scope':f"Latest visible run {ui['tests']} PASS, timestamp {ui['timestamp']}"}],reason=ev['scope']);changed.append(rid);row.update(status='PASS',evidence=ev)
  else:unmapped.append(rid)
 else:
  actual.update(status='BLOCKED',reason=row['reason'],evidence=[{'path':'evidence/PENDING-ACCEPTANCE-PLAN.md','scope':row['group']+' prerequisite; no substituted pass'}]);row['status']='BLOCKED'
assert set(unmapped)=={'R006.08','R006.09'}, f'Unexpected uncovered independent criteria: {unmapped}'
for rid in unmapped:
 actual=criteria[rid];actual.update(status='BLOCKED',reason='Actual official Claude tool attempt requested native Edit approval; user reported the window closed. Request canceled without granting; fixture unchanged. Command execution was not reached. No automatic reopen/re-send authorized by latest steering.',evidence=[{'path':'evidence/live-claude-tools-ui-first/result.json','scope':'Official native request, no permission granted, canceled; actual Edit/command effects unpassed'}])
 next(row for row in baseline['criteria'] if row['id']==rid).update(status='BLOCKED',reason=actual['reason'],evidence=actual['evidence'])
coverage['status_counts']=dict(collections.Counter(r['status'] for r in coverage['criteria']))
additional={
 'R005.16':('evidence/ui-acceptance/tests.txt','test_actual_local_drop_requires_capability_and_dispatches_attachment_contract; test_model_change_gates_attachments_and_preserves_queued_files_until_explicit_clear','Actual Qt supported/unsupported attachment controls and selected-model policy; independent official Claude text/image wire acceptance in claude-attachments-1791165415288631900.json'),
 'R005.17':('evidence/ui-acceptance/tests.txt','test_model_change_gates_attachments_and_preserves_queued_files_until_explicit_clear','Actual Qt image-model versus text-model control gating; official Codex discovery informs the pure selected-model policy, protocol regression in unit-tests.txt'),
 'R005.23':('evidence/ui-acceptance/tests.txt','test_actual_local_drop_requires_capability_and_dispatches_attachment_contract','Actual Qt viewport drop, real Core scoped dispatch to labeled synthetic adapter and unsupported rejection; real official Claude attachment tests separately evidenced'),
 'R006.07':('evidence/live-collaboration-ui/result.json','actual_claude_tool_UI','Real Claude Read tool and result observed in actual source Qt with screenshots'),
 'R071.08':('evidence/live-collaboration-ui/result.json','actual_claude_tool_UI','Official native Claude Read tool activity rendered in visible Qt; no Edit grant inferred'),
 'R079.07':('evidence/ui-acceptance/result.json','50 visible cases; ui-widget-regression/result.json 25 PASS','Stage 7 three-panel UI implementation exercised with real Qt and explicit fixture scope, plus official two-agent UI16 checks. Dot backend is separately Stage 6 blocked; no three-native-agent Final claim.'),
 'R079.10':('evidence/ui-acceptance/tests.txt','test_history_filters_search_and_double_click_restore_real_store; test_timeline_contains_each_recorded_semantic_event','Stage 10 real SQLite/Core search/filter/history restoration and visible Qt timeline, not just filter forwarding'),
 'R079.11':('evidence/live-codex-ui/diff-test-view.json','native-effects.json; actual diff/test viewer4PASS; current UI50 safe open/copy/save tests','Stage 11 actual official Codex human-approved command/diff/test results rendered plus current isolated viewer actions; original command-expansion failure resolved and historical evidence retained'),
 'R079.12':('evidence/recovery-performance.json','actual crash child exit91; test_close_reopen_restores_task_project_session_history_without_resend; security regression125PASS','Stage 12 actual Core process crash and restored DB/raw state, actual Qt close/reopen, no resend, secret boundary regressions. No forced kill of active production/native sessions.'),
}
native=load('native-history-idle-ui/result.json');assert native['status']=='PASS'
additional['R006.10']=('evidence/native-history-idle-ui/result.json','official_native_session_list; original_session_selected; history_original_prompt; history_readonly; no_transcript_import_or_resume','Actual official SDK session discovery and selected readonly Qt history; state compared before/after preview, no implicit import/resume')
additional['R094.01']=('evidence/native-history-idle-ui/result.json','idle.wall_seconds; idle.process_cpu_seconds; idle.one_core_cpu_percent','Measured disconnected source Qt process CPU over20seconds; not compiled EXE or three-native-stream performance')
for rid,(path,case,scope) in additional.items():
 criteria[rid].update(status='PASS',evidence=[{'path':path,'case':case,'scope':scope}],reason=scope)
coverage['status_counts']=dict(collections.Counter(r['status'] for r in coverage['criteria']))
for rid in ('R079.08','R079.09','R080.02','R099.01','R099.20'):
 criteria[rid]['reason']='Local/Qt and official Claude/Codex scoped checks now pass. Full stated three-agent stage/Final scope still requires unavailable approved Dot transport; EXE launch and ungranted Claude Edit/command effect also remain blocked. Historical13-case UI failure is resolved, not a current blocker.'
for section in coverage['sections']:
 counts=collections.Counter(r['status'] for r in coverage['criteria'] if r['section']==section['section']);section['counts']=dict(counts);section['status']=next(s for s in ('FAIL','BLOCKED','PENDING','UNSUPPORTED','PASS') if counts[s])
coverage['observed_utc']=now
general=load('unit-test-results.json')
coverage['test_summary'].update(discovered=general['tests_run'],executed_pass=general['tests_run']-general['failures']-general['errors']-len(general['skipped']),ui_authored=ui['tests'],ui_executed=ui['tests'],ui_pass=ui['tests'],ui_fail=0,ui_errors=0,ui_scope='50 visible isolated Qt/Core/Git cases plus25 focused widget regression; official two-agent UI16 PASS and native readonly history5 PASS',native_history_ui_checks=5)
coverage['independent_reconciliation']={'observed_utc':now,'mapped_pass':changed,'remaining_independent':unmapped,'mapping':'scripts/reconcile_acceptance.py','scope':'Explicit named criterion/case mappings, not prefix-based promotion'}
coverage['independent_reconciliation']['additional_resolved_previous_blockers']=list(additional)
baseline['reconciled_utc']=now;baseline['outcome_counts']=dict(collections.Counter(r['status'] for r in baseline['criteria']))
(E/'requirement-coverage.json').write_text(json.dumps(coverage,ensure_ascii=False,indent=2),encoding='utf-8');(E/'pending-acceptance-classification.json').write_text(json.dumps(baseline,ensure_ascii=False,indent=2),encoding='utf-8')
doc=ROOT/'docs/REQUIREMENTS.md';text=doc.read_text(encoding='utf-8');lines=text.splitlines()
for n,line in enumerate(lines):
 match=re.match(r'\| (R\d+\.\d+) /',line)
 if match and match.group(1) in ({r['id'] for r in baseline['criteria']} | set(additional) | {'R079.08','R079.09','R080.02','R099.01','R099.20'}):
  r=criteria[match.group(1)];links='; '.join(f"{ev['path']} ({ev.get('case',ev.get('scope',''))})" for ev in r['evidence']);lines[n]=f"| {r['id']} / {r['planned_case']} | {r['criterion']} | {r['status']} | {r['reason'].replace('|','/')} Evidence: {links.replace('|','/')} |"
text='\n'.join(lines)+'\n';counts=coverage['status_counts'];text=re.sub(r'Counts: \*\*[^*]+\*\*', 'Counts: **'+', '.join(f'{counts.get(s,0)} {s}' for s in ('PASS','FAIL','BLOCKED','UNSUPPORTED','PENDING'))+'**',text,count=1)
text=text.replace('Visible UI23 passed including fixed pending-review reminder;',f"Visible UI{ui['tests']} passed with explicit independent criterion mappings and official two-agent UI16 PASS;")
doc.write_text(text,encoding='utf-8')
remaining=[{'id':r['id'],'criterion':r['criterion'],'status':r['status'],'reason':r.get('reason',''),'evidence':r.get('evidence',[])} for r in coverage['criteria'] if r['status']!='PASS']
(E/'REMAINING-ACCEPTANCE.json').write_text(json.dumps({'observed_utc':now,'final_gate':'BLOCKED','counts':counts,'criteria':remaining},ensure_ascii=False,indent=2),encoding='utf-8')
(E/'REMAINING-ACCEPTANCE.md').write_text('# Remaining acceptance criteria\n\nFinal remains BLOCKED. A scoped PASS does not replace blocked native-agent or executable acceptance.\n\n| ID | Status | Requirement | Specific blocker or limitation |\n|---|---|---|---|\n'+'\n'.join(f"| {r['id']} | {r['status']} | {r['criterion']} | {r['reason'].replace('|','/')} |" for r in remaining)+'\n',encoding='utf-8')
print(json.dumps({'independent_mapped':len(changed),'remaining_independent':unmapped,'counts':counts},indent=2))
