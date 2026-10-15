# Tests

The current runner selects offline cases with temporary data and mocked adapters. Explicit native opt-in tests remain in some modules; the runner removes their live enable flags from its child environment.

## Running (PowerShell, from the repo root)

```powershell
python scripts/run_tests.py --list
python scripts/run_tests.py
python scripts/run_ui_tests.py
python scripts/run_tests.py test_core test_agent_instances
```

The runner uses a separate Python process per top-level module to isolate Qt state, adds `vendor` and `tests` to `PYTHONPATH`, and defaults to `QT_QPA_PLATFORM=offscreen`. Logs and a JSON result are stored in a new timestamped `evidence/test-runs/` directory. Module failures and timeouts return a nonzero exit code; skips are preserved in logs. `--timeout` sets the per-module limit (180 seconds by default). `tests/legacy_ui/` is not included. Full discovery can still expose missing fixtures or Windows prerequisites listed below; the runner does not hide them.

For an individual unittest case, use `$env:QT_QPA_PLATFORM='offscreen'; $env:PYTHONPATH='vendor;tests'` followed by `python -m unittest test_ui_refresh`.

## Baseline

### Hermes send recovery — 2026-10-11

- Latest results across 11 isolated modules: **254 passed, one pre-existing Dot identifier fixture skip**. Initial report: `evidence/test-runs/20261011T012740617174Z/result.json`. That run exposed a missing-adapter UI initialization regression; after fixing it, the two affected modules passed in `evidence/test-runs/20261011T012941905042Z/result.json`. The final 17 Local UI cases passed in `evidence/test-runs/20261011T012931183340Z/result.json`.
- Actual Hermes adapter fixtures verify explicit legacy-session detection, exactly one fresh send from the labeled button, unchanged old task/session/history, persistent send errors and drafts across refresh/context changes, and refusal to replace unknown, corrupt, mismatched or missing native sessions. Rendering, connecting and refreshing do not migrate history or start inference.
- Inspected 1100×800 offscreen renders: `evidence/hermes/send-legacy.png` and `send-error.png`. Changed Python files pass AST parsing; `git diff --check` passes. This follow-up used temporary data and mocked CLI processes; no user prompt was resent and the running application was not restarted.

### Hermes replacement — 2026-10-11

- Final targeted run: **268 tests passed, zero skipped, across 13 isolated modules**. Report: `evidence/test-runs/20261011T010309992255Z/result.json`. Includes Hermes adapter/Core, legacy settings compatibility, startup factory, independent instances, UI, workbench, Monitor, orchestration correlation, handoff and approval boundaries.
- Hermes-specific coverage has 20 adapter and 13 Core cases: UTF-8 query files, literal argv, optional provider/model, exact native resume behind a stable alias, context-compaction ID changes, saved metadata recovery, malformed/nonzero results, cancellation ownership, watchdog expiry, helper-thread startup failures and process cleanup. A real Windows synthetic parent/descendant cancellation test confirms an unrelated control process survives.
- Real installed Hermes smoke: exact `ACW_HERMES_OK` response; a fresh adapter resumed the saved native ID and recalled the prior marker. All three inference turns used isolated temporary project directories, made zero tool calls and reported no errors. Evidence: `evidence/hermes/live-smoke.json` and `live-resume.json`. These are transport/resume checks, not live coding or tool-approval acceptance.
- The real `run.main` offscreen startup/close passed with subprocess calls forbidden, a temporary data directory and synthetic legacy settings. Hermes remained disconnected, stale seed/executable/model values were ignored and saved legacy settings were preserved. Evidence: `evidence/hermes/startup-smoke.json`.
- An 800×660 settings render was inspected with Windows fonts; no horizontal/vertical overflow or clipped controls. Evidence: `evidence/hermes/settings-20261011T005808024226Z.png`. Python AST checks and `git diff --check` pass.
- Full discovery report `evidence/test-runs/20261011T005916318101Z/result.json` ran 40 modules / 700 tests with 23 skips; three modules failed at that point. The Codex discovery factory-import failure was fixed and passed the final targeted run. Two pre-existing missing prerequisites remain: `evidence/codex-schema/v2/ItemStartedNotification.json` for `test_codex_adapter`, and `install.ps1` for `test_exe_source_hardening`. They were not fabricated or skipped to claim a full-suite pass.

### Compact Agent sidebar — 2026-10-10

- `test_workbench test_ui_refresh test_local_ui test_session_labels test_agent_instances test_collaboration_monitor test_dot_conversation`: **206 passed, zero skipped**, in seven isolated processes. Report: `evidence/test-runs/20261010T115535646784Z/result.json`.
- Five additional workbench cases verify one visible Agent scope, advanced session actions and capability/Monitor gates, project details scoped to the correct Agent, view-menu draft/binding preservation, and directly opening the selected Local instance's settings without connecting.
- Focus, parallel and narrow screenshots were regenerated with `tests/render_workbench.py` and inspected. Changed Python files pass syntax compilation and `git diff --check` passes. All data and adapters are offline fixtures; the user's existing process and data were untouched.

