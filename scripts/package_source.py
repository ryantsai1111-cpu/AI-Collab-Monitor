"""Package only reviewed source, documentation, tests and sanitized evidence."""
from pathlib import Path
import hashlib,json,zipfile,datetime
root=Path(__file__).resolve().parents[1]
files=[]
for name in ('README.md','requirements.txt','run.py','install.ps1','python-path.txt','.gitignore'):
 files.append(root/name)
for directory in ('acw','docs'):
 files.extend(p for p in (root/directory).rglob('*') if p.is_file() and p.suffix in {'.py','.md','.json'})
files.extend((root/'tests').glob('test_*.py'))
files.extend(root/'tests'/'fixtures'/name for name in ('g8-dot-contract-sample.json','g8-dot-observed.json') if (root/'tests'/'fixtures'/name).exists())
files.extend((root/'tools'/'chatgpt-dot-cli-pinned'/'chatgpt_dot').glob('*.py'))
files.extend(root/'tools'/'chatgpt-dot-cli-pinned'/name for name in ('LICENSE','pyproject.toml','README.md','SECURITY.md'))
files.append(root/'tools'/'dot-source-manifest.json')
files.extend(root/'scripts'/name for name in ('dot_cli_entry.py','run_dot_offline_tests.py','open_dot_handoff.py'))
files.extend(root/'scripts'/name for name in ('run_session_labels_ui.py','run_exe_claude_review_ui.py'))
files.extend(root/'scripts'/name for name in ('installer_policy.py','package_context.py','ascii_json_helpers.ps1','build_launcher.ps1','launcher.manifest',
    'launch_validation_helpers.ps1','launch_observation.py','read_launch_snapshot.py','run_exe_source_tests.py'))
files.extend(p for p in (root/'evidence'/'exe-source-hardening'/'original-source').rglob('*') if p.is_file() and p.suffix in {'.py','.ps1','.cs'})
files.append(root/'scripts'/'save_continuation_checkpoint.py')
files.extend(root/'scripts'/name for name in ('inventory_existing_capabilities.py','verify_multi_monitor_ui.py','reconcile_authorized_followup.py','refresh_followup_documents.py'))
files.extend(root/'scripts'/name for name in ('run_public_claude_docs_ui.py','capture_public_docs_evidence.py'))
files.extend(root/'scripts'/name for name in ('run_live_mcp_echo_ui.py','verify_mcp_saved_raw_ui.py','finalize_mcp_acceptance.py'))
files.extend(root/'scripts'/name for name in ('current_acceptance_report.py','reconcile_acceptance.py','finalize_documents.py','sync_installed_source.ps1','run_live_claude_tools_ui.py','verify_native_history_idle_ui.py','close_test_dialog.py','verify_installed_candidate_source.py'))
files.extend(p for p in (root/'tools'/'claude-session-sdk').glob('*') if p.is_file() and p.suffix in {'.mjs','.json','.yaml'})
files.extend((root/'scripts'/name) for name in ('Launcher.cs','run_tests.py','package_source.py','ui_driver.py','run_ui_tests.py','update_acceptance_report.py','run_codex_write_acceptance.py','copy_node_dependencies.py','run_live_codex_ui.py','run_live_collaboration_ui.py','verify_live_diff_ui.py','verify_desktop_launch.ps1'))
files.extend(p for p in (root/'evidence').rglob('*') if p.is_file() and p.suffix in {'.json','.jsonl','.md','.txt'} and p.name!='source-manifest.json')
files.extend(p for p in (root/'evidence').rglob('*.png') if p.is_file() and any(name in str(p.parent) for name in ('ui-acceptance','ui-widget-regression','live-codex-ui','live-collaboration-ui','live-claude-tools-ui','native-history-idle-ui','multi-monitor-ui','public-claude-docs-ui','live-mcp-echo-ui','dot-offline-ui','session-labels-ui','exe-claude-primary-review')))
files=sorted(set(files))
assert all(p.suffix.lower() != '.exe' for p in files)
manifest={'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'release':'1.0.0-candidate','compiled_executables_included':False,'final_status':'BLOCKED','dependencies':'PySide6 6.11.2 and Node SDK node_modules are not included in the source archive; existing Python/Node plus pinned dependency manifests are required. See UI execution history and remaining retest boundary.','files':[{'path':p.relative_to(root).as_posix(),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in files]}
mp=root/'evidence'/'source-manifest.json';mp.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
archive=root/'AI-Collaboration-Workspace-source-audited.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
 for p in files+[mp]:z.write(p,p.relative_to(root).as_posix())
with zipfile.ZipFile(archive) as z:
 assert z.testzip() is None
 assert z.read('docs/PRD.md')==(root/'docs'/'PRD.md').read_bytes()
print(json.dumps({'archive':str(archive),'bytes':archive.stat().st_size,'file_count':len(files)+1,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest()},indent=2))
