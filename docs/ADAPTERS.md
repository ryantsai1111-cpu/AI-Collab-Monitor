# Adapter contract and verified boundaries

All adapters expose `connect`, `disconnect`, `list_models`, `list_efforts`, `list_sessions`, `create_session`, `resume_session`, `send_message`, `stop`, `set_project`, `stream_events`, and `get_history`. The base contract is in `acw/adapters/base.py`. Core receives typed callbacks and owns persistence. Connected is emitted only after a successful backend protocol handshake.

Capabilities include model selection, effort, sessions, files, tools, project, cancel, streaming, history and approvals. Menus consume backend discovery. No model catalog is hardcoded; lack of a supported catalog is rendered as Default backend model or Managed by ChatGPT / dot.

`attachment_capability(model)` is a pure adapter extension exposed by Core. Codex derives selected-model image support from official `model/list` inputModalities, not the existence of any image-capable model. The UI hides attachment/drop controls for unsupported selected models and preserves queued files until explicit clear. Approval controls require backend supports_approval and are disabled in readonly Monitor mode and for historical/resolved requests.

App-server JSON stderr diagnostics are parsed before recursive secret/hidden-reasoning filtering; public remaining fields are reserialized and filtering is annotated. Plain stderr uses text redaction. No raw hidden reasoning is retained to establish fidelity.

## Codex

Uses the existing official Codex 0.160.0 `app-server` over stdio. Generated schemas are retained in `evidence/codex-schema`. The adapter initializes, lists models/efforts, starts/resumes/reads/lists threads, streams turn events, and cancels with `turn/interrupt`. It never uses process-tree killing, `thread/shellCommand`, unrestricted `process/*`, or dangerous bypass flags.

`commandExecution.aggregatedOutput` is a **combined stdout/stderr stream**. The adapter preserves that distinction instead of inventing separate stderr. Exit codes, command status and diffs are independently rendered. Backend-specific approval requests require an explicit user response. See the live evidence for which methods passed on this machine.

Official contract: https://learn.chatgpt.com/docs/app-server

## Claude

Explicit `session_mcp_servers` constructor settings accept bounded structured STDIO command/args entries. They become inline official `--mcp-config` plus `--strict-mcp-config` and an empty built-in tool set for that isolated session. No permanent configuration, environment credential forwarding, HTTP endpoint, auto-allow rule or permission-mode flag is added. Defaults are unchanged. Native MCP tool/approval/results use the same adapter/Core/UI event path as other tools. The opt-in `scripts/run_live_mcp_echo_ui.py` exercised the already installed official MCP SDK1.32.0/Zod4.6.5 fixture with explicit user authorization and a human native approval:11 checks PASS, exact fixed string, one tool call, verified process exit. Its own handler has no filesystem/network/shell operations; official inference still uses network. See `evidence/live-mcp-echo-ui/`. This does not authorize another run or certify private connector access.

Uses the installed official Claude Code 2.1.286 programmatic streaming mode and the published official Agent SDK control protocol. A persistent stream supports partial text events, initialization, permissions and `interrupt`. Assistant completion is separate from tool completion. Model and effort choices come from the actual handshake; the selected model's effort support is checked before sending.

After the user completed official login, the isolated [live run](../evidence/claude-live-run-1791165118613641100.json) passed 13 checks: handshake, model discovery, effort discovery, message, streaming, cwd, tool events, fixture read, resume, model/effort selection, stop, Workspace-owned session list and Workspace-owned history. The earlier OAuth-expired result in `CLAUDE-AUTH-BLOCKER.md` is historical, not the current Claude blocker. This run did not validate the native SDK session reader or desktop UI.

Attachments use native user-message content blocks: bounded UTF-8 text and PNG/JPEG/GIF/WebP images. Paths must pass Core and adapter scope checks. Recognizable text secrets are redacted; image pixels are not. The [separate live attachment test](../evidence/claude-attachments-1791165415288631900.json) passed for a synthetic text marker and blue PNG, with streaming, zero tool calls and zero approval requests. Other formats were not established by that test.

### Native session discovery and history

`ClaudeAdapter.list_sessions(native=True)` invokes the public official SDK through `tools/claude-session-sdk/session-helper.mjs`. The project-local Node package is pinned to `@anthropic-ai/claude-agent-sdk@0.3.289`, installed with lifecycle scripts and optional platform CLI packages disabled. Existing Claude CLI execution remains separate. A compatible installed official Python SDK is a fallback, not a required new installation.

The helper uses only `listSessions`, `getSessionInfo` and `getSessionMessages`. It requires an explicit selected `dir`, disables worktree expansion, bounds pagination, filters metadata titles and omits hidden reasoning and attachment binary from history. Native transcript reads require a previously discovered session in the selected cwd and a known bounded file size (16 MiB by default). It does not query a model, log in, resume, rename or mutate a native session.

UI **Discover…** calls `WorkspaceCore.discover_sessions`; **Import selected (no resume)** calls `import_session` and stores metadata locally. Import does not change the current task mapping or fetch a transcript. **View native history** is enabled only after `native_history_capability` confirms an available official reader. Its worker calls `native_history`, which verifies the selected project and discovered session before and after the read, then displays a read-only conversation/activity view and sanitized structured records. Unsupported backends show **Native history unavailable** with the actual reason.

Native preview does not persist messages, remap a Task, resume or send. **Resume** is a separate action; the panel's **History** reads Workspace-persisted messages. Startup and Connect do not scan native sessions. The explicit native-history UI now has visible Qt case passes; broader real native-session UI scope remains itemized.

The separate [native SDK check](../evidence/claude-native-session-check-1791165508399169700.json) passed all seven checks under normal permissions: discovery, selected cwd, metadata, native history, original message IDs, no implicit resume and pagination. It examined only the isolated `tests/sandbox-claude` index (four records) and explicitly selected one test session's 13 messages. No query or resume was called. This proves the backend reader, not the new UI controls or access to every Desktop conversation. See [SDK research](../evidence/claude-session-sdk-research.md) for the public contracts.

Official references:
- https://code.claude.com/docs/en/agent-sdk/streaming-output
- https://code.claude.com/docs/en/agent-sdk/streaming-vs-single-mode
- https://code.claude.com/docs/en/agent-sdk/sessions
- https://code.claude.com/docs/en/agent-sdk/typescript
- https://github.com/anthropics/claude-agent-sdk-python

## Dot — approved unofficial, manual activation

See [DOT-UNOFFICIAL.md](DOT-UNOFFICIAL.md) for pinned source, bounded adapter contract, per-action local consent, unsupported streaming/cancel/files/New, selected native identity, offline evidence and the exact human handoff. Startup makes no Dot call. The development agent has not launched live authentication; live acceptance remains blocked.
