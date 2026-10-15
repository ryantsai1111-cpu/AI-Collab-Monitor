# Scripts

Updated 2026-10-09. Run selected entry points, not every script in this directory.

## Current maintenance entry points

| Entry | Purpose |
| --- | --- |
| `python scripts/run_tests.py` | All top-level test modules, one subprocess each, offline opt-ins disabled |
| `python scripts/run_tests.py --list` | Inspect the selected suite without running |
| `python scripts/run_tests.py test_core test_agent_instances` | Selected modules only |
| `python scripts/run_ui_tests.py` | Current UI suites, isolated QApplication per module |
| `python scripts/run_ui_tests.py --widgets-only` | Current test_ui_refresh suite |
| `python scripts/package_source.py --list` | Review the source package allowlist |
| `python scripts/package_source.py` | New timestamped source ZIP and embedded hashes; no overwrite |
| `python scripts/run_dot_offline_tests.py` | Existing isolated Dot tests |
| `python scripts/run_session_labels_ui.py` | Existing visible fixture session-label test |

Test logs live in a new timestamped `evidence/test-runs/` directory. Failures, missing prerequisites and per-module timeouts remain failures. A passing unittest module can still contain skipped tests; consult its log. Full discovery does not include `tests/legacy_ui/`. `--visible` shows fixture windows only and does not enable live inference.

The source ZIP excludes vendor, node_modules, local config, test data, raw logs and acceptance evidence. It includes application PNG assets, source, docs, tests, dependency manifests and the pinned Dot license. It is not a bundled executable or a live-accepted release.

## Runtime dependency

`dot_cli_entry.py` is called by `acw/adapters/dot.py`. Keep it and `tools/dot-source-manifest.json` with the unchanged pinned source. It must not be treated as an obsolete acceptance script.

## Historical deployment and live verification

`Launcher.cs`, `launcher.manifest`, `build_launcher.ps1`, `installer_policy.py`, `package_context.py`, `launch_observation.py`, `ascii_json_helpers.ps1`, `launch_validation_helpers.ps1`, `read_launch_snapshot.py`, `verify_desktop_launch.ps1` and `run_exe_source_tests.py` preserve the earlier EXE work and source-hardening tests. The missing `install.ps1` means this is not a complete current installer.

`sync_installed_source.ps1`, `copy_node_dependencies.py` and `verify_installed_candidate_source.py` target the earlier installed layout; do not use them as the current checkout update procedure.

`run_live_*.py`, `run_codex_write_acceptance.py`, `run_exe_*review_ui.py`, `run_public_claude_docs_ui.py` and related capture/verify scripts use specific historical paths or actual backends. Their presence and earlier authorization do not authorize new live calls. `open_dot_handoff.py` opens a disconnected real UI, but its subsequent human actions can use credentials.

## Obsolete one-off transformations

The 17 obsolete one-off report/source transformations were removed from this directory on 2026-10-09 after checking application and test references. They remain in an ignored local recovery backup under `evidence/cleanup/`, outside runtime imports and source packaging. See [cleanup record](../docs/CLEANUP-REVIEW.md). Do not run the backed-up scripts against the current checkout.