### Agent-centered interaction logic — 2026-10-09

- Latest completed results per module: **452 tests passed, zero skipped, across 23 isolated modules**. Aggregate with exact source logs: `evidence/monitor/logic-regression.json`. This combines the `20261009T150236342635Z`, `20261009T150826431890Z`, `20261009T151411007832Z` and `20261009T151813059250Z` runner reports, taking only the latest result for each module. Earlier scope and focus assertions exposed by the new behavior were corrected; the original reports retain those failures.
- Coverage includes independent Project/Session selection, unrelated record navigation during work, participant-only collaboration locks, cross-project and same-provider collaboration, saved-session history/draft restoration, failed-send attachment preservation, backend-family session ownership, asynchronous draft/scroll protection, independent desktop-session opens and stopping dispatch before shutdown.
- The actual `run.main` entry point passes an isolated offscreen startup/close smoke check (`evidence/monitor/startup-smoke.json`). An injected UI initialization failure also releases the Store and process lock while preserving the exception (`evidence/monitor/startup-failure-smoke.json`). Backend process/network calls were forbidden; the running user application was not restarted.
- Focus (1500×1000), parallel (1800×1000), and narrow (650×900) renders from `tests/render_workbench.py` were inspected. Changed Python sources pass syntax compilation; `git diff --check` passes.
- This is targeted offline verification, not full discovery or live native Desktop acceptance. Historical prerequisite failures below remain separate from this scope.

### Main Monitor workbench — 2026-10-09

- Final regression: `test_workbench test_ui_refresh test_local_ui test_maintenance` passed **86 tests** (7 + 67 + 5 + 7) in isolated processes. Report: `evidence/test-runs/20261009T123556673097Z/result.json`.
- New coverage checks the default hacker theme and Focus layout, focus/parallel switching without replacing panels or losing drafts/bindings, per-instance rail navigation, read-only overview boundaries, narrow layouts, local snapshot refresh without backend calls, and layout persistence.
- `tests/render_workbench.py` produced inspected Focus (1500×1000), parallel (1800×1000), and narrow (650×900) Qt renders in `evidence/monitor/workbench-*.png`. These use synthetic conversations and disconnected adapters.
- The actual `run.main` entry point exited successfully using isolated temporary data and offscreen Qt, with backend process/network calls forbidden. Its observed title, Focus layout, Workspace view, hacker theme and disconnected adapters are recorded in `evidence/monitor/startup-smoke.json`.
- This verifies the main UI and startup, not live inference or complete native Desktop synchronization. The user's running application was not restarted.

### Post-cleanup regression — 2026-10-09

After moving 134 obsolete files/caches into a local recovery backup outside runtime and packaging paths, `test_maintenance test_first_run test_agent_instances test_local_ui test_ui_refresh test_session_labels test_dot test_collaboration_monitor` passed **149 tests** in eight isolated processes. Logs: `evidence/test-runs/20261009T091631247114Z/`. Bytecode writing was disabled for this run so verification did not recreate the removed caches. Entry-point help, the existing shortcut target, preserved-file hashes, source packaging and current document links also passed. This does not claim live backend or full-suite acceptance.

### Repository maintenance — 2026-10-09

- The new runner executed `test_maintenance test_agent_instances test_local_ui test_ui_refresh test_session_labels`: **104 tests passed** across five isolated processes (7 + 12 + 5 + 67 + 13).
- Maintenance coverage includes package exclusion of machine data/runtime/credentials, preservation of application assets/license, manifest hash verification, refusing overwrite, missing-source failure before ZIP creation, disabling inherited live opt-ins, per-module isolation, truthful failure/timeout reporting and rejection of unknown test modules.
- `run_ui_tests.py --list` resolves the current UI modules instead of importing the old `legacy_ui` suite. A real source ZIP was generated and checked; no runtime dependency was upgraded or installed.
- This is a targeted maintenance regression, not a full-suite or live-backend acceptance.

### Independent agent instances — 2026-10-09

- `test_agent_instances test_core test_orchestrator test_orchestrator_correlation test_orchestrator_handoff_safety test_orchestration_approval_boundary test_local_core test_local_llm test_adapter_stream_safety test_core_backend_reliability test_adapter_cancel_ownership`: **202 passed**. Includes 12 new instance tests covering disconnected creation, settings and session isolation, registry restoration without schema changes, concurrent native-session reservations, duplicate-send rejection, independent project selection, two-Claude delegation/review, panel drafts and separate Local endpoint controls.
- `test_local_ui test_ui_refresh test_session_labels`: **85 passed**. Legacy provider labels remain compatible; custom instances use their own names.
- `test_agent_instances test_collaboration_monitor test_agent_contexts`: **57 passed** at the earlier UI checkpoint, before two additional instance tests were added and covered by the final 202-test run.
- `python -m render_monitor --same-provider`: wide (1500×1060) and narrow (650×960) renders inspected at `evidence/monitor/instances-*.png`. Participating instances appear first; narrow Monitor content uses one column.
- These groups overlap and are not a full-suite or live-backend acceptance. All calls use temporary data and offline adapters. No live inference, credential access, Desktop patch or database migration was performed.
- Run the two final test groups in separate Python processes. Combining earlier Qt fixtures with `test_local_ui` in the same process stalled in its class-level `QApplication.setStyle('Fusion')`; the split runs above completed. This test-harness ordering issue remains unresolved.

