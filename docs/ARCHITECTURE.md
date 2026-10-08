# Architecture

## Decision

PySide6 6.11.2 + Python 3.12.14 is the PRD-permitted desktop alternative. RYAN-PC has an existing Python runtime. Rust/cargo and a verified Tauri Windows build toolchain were absent during inventory. No system installation was performed. A future Tauri migration can reuse the adapter contract, SQLite schema, event semantics and acceptance suite; this delivery does not claim to be Tauri.

```
PySide6 MainWindow (three panels, worker threads)
  -> WorkspaceCore (task/session/project/handoff/permissions)
     -> ClaudeAdapter -> official stream-json/control protocol
     -> CodexAdapter  -> official app-server JSON-RPC stdio
     -> DotAdapter    -> explicit blocked capability boundary
  -> Store -> SQLite WAL + sanitized raw JSONL + scoped artifacts
```

The UI never builds a shell command to invoke an agent. Core calls adapters, adapters own their processes and protocol IDs. Blocking work stays off the Qt UI thread. Background events enter a queue, with bounded UI polling. Streaming assistant output and structured tool/command/file events remain distinct.

## Data and recovery

Each agent can select its own project/task and map its own native session. Role selections are persisted in existing settings rows, without a schema change. Shared workspace navigation provides the initial default; explicit role selections remain independent. See [Independent agent projects and sessions](AGENT-CONTEXTS.md) for UI behavior, routing, collaboration checks and provider limits.

SQLite tables: projects, tasks, sessions, messages, events, handoffs, artifacts, settings. A task maps its three native backend session IDs. Session names are Workspace-local labels where backend rename is unsupported. Backend-native session imports must be explicitly requested; existing work sessions are not silently resumed.

Raw JSONL preserves safe backend fields. Hidden reasoning, credentials and potentially fragmented sensitive payloads are omitted/redacted; records identify this exception to byte-for-byte fidelity. Message source and handoff payload are separate immutable facts; annotations do not overwrite source content.

SQLite WAL transactions survive abnormal close. On restart, stale busy/interrupted work is recovered to local history without sending a prompt. Reconnection is explicit. Offline local history remains usable.

## Boundaries

Automatic orchestration is OFF. There is no approval decision engine, automatic handoff, deployment, commit, push or merge. Git reads use argument lists and disable optional locks. Legacy Monitor reads only the four explicitly named logs incrementally; no writes, resets or session control.

The app is installed per user. The desktop contains a shortcut. Existing Python is an explicit runtime dependency; the compiled Windows launcher is not a bundled standalone Python interpreter.

## Official native Claude session helper

The Python adapter invokes a small read-only Node bridge under `tools/claude-session-sdk`. It uses pinned official `@anthropic-ai/claude-agent-sdk@0.3.289` public session metadata/history functions, with an explicit current project `dir`, worktree expansion disabled, bounded pages and transcript size. Discovery and history are explicit user actions; importing metadata never resumes a backend or rewrites the current task mapping. Inference continues through the existing installed Claude Code CLI and its unchanged permission policy. Node is discovered from configuration/PATH or alongside the existing Python runtime; no global installation is required.

The source archive contains the helper, package manifest and lockfile, not installed third-party dependencies. The per-user installer stages existing dependencies without network installation. Native helper validation used only the task's isolated Claude project.


## Current approved Dot integration update

The earlier official-bridge blocker remains historical context. An explicitly approved, pinned unofficial Dot adapter and manual UI are now implemented and offline-tested. See [Dot activation and boundaries](DOT-UNOFFICIAL.md). Only the human may trigger live credential-bearing list/connect/read/send. No live Dot PASS or Final acceptance is claimed. EXE work remains deferred.
