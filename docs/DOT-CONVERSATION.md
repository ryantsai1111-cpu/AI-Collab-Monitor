# dot: existing ongoing conversation

## Product and connector

A dot is a named, always-on assistant with continuing context and its own cloud computer. Workspace's unofficial messaging connector exposes a subset of that product, not a Codex-style session server.

Official sources reviewed on 2026-10-07:
- https://openai.com/index/introducing-dots/
- https://help.openai.com/en/articles/20001530-getting-started-with-your-dot

## User experience

Selecting the approved dot and pressing Connect asks for one bounded confirmation covering identity verification and the first existing-conversation page. It does not need a Workspace project/task or Resume. The initial page contains at most 32 messages; the menu provides older-page loading. Cached history is incomplete unless all pages have actually been retrieved.

The main panel displays the continuing conversation. Native session creation/resume/rename selectors, model/effort selectors and server Stop are not shown for dot. Workspace task association is available separately under the handoff menu. Disconnect ends this connector's access; it does not pause the native dot's other work.

The initial rendering window is at most 200 cached messages. Each explicit older-page action expands the visible window by 32. This limits ordinary startup rendering without discarding cached records. A successful read timestamp describes retrieval, not the assistant's work/completion status.

## Identity and storage boundaries

- Dot ID, messaging room ID and active task IDs are distinct concepts.
- The connector verifies an existing room and retains its pin. Missing or changed rooms fail closed; the guarded read/send wrapper cannot create a room.
- The existing pinned client source and source-manifest verification remain unchanged. Wrapper guards validate the exact resolved identity and room before the existing read/send functions, and include provenance in responses.
- Manual conversation connect/read/send uses a thread-local root context with null task/project. It must not rewrite Workspace task-session mappings.
- Root snapshots/receipts retain room provenance. Unproven legacy cache is not displayed as the verified current room; it is preserved, not deleted.
- Same-identity native messages are deduplicated for display. Verified root copies take precedence over task-scoped copies. Original task records/handoff references remain intact.
- Generic task message queries and orchestration remain task-scoped. Root cards do not expose task Forward actions. Explicit local task binding is required for task handoffs.
- Selecting another identity clears old visible messages and isolates drafts.

## Approval and failure behavior

Connect+first-page consent covers just those actions. Separate sends/refreshes retain explicit consent. Existing consented post-send checks are time/request bounded; stable snapshots are not a native completion signal. Manual reads/sends are disabled during an active collaboration run and follow-up reading stops when orchestration starts.

A failed history read retains prior cache and surfaces the error. Missing send receipts are uncertain outcomes; automatic resend is forbidden. None of these functions execute at app startup. No credential files are read by the new code or tests.

## Acceptance boundary

Cloud fixture tests cannot establish actual account/session reachability on Windows. Runtime loading still requires a safely reopened application and the user's connector confirmation.

The pre-existing shared-root automatic-verdict correlation gap is not solved by this UI change: an unrelated new root reply may be attributed by the older orchestration polling route. Do not claim live three-agent acceptance or unattended collaboration safety from these tests.
