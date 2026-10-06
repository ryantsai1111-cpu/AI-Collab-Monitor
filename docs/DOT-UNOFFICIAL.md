# Approved unofficial Dot integration — human activation pending

Source is pinned to `1413f7b61060eb582fd53a0210ef1a499d158fe0` from https://gitlab.com/aa22396584/chatgpt-dot-cli, version string0.2.2. The tag0.2.2 is a different revision and is not used. Runtime dependencies are empty; existing Python3.12 runs the unchanged project-local source. No pip/system installation, upstream MCP service, global Git trust exception or credential extraction is required. `tools/dot-source-manifest.json` hashes every imported upstream Python file plus provenance/license documents. The bounded entry checks them before loading the CLI.

## Local human handoff

Open the prepared isolated handoff window with the existing Python runtime: `pythonw scripts/open_dot_handoff.py` from the source directory. This launches a disconnected real adapter, not a fixture; it performs no authentication or CLI call until your explicit UI action. Close/reopen the Python Workspace to load updated source; no EXE operation is requested. Create/select a non-sensitive test task. All agents start disconnected. In the Dot pane:

1. Click **Select Dot...**. Read the consent dialog. Yes launches the CLI locally to list identifiers/names; it uses the existing Codex ChatGPT login and sends its token to `https://chatgpt.com/backend-api`. This is nonofficial. No password/token/code should be pasted into Workspace or chat.
2. Select **G8毛**, then click **Use G8毛** explicitly. Other targets are refused. The list endpoint returns Dot metadata (potentially previews) transiently inside the CLI; Workspace only exposes names/IDs and does not persist account-wide previews. No conversation-message endpoint has been called yet.
3. Click **Connect Dot**, and separately confirm. Connected requires the backend to return the exact selected native Dot identity with the expected name. It does not mean a new independent chat thread was created, and it does not automatically retrieve messages.
4. Click **Refresh** and separately confirm if you want to read the selected Dot's latest32 messages. **Older page** retrieves the preceding page using the native cursor. History/Raw afterwards read only sanitized local records. Do not read older pages if those contain private content you do not wish to store locally.
5. To test sending, enter only `ACW_DOT_ACCEPTANCE: Please reply exactly ACW_DOT_OK. Do not use tools or access files.` Click **Send**, inspect the selected target, then personally confirm. A send receipt is an acknowledgement, not an assistant reply. Wait and personally click **Refresh** to retrieve the reply. Repeated Refresh does not duplicate native message IDs; a receipt ID also deduplicates your outgoing message.
6. Disconnect/reconnect requires another explicit Connect confirmation. Switching tasks requires explicit Resume of the existing selected Dot identity when that task has no mapping. Resume is local mapping, not a network reconnect or independent chat creation.

Only the human may perform these live clicks. The development agent has not clicked them or launched the live CLI. The offline tests inject a clearly labeled fixture runner and prohibit the real launcher. Live list/read/send/reconnect/thread correctness remains **BLOCKED pending human-run evidence**.

## Capability and safety boundaries

**Unofficial integration** is always shown. Model/effort are **Managed by ChatGPT / dot**. True token streaming, server cancellation, attachments, tools and independent new chat sessions are **Unsupported**. Project/task/branch data is local metadata; Dot does not enter the repository. The mapping stores the native Dot ID; successful Connect records the native messaging-room ID if returned, without inventing a conversation ID.

Every list/connect/read/send consumes a separate one-use consent bound to action and selected target. Programmatic operations without that consent fail before CLI launch. This is an internal guard against accidental automation, not an OS security boundary. No auto-connect, background polling, post-send refresh, cross-agent relay, auth override, auto-login, shell command interpolation, process-tree kill or permission bypass exists. Native CLI network timeout/retry behavior remains unchanged (it may retry certain non-JSON403/429/503 responses once). Workspace does not automatically retry a failed send; avoid resending an uncertain receipt without inspecting history first.

The bounded launcher only permits list/messages/send, fixed selected IDs,32-message pages and literal text after `--`. It exposes no automation/email/computer/environment/private-tool commands. It uses isolated Python imports and explicit UTF-8. Credential handling stays in the unchanged CLI; stdout/stderr are secret-filtered before Workspace persistence. Raw events are sanitized snapshots, with native message IDs/timestamps and a marker that reads are not streaming. Hidden reasoning is omitted. Unknown sender membership is rendered as an event instead of fabricating an assistant.

Forward to Dot remains a human action with the existing handoff preview/source preservation plus separate Dot consent. Notes remain local until an explicit handoff. No automatic orchestration is enabled.

## Evidence

- `evidence/dot-offline/result.json`:14 offline adapter/Core/launcher tests PASS; no real CLI authentication.
- `evidence/dot-offline-ui/result.json`:11 visible Qt fixture tests PASS; screenshots explicitly show OFFLINE TEST.
- `evidence/unit-test-results.json` and `evidence/ui-acceptance/result.json`: existing general and50 visible UI regression results.
- `evidence/installed-source-sync.json`: hash-verified Python/docs/pinned-source sync only, with backups; no data/settings/EXE changes.

These prove implementation and offline behavior, not live Dot acceptance. Final remains BLOCKED, and EXE/security work is deferred.


## Selection fix (2026-10-05)

A read-only check of the original human handoff window found Connect Dot disabled, Select Dot enabled, Select Dot first notice, no saved agent.dot selection and completed Busy-to-Disconnected metadata operations. No backend error/session mapping was present. The old build did not retain selection-result callback exceptions, so the exact failed human selection value cannot be reconstructed. No live call, credential read, user-window click/close or data overwrite was performed to diagnose this.

