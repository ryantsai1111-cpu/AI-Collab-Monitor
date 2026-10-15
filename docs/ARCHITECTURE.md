# Architecture

Current checkout overview, updated 2026-10-09. Python 3.12 + PySide6 6.11.2; the source entry is `run.py`. Earlier compiled-launcher reports are historical.

## Components

```text
run.py
  -> MainWindow: live Monitor workbench, independent AgentPanel + local AgentRail
     -> MonitorDashboard: separate read-only collaboration overview
     -> WorkspaceCore: instance routing, context, sessions, approvals, persistence
        -> ClaudeAdapter: official CLI streaming/control protocol
        -> CodexAdapter: official app-server JSON-RPC over stdio
        -> HermesAdapter (local provider): bounded one-shot CLI, JSONL events
        -> DotAdapter: pinned unofficial transport, scoped consent
     -> AutoCollab: selected lead/implementer, correlation, budgets and holds
     -> Store: SQLite WAL, sanitized raw JSONL and scoped artifacts
```

Blocking UI work runs in workers. Typed adapter events enter a queue for bounded Qt polling. Adapters own protocol IDs and backend processes; tool completion and assistant completion remain separate.

## Providers and instances

`acw/agents.py` distinguishes provider type from instance identity. The original four IDs remain compatible; additional Claude, Codex and Local instances receive stable IDs and independent adapters. Settings and project/task selections use instance-specific keys. Creation and application restart do not connect, read credentials or send prompts.

Original task session columns remain supported; extra instance mappings use existing `tasks.metadata.agent_sessions`. This instance feature adds no schema migration. Earlier Local LLM support already has its own additive migration.

Core rejects overlapping session control inside this process by backend family and concurrent resume reservations. Hermes uses a stable Workspace alias and stores its changing native session ID in existing session metadata. It cannot detect an external Desktop or Hermes CLI sending to the same session. Working directories are not automatically separate worktrees. See [AGENT-CONTEXTS](AGENT-CONTEXTS.md) and [HERMES](HERMES.md).

## Collaboration and approvals

An explicit run selects lead and implementer instance IDs, which may share a provider. There is one active run, one lead/implementer pair, and optional existing Local/Dot review roles. Correlation envelopes, frozen bindings, round/step/time limits and uncertain-delivery handling prevent unrelated replies from advancing the run. Only the selected lead's validated approval completes it.

Each participant retains its own project/task/session; dispatch contracts and response reads address that Agent's frozen container. The lead container stores run audit events. Record navigation and nonparticipating Agents remain usable. The workbench remains open after start, with the overview available separately; closing first stops orchestration before requesting backend cancellation.

Claude/Codex approval policy defaults to asking; user-selected modes and connection-local rules may approve eligible requests. Remaining approval requests pause collaboration. Hermes instead uses its native one-shot approval settings and exposes no Workspace permission bridge. The orchestrator never changes these policies. See [SECURITY](SECURITY.md), [HERMES](HERMES.md) and [DESIGN-auto-collab](DESIGN-auto-collab.md).

## Storage and recovery

SQLite stores projects, tasks, sessions, messages, events, handoffs, artifacts and settings. On MainWindow construction, legacy shared selections are snapshotted once into each Agent's settings without contacting adapters. Agent navigation thereafter remains independent of the separate Record page. New conversations create distinct task containers; opening a saved conversation restores its original container. No schema migration is added. View state and unsent drafts are in memory only.

Restart marks interrupted streaming and uncertain deliveries locally without replaying prompts or resuming collaboration. Connections and backend resume are explicit. Raw JSONL, diagnostics and exports filter credentials and hidden reasoning; raw records are not byte-for-byte backend transcripts.

Default data is under `%LOCALAPPDATA%/AI-Collaboration-Workspace/data`; `--data-dir` supplies an isolated alternative. A Qt lock prevents two windows opening the same dataset.

## Native history and runtime tools

`acw/desktop_sessions.py` reads selected local Claude Code/Codex history for navigation and periodic synchronization. It does not implement general Claude Chat or complete Desktop synchronization. Workspace rename/archive metadata remains local.

Claude can also use `tools/claude-session-sdk/session-helper.mjs`, pinned by its package manifest, for explicit project-scoped official discovery/history. Metadata preview is separate from Desktop transcript import and inference.

Dot invokes `scripts/dot_cli_entry.py`, which verifies `tools/chatgpt-dot-cli-pinned/`. These are runtime dependencies, not cleanup candidates. `vendor/` supplies Qt; installed SDK `node_modules/` must also be retained.

`AI-Collab-Monitor/` is the earlier standalone log viewer. Workspace only reads configured legacy logs; it does not execute viewer scripts. Historical launchers and acceptance scripts are described in [scripts/README](../scripts/README.md).

## Remaining work

The Monitor workbench reuses the same AgentPanel instances across focused and parallel layouts; it does not duplicate composers or adapters. AgentRail projects a local snapshot each second and only emits navigation/add-dialog actions. The separate overview and legacy transcript modes retain their read-only controls. General Claude Chat, full bidirectional Desktop synchronization, natural-language run initiation, multiple parallel implementers, automatic team creation, Agent removal and worktree management remain unimplemented. Offline results in [tests/README](../tests/README.md) do not establish live backend acceptance.
