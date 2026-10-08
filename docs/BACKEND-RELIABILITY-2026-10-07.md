# Backend reliability candidate — 2026-10-07

Status: scoped cloud implementation and hash-frozen integration validation completed. Not deployed on Ryan-PC, not a live three-agent acceptance report, not published to GitHub.

## Changes

- Per-agent reentrant operation reservations prevent concurrent send/create/resume and mutable task/project selection races. Adapter generations ignore callbacks from replaced adapters; a completed old send cannot claim a new adapter's request ownership.
- Outgoing requests are recorded before dispatch. Failures after invoking the adapter are `delivery_unknown`, never automatically resent. Handoff failures proven to occur before dispatch remain `failed`. Restart changes in-flight delivery records to uncertain, without replay.
- Dot native snapshots belong to the verified root conversation. Only a validated, immutable application-level reply can be copied into task evidence. Native IDs and room identity remain required; task switching does not re-label unrelated native messages.
- Orchestration uses run/step/nonce markers, exact ordered outgoing-receipt matching, one complete reply, frozen bindings, explicit approval handling and bounded waits. These are application correlation checks, not a native completion guarantee or cryptographic authentication.
- Stop requests require the same run, local request, adapter, session and an adapter-owned operation token. Codex tokens bind the actual accepted native turn; Claude tokens are explicitly local process/session/send-generation guards. Unsupported guarded cancellation is refused rather than falling back to a generic Stop. Old callbacks and expired calls cannot advance a new run. Maximum rounds without final approval pause the run instead of reporting success.
- SQLite native-message lookup uses the dedicated JSON-expression index explicitly when supported; diagnostics report a scoped-scan fallback on older SQLite. Repeated unchanged snapshots do not duplicate message/raw records.
- Managed database sidecars and raw-log files reject static symlinks, reparse points, hard links and non-regular files; guarded writes coordinate with close. This does not claim elimination of all filesystem ancestor or SQLite-open TOCTOU races.
- Replacing an adapter interrupts its old stream and discards the unpersisted raw tail, preventing credential policies from mixing across generations.
- Visible stream fragments are accumulated before redaction. Streaming raw fragments are omitted from persistent audit records. Local-provider credential redaction is applied to the accumulated visible text as well as complete-line persistence.
- Null or missing native text remains an empty stored string with `no_text` metadata. A UI-only notice explains that non-text display is unsupported. It does not fabricate agent content or turn attachment metadata into a reply.

## Intentional test-contract changes

- The existing Dot snapshot test now checks root-conversation rows separately from the originating task's outgoing message. Uncorrelated native replies must not be inserted into task history.
- The existing disconnected-handoff test retains its `failed` expectation because adapter dispatch never occurred. New tests separately require `delivery_unknown` after dispatch.
- Windows symlink fixtures skip only the specific unsupported privilege error rather than altering security settings. A skip is not native-platform verification.

- The first-run guidance fixture checks the role-specific conversation/task picker and its explanatory error, while retaining the unsent draft and zero-send assertions. The Claude stderr fixture binds its synthetic reader to the current process; obsolete-process output is separately rejected.

## Final scoped cloud verification

- Hash-frozen run: 542 tests, 516 passed, 26 skipped, zero failures/errors; exit code 0, 73.52 seconds. All source/test SHA-256 hashes were unchanged across the run.
- Two modules remain outside this supported aggregate: `test_exe_source_hardening` requires trusted Windows PowerShell unavailable in the cloud; `test_codex_adapter` requires the missing `evidence/codex-schema/v2/ItemStartedNotification.json` fixture. A separate legacy check reproduced these blockers. This is not a full-suite pass.
- Root render fixture: 10,032 cached messages, 200 rendered cards, 1.258 seconds.
- Local credential-stream stress: 300 completed streams plus two recovered interruptions; 15,131 events; no synthetic canary leakage in inspected UI, database/WAL or raw logs, and no deadlocks.
- Core reliability: 24 deterministic cases plus five repeated runs (120 executions). Real-adapter cancellation/dispatch: 15 cases plus ten repeated runs (150 executions).
- Independent review re-ran real Codex replacement-turn cancellation, Stop during already-entered preparation, and real Claude buffered-reader shutdown. The latter completed in 0.002 seconds without old diagnostics leaking onto the new task.
- Evidence: `evidence/backend-reliability/cloud-acceptance.json` and accompanying cloud logs. Synthetic tests only; no account or production acceptance implied.

## Known acceptance limits

The bounded root-conversation patch already installed on Ryan-PC displayed 31 current-chat cards, then failed with `NOT NULL constraint failed: messages.content`. Nullable content reproduces that failure in synthetic tests, but the exact live payload shape has not been inspected. A separate four-file hotfix candidate passed 410 supported cloud tests (384 passed, 26 skipped); excluded legacy modules and opt-in live tests are not a full-suite pass.

Ryan-PC was verified offline at 14:14 UTC. No newer backend candidate or nullable-message fix has been applied locally. Local diagnostics, Windows tests, full-page UI read, interrupted/repeated flows and live backend collaboration remain pending.

No credential files were read for cloud tests. No live model requests, agent messages, remote repo writes, commits, pushes, security changes or software installations are part of this cloud validation.