### Flexible lead follow-up — 2026-10-09

- `test_collaboration_monitor test_orchestrator test_orchestrator_correlation test_orchestrator_handoff_safety test_orchestration_approval_boundary`: **105 passed**. Includes both leads across direct / G8毛 relay modes and all three Local LLM choices, reverse correction rounds, chosen-lead completion, prompt recipients and Monitor labels.
- `test_ui_refresh test_local_ui test_agent_contexts`: 90 passed; one old assertion required Claude to carry a permanent reviewer label and Codex an implementer label. Updated that assertion to require both to display the neutral collaboration label, as requested by the user; the changed test passed in a targeted rerun. No product code changed after this UI run.
- `python -m render_monitor --lead codex`: wide and narrow Codex-led screenshots inspected under `evidence/monitor/codex-lead-*.png`.
- Changed Python files pass `py_compile`; `git diff --check` passes. Offline verification only.

### Scoped collaboration / Monitor verification — 2026-10-09

Windows, vendored PySide6, `QT_QPA_PLATFORM=offscreen`; temporary data and offline adapters only.

| Scope | Result |
| --- | --- |
| `test_collaboration_monitor` | 22 passed: direct delegation, Claude-only completion, correction rounds, total time/step budgets, delayed dispatch, approval holds, optional roles, read-only Monitor, independent contexts, responsive layout and timer shutdown |
| `test_collaboration_monitor test_ui_refresh test_agent_contexts test_live_sync` | 110 passed at the UI verification checkpoint; the Monitor module then gained two additional cases, both covered by its final 22-test run |
| `test_orchestrator test_orchestrator_correlation test_orchestrator_handoff_safety test_orchestration_approval_boundary test_adapter_cancel_ownership test_adapter_stream_safety test_connect_reservation test_core_backend_reliability test_live_sync test_approvals test_local_ui test_dot_follow test_dot_conversation` | 210 passed in the final existing-code regression run |
| Syntax / patch checks | `py_compile` of changed Python implementation and new tests; `git diff --check`: passed |
| Visual check | `python -m render_monitor`: wide (1500×1060) and narrow (650×960) native Qt renders inspected; synthetic data with installed Windows fonts |

These scopes overlap; counts must not be added as unique tests. This is not full-suite or live-backend acceptance. Screenshots and logs are generated under ignored `evidence/monitor/`; reproduce with the tracked `tests/render_monitor.py`.

The existing relay tests now explicitly request `workflow='relay'` (and UI tests explicitly provide run consent), preserving their G8毛 safety assertions after the default changed to direct Claude/Codex collaboration.

The first UI regression exposed a live-sync timer that survived window close and read a closed Store. Window shutdown now stops all three timers; the corrected UI run passed. An initial quiet aggregate was interrupted while investigating its lack of output; the final verbose 210-test run completed successfully.

### Historical baseline

Measured 2026-10-06 on Windows 11, CPython 3.12.10, PySide6 6.11.2.

| Module | Result | Notes |
| --- | --- | --- |
| `test_ui_refresh` | 67 run, OK | Current UI suite |
| `test_offline_contracts` | 18 run, 2 errors | Both errors are `WinError 1314`: creating symlinks needs elevation or Developer Mode |
| `test_core` | 44 run, OK | |
| `test_dot` | 14 run, OK | |
| `test_security_review` | 11 run, OK | |
| `test_inspection` | 16 run, OK | |
| `test_claude` | 18 run, OK (1 skipped) | |
| `test_codex` | 24 run, OK (2 skipped) | |
| `test_recovery_process` | 2 run, OK | |
| `test_session_labels` | 11 run, OK | |
| `test_codex_adapter` | 6 run, 1 error | Needs `evidence/codex-schema/v2/*.json`, which was never added to the repo |
| `test_exe_source_hardening` | 23 run, 1 failure | Needs `install.ps1` at the repo root, which was never added to the repo |
| `test_dot_ui` | 12 run, 1 failure (1 skipped) | `test_startup_no_transport_and_truthful_controls` expects the pre-refresh English notice text |

## `legacy_ui/`

`test_ui.py` and `test_workspace_ui.py` (25 tests each) were written for the pre-refresh window. Against the
current UI `test_workspace_ui` ends with 4 failures and 14 errors, and `test_ui` does not finish within 300
seconds, so both are parked here and are not part of the baseline.
`test_ui_refresh.py` is the suite that covers the current window.

## History

Until 2026-10-06 the test sources existed only inside `tests.zip`, mixed with live run data (SQLite databases
and raw agent transcripts). The sources and `fixtures/` were extracted; the run data was not kept in the repo.
