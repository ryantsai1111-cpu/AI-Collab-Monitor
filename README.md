# AI Collaboration Workspace

Windows desktop workspace for independent Claude, dot, and Codex panels, local task history, and explicit handoffs.

**Release status: acceptance candidate; Final is not certified.** An official embeddable dot message bridge has not been established. The dot panel is an honest blocked integration, not a simulated agent. See [Final Acceptance Report](evidence/FINAL-ACCEPTANCE-REPORT.md) for the measured outcome.

## Run

The installed **AI Collaboration Workspace.exe** launch was rejected by Windows security and its installed file is now absent. The existing shortcuts therefore do not have verified working startup. No restore/rebuild/retry or security change has been performed. See [the exact blocker](evidence/EXE-SECURITY-BLOCKER.md).

From the existing Python runtime: `python run.py`. For an isolated dataset: `python run.py --data-dir C:\path\to\isolated-data`.

`install.ps1` installs this new application to `%LOCALAPPDATA%\AI-Collaboration-Workspace\app`, creates Desktop and Start Menu shortcuts, and leaves the original Desktop Monitor untouched. An existing install is never silently replaced. App data is under `%LOCALAPPDATA%\AI-Collaboration-Workspace\data`.

Startup restores local project/task/history but does not start backends, reconnect sessions, or resend prompts. Press Connect on each supported panel. Use an explicitly selected project and task before sending.

## Documents and verification

- [Original PRD](docs/PRD.md) and [requirement tracker](docs/REQUIREMENTS.md)
- [Architecture](docs/ARCHITECTURE.md), [adapters](docs/ADAPTERS.md), [security](docs/SECURITY.md)
- [User guide](docs/USER_GUIDE.md), [troubleshooting](docs/TROUBLESHOOTING.md)
- [Backend discovery](evidence/backend-discovery.md), [Final acceptance](evidence/FINAL-ACCEPTANCE-REPORT.md)

`python scripts/run_tests.py` measured129PASS/0FAIL/2opt-in skips (131discovered). `python scripts/run_ui_tests.py --visible` measured50PASS in real Qt with isolated Core/SQLite/Git and explicit synthetic transports; the last changed widget paths passed25focused cases with `--widgets-only`. Real official Claude/Codex visible handoff/resume/stream/Stop passed16checks, official readonly native history5checks. Actual Codex human-approved write/diff/test passed. One subsequently expressly authorized Claude run passed7 actual human-approved file/command/UI checks. Physical two-monitor Qt checks passed10 after fixing high-DPI clipping; previous canceled/failed attempts are preserved. Test doubles do not certify real backends. Current tracker:593PASS/0FAIL/56BLOCKED/4UNSUPPORTED/0PENDING, Final not accepted.

The official Claude CLI and Codex app-server keep their own login and permission state. This application never reads credentials and never automatically approves tool requests. Tool output can contain sensitive text: redaction is applied before persistence, and raw-event safety exceptions are recorded.

## Official session helper dependency

Native Claude session browsing uses the pinned public Agent SDK in `tools/claude-session-sdk` and the existing Node runtime. Its manifest/lockfile are included in source; `node_modules` and PySide6 `vendor` are excluded from the source ZIP. The isolated real helper tests passed with SDK 0.3.289. The SDK's optional standalone CLI binary is not used; model interaction retains the pre-existing Claude Code executable. See `evidence/claude-session-sdk-install.json` for the bounded package installation outcome.

Per-user installation on RYAN-PC is complete: Desktop and Start Menu shortcuts were verified against the installed executable. Actual compiled EXE launch was attempted and rejected by Windows security; do not disable or exclude it. Python/Qt UI testing does not certify EXE startup. Current23-case visible UI suite passed. Installed official SDK session/list/history checks pass; see `evidence/installed-sdk-verification.json`.

Human approval remains explicit. Pending requests now have a fixed Review reminder above the event viewport, so newer activity cannot hide the action. See `evidence/live-codex-ui` and `evidence/EXE-SECURITY-BLOCKER.md`.

Authorized MCP follow-up: actual official Claude `mcp__acw_acceptance__echo`, fixed input/result, one human native approval, exact tool/result/status in actual Workspace UI,11 checks PASS; saved Raw UI checks overlap. No persistent config/service/port, private connector, automatic allow rule or permission-mode change. See evidence/live-mcp-echo-ui/result.json. Earlier Claude Docs public-document scope attempt remains historical BLOCKED.


## Current approved Dot integration update

The earlier official-bridge blocker remains historical context. An explicitly approved, pinned unofficial Dot adapter and manual UI are now implemented and offline-tested. See [Dot activation and boundaries](docs/DOT-UNOFFICIAL.md). Only the human may trigger live credential-bearing list/connect/read/send. No live Dot PASS or Final acceptance is claimed. EXE work remains deferred.
## Source-only EXE follow-up

The G8 second review authorizes source changes/offline tests only. The revised
installer, build and EXE launch-verification scripts have **not been executed**.
Their default modes are read-only plans; execution switches are not approval.
Existing app/partial/quarantine states are not auto-resumed. See
`docs/EXE-SOURCE-HARDENING.md` and the append-only evidence for the deployment,
physical-path, binary-provenance and acceptance limits. Existing binary/data and
live windows remain unchanged; no antivirus exclusions or vendor uploads occurred.

The second source-only remediation records complete eligible-file inventories,
explicit exclusions and reparse failures; actual bundled dependency preparation
remains blocked by linked/unknown/unreadable resources. Package identity is an
additional read-only signal, not full virtualization coverage. Launch argv uses
bounded ASCII JSON stdin; production data access remains UNKNOWN. See the
second-draft boundaries and manual INCOMPLETE rollback plan in
`docs/EXE-SOURCE-HARDENING.md`. No compilation, deployment or EXE launch is implied.
