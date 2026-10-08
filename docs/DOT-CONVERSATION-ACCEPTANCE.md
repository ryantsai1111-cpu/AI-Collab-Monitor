# Dot conversation candidate: cloud acceptance

Date: 2026-10-07. Scope: load the selected existing dot conversation on Connect; keep Workspace task handoffs separate.

## Passed

- Python 3.12.14 / PySide6 6.11.2 in the assistant's Linux cloud workspace
- Final supported regression: **401 tests, 375 passed, 26 skipped, exit 0**, 63.381 seconds
- New root/room/UI suite includes **45 tests**; final combined regression includes the same tests
- Stress: 10,032 stored fixture messages; ordinary display bounded to 200 cards; final measured initialization/render **1.411 seconds** on this cloud machine (not a Windows performance guarantee)
- Repeated snapshot read: 100 requests, native-ID dedup maintained
- Task switching: 50 pairs / 100 selections, no additional transport and no conversation loss
- No-project/task connect/read/send, initial consent rejection, wrong/missing/changed room, failed reads, uncertain send receipts, root/task isolation, thread-local cleanup, duplicate root operations, draft isolation, empty loaded page, persistent error text, and root handoff exclusion
- Independent review plus offline layout checks at 1530x920, 1280x720, 760x600 and 640x420; no horizontal content overflow. Minimum size leaves a small transcript viewport
- All changed Python files parse; pinned third-party source hashes unchanged
- Actual pinned read/send functions exercised only against fake callbacks with network/auth/process access forbidden

## Skipped and pre-existing blockers

The supported run excludes three old test modules. A separate full-discovery attempt, before the final empty-page test was added, ran 432 tests with 3 failures, 1 setup error, and 26 skips:

- Two EXE-hardening assertions require trusted PowerShell, absent on this Linux host
- Codex schema setup lacks evidence/codex-schema/v2/ItemStartedNotification.json in this cloud source snapshot
- The pre-existing first-run test expects require_task while the role-specific UI uses show_sessions

The remaining changed-suite failures from that earlier attempt were corrected and retested in the final supported run. Skips include platform-only and opt-in live tests. Do not describe this as a full-suite pass.

## Test expectation changes

- Dot Connect now includes list + first-page read after one bounded confirmation
- Dot draft and displayed history follow the selected identity, not the Workspace task
- Root reply assertions use the dedicated root projection; task queries remain separate
- The wrapper requires an expected existing room
- Dot menus expose task association / older messages instead of native session controls
- Stable snapshots are labelled as new messages without claiming a native completion signal

## Not established by cloud tests

- Actual account connectivity, full native conversation availability, or Windows-native execution of this candidate
- Live three-agent collaboration
- The pre-existing automatic-verdict correlation gap in task-scoped shared-root polling remains unresolved; no unattended collaboration acceptance is implied

All measurements use synthetic fixtures. No real messages, credentials, or auth files were loaded. Local deployment and native acceptance must be recorded separately after hash-guarded application.
