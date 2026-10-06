# Tests

All suites are offline: temporary data directories, in-memory or mocked adapters, no credentials, no network.

## Running (PowerShell, from the repo root)

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'; $env:PYTHONPATH = 'vendor;tests'
python -m unittest tests.test_ui_refresh
```

Run one module at a time. `vendor` on `PYTHONPATH` supplies PySide6 6.11.2; drop it if PySide6 is installed with pip.

## Baseline

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
