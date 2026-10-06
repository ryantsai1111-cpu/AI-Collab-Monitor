from pathlib import Path
p=Path('scripts/package_source.py');s=p.read_text(encoding='utf-8-sig').replace("'package_source.py','ui_driver.py'", "'package_source.py','ui_driver.py','run_ui_tests.py'");p.write_text(s,encoding='utf-8')
p=Path('evidence/UI-EXECUTION-BLOCKERS.md');s=p.read_text(encoding='utf-8-sig');s += '''

## Smallest concrete permission request (prepared, NOT executed)

One-time command, working directory `C:\\Users\\ryant\\Documents\\Codex\\2026-10-05\\task-2`:

```powershell
& 'C:\\Users\\ryant\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\python\\python.exe' scripts\\run_ui_tests.py --visible
```

Target executable: existing Python 3.12.14 at the path above. Script: `scripts/run_ui_tests.py`, source available for review. Dependency: existing `vendor/PySide6` 6.11.2. No download/install/relocation is proposed.

Requested execution scope: **one invocation as the normal interactive `ryant` user, outside the restrictive tool token**, not administrator/UAC, no ACL/security-policy/PATH change, no permanent exception. It opens only this app's synthetic test windows, drives Qt widgets through QTest, captures only those test windows, writes temporary `acw-ui-isolated-*` datasets and `evidence/ui-acceptance/`, then exits. A 180-second watchdog terminates only this test process if it hangs. No official backend, network, real repository, existing session, authentication flow or third-party communication occurs.

Risk: the one Python process runs with the normal account's filesystem rights and will show temporary test windows/change focus. Its reviewed test code is scoped to temporary data and evidence. This is an explicit, narrow exception requiring user approval because auto-review rejected a similar execution scope; it must not be treated as already authorized. Passing this runner verifies widget interactions only. Separate external desktop/launcher and real backend UI acceptance still remain.

## Exact delivery locations and launch status

- Source and candidate executable: `C:\\Users\\ryant\\Documents\\Codex\\2026-10-05\\task-2`.
- `AI Collaboration Workspace.exe`: compilation PASS; **never launched or double-clicked** during this task.
- `python run.py --data-dir tests/ui-manual-data`: previously started under an approved invocation, no startup traceback; closed afterward. No interaction/visual acceptance claimed.
- Desktop and Start Menu `AI Collaboration Workspace.lnk`: **not created**, existence checked false.
- Intended install: `%LOCALAPPDATA%\\AI-Collaboration-Workspace\\app`; intended production data: `%LOCALAPPDATA%\\AI-Collaboration-Workspace\\data`. The application root does not yet exist (read-only existence check false).
- Actual test-only data: `tests/ui-manual-data`, isolated Claude/Codex repos under `tests/sandbox-*`, and fresh temporary unit test directories. Production data was never used.
- Reviewed per-user installer: `install.ps1`; **not executed**, separate from the proposed one-time UI test.
''';p.write_text(s,encoding='utf-8')