The selection dialog now has an explicit **Use G8** confirmation, structured item data rather than formatted-string lookup, and a saved-selection message. Commit configures the native target, saves settings, refreshes capabilities and returns Disconnected so Connect becomes enabled; cancellation does not commit or connect. Name normalization is NFKC plus trim, retaining the G8 identity restriction. The corrected pinned transport contract allows periods/tildes after an initial alphanumeric; colons are not supported; path/query/fragment/control syntax remains rejected. Reconnect still validates the exact selected backend ID and approved name.

UI callback exceptions are now sanitized, stored as errors and retained across queued Busy/Disconnected/Error transitions. An offline regression reproduced the old disappearing-error behavior; first and second failed repair tests are preserved in `evidence/dot-selection-fix/`, followed by10PASS. An actual Qt modal confirmation test saves the fixture target and enables Connect without a second transport call. The GUI-thread check passed; no thread-cause claim is made for the human incident.13 offline adapter tests pass.

The active original window is not hot-patched or closed. `pythonw scripts/open_dot_handoff.py --selection-fix` opens an updated, disconnected window with **DOT SELECTION FIX** project and separate `tests/dot-human-handoff-selection-fix/data`. It does not read/copy old data or connect automatically. Only the human may click Select/Use/Connect and accept each credential-bearing action.


## Identifier contract correction — actual account fixture pending

The reported event `event-5c1b4ece96cf46c7adc2706c73027fa2` at `raw/dot.jsonl:446` was checked read-only, along with the same task metadata/state/error and saved selection. The rejected identifier was not recorded by that old build. No auth file, token, cookie, unrelated conversation, backend API or user-window click was accessed. An actual-account fixture cannot be reconstructed from an error that contains no identifier; the requested non-secret value remains a blocker.

The pinned `api.py` primary source has `_ID = [A-Za-z0-9][A-Za-z0-9._~-]{0,199}`. The earlier Workspace charset omitted legal tilde and incorrectly accepted colon. This source discrepancy is confirmed; it is not a claim that the unknown original value definitely contained tilde. Validation now matches that exact pinned contract and a test compares it to the source AST, without importing/running credential code. Non-string IDs are rejected without coercion. Values outside the transport contract are reported Unsupported rather than declared invalid backend identities. Dot names may be normalized; native IDs are never trimmed, decoded, encoded, rewritten, or replaced with room/thread IDs. Arguments remain a literal list with shell disabled.

API list response is an object with an `items` array; upstream `list_dots` returns its Dot objects and `cmd_list --json` emits a JSON array. Selection uses each node's native `id`, not `messaging_room_id` or `active_root_thread_id`. The fixture `tests/fixtures/g8-dot-contract-sample.json` explicitly describes SOURCE-CONTRACT SAMPLE ONLY; it is not real account data. Visible Qt tests execute parse, real confirmation, save, close/reload and Connect enablement, without clicking Connect or any live operation. Current offline results:14 adapter tests PASS,11 visible UI tests PASS,1 actual-ID UI case BLOCKED/SKIPPED until a real non-secret identifier is provided. General suite143PASS/2 existing opt-in skips. No native Dot PASS is promoted.

On a future **human-triggered Select Dot** the updated adapter records only G8 target's non-secret native ID/type and allowlisted field names/room/thread IDs. Account-wide previews and other Dot records are not persisted. This diagnostic occurs before selection validation so a rejection can be investigated without an agent API call. The user must reopen an updated Python window to load the fix; current windows/data are left untouched. Credential-bearing actions still require separate explicit local user confirmation.


### Final semantic correction: identity is opaque, path guard is separate

Further primary-source inspection shows `resolve_dot` compares `item.id == dot_id` literally. `_ID` is an HTTP path allowlist, not the list identity schema; applying it to selection would still be too strict for a legitimate opaque/base64 identity. Workspace now preserves any nonempty string identity (local16KiB/control-character bounds only), with no strip, decode, namespace rewrite or room/thread substitution. Other primitive/object types are Unsupported and logged by type without coercion. The prior charset/colon/tilde discussion is historical; it is not the final identity validator.

Literal `--dot-id=VALUE` and `--before=VALUE` arguments are used both into the bounded launcher and into unchanged CLI, preserving leading dashes and base64 punctuation without introducing flags. Shell is disabled. Workspace never places this identifier in a URL. The pinned CLI's original `assert_allowed(method,path)` remains unchanged and is the first request step before header construction/network; unsafe room-creation paths are rejected there. CLI endpoint/auth policy is not relaxed. A source-AST regression verifies that ordering. Labels are plain text. The source-derived fixture now uses `opaque-prefix:YWJj+/==`, explicitly synthetic, proving parse/real modal/save/reload/Connect-enabled without live Connect. Actual-account fixture remains BLOCKED until the human-provided ID is obtained.

Installed source is updated, but existing windows retain their loaded code. Leave the current handoff window unchanged to Copy native ID; after the actual-ID fixture passes, reopen an updated Python window to apply the final opaque validator. No window is auto-closed, no data is overwritten, no live operation is triggered by development.

## Automatic collaboration runs (2026-10-06)

The statements above about one-use consent, no polling and no relay describe manual use and remain true for it.
The one exception is a user-started automatic collaboration run: the start dialog shows the disclosure and asks
for a run-scoped authorisation. While that run is active the workspace may send to and read from the selected
Dot without further prompts (reads about every 10 seconds, at most 400 requests). The authorisation covers only
`send` and `messages` for the selected Dot, never `list` or `connect`, and is revoked when the run ends, is
stopped, or the Dot disconnects. See `docs/DESIGN-auto-collab.md`.
