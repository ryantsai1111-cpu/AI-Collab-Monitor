# Independent agent projects and sessions

Implemented against `f9bbe88` on 2026-10-07. The earlier Codex executable discovery repair remains in the same working tree.

## Operator workflow

Each panel shows its project and task below the role header. Click that button, or open the role's conversation sidebar, to select its project and task. Use New to create a backend session or Resume to activate a saved session. New creates a workspace task when the role has a project but no task. The sidebar also has a separate New task action.

Selecting a project or task changes only that role. Its directory, session mapping, history, draft, attachments and pending approvals follow that selection. Other roles can remain on different projects and continue their active turns. The role being switched must be idle. Changing a project never silently resumes an existing session or sends a prompt.

Before a role has an explicit selection, it uses the workspace project/task as its initial default. After an explicit selection, shared workspace navigation does not replace it. This keeps the shared task controls available for collaboration and workspace inspection.

The Claude and Codex desktop conversation navigator now opens a conversation into that role's own project/task. The existing one-at-a-time open guard remains, but another role's active turn does not block opening an idle role's conversation.

## Persistence and routing

Selections use existing SQLite settings rows named `selection.claude`, `selection.dot`, `selection.codex` and `selection.local`. Each stores `project_id` and `task_id`. Session IDs stay in the existing task/session tables. No schema migration or dependency is introduced.

Core connection, new/resume, native discovery/history, prompt/attachment validation and event attribution use the selected role's context. Restart restores selections without connecting or resuming. UI view caches are keyed by role, project, task and session. Git refreshes update only panels using the repository that was inspected.

Handoff previews identify both the source and receiving task/project. Delivery uses the target role's selected task; changing its task or mapped session after preparing the preview requires preparing a new preview.

Automatic collaboration requires its participating roles to select the shared collaboration task. It rejects differing tasks before any session preparation or send and never silently aligns independent selections.

## Provider limits

Claude, Codex and Local LLM retain their existing backend session capabilities. G8毛's project is workspace metadata; the unofficial Dot integration still requires explicit consent, can resume an existing approved Dot identity, and cannot create a native project or a new Dot conversation. Local LLM retains its selected harness's capabilities.

## Verification

Validated 308 tests across the role-context, Core, desktop-session, orchestration, UI, approval, local-provider, Codex/Claude/Dot, discovery, security, inspection and session-label suites: 305 passed and 3 opt-in live tests skipped. Syntax parsing and `git diff --check` passed.

`tests/test_agent_contexts.py` exercises independent contexts for all four roles, own-role idle checks, concurrent event/transcript routing, native discovery/history, attachment scopes, persistence without connection, cross-project resume rejection, target-aware handoffs, draft restoration, desktop Codex opening while Claude is busy, and automatic collaboration rejection.

A Codex protocol integration regression uses the real adapter with a labelled in-memory transport and verifies that `thread/start` receives Codex's selected directory and `thread/resume` stays in that project. No live inference or existing user conversation is used by these tests.

Two desktop UI assertions and the default-project assertion now check the role's selection instead of the global selection, matching the new behavior. Existing shared navigation and adapter protocol tests remain active.

Run in PowerShell from the repository root:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONPATH = 'vendor;tests'
python -m unittest tests.test_agent_contexts tests.test_core tests.test_desktop_sessions tests.test_orchestrator
python -m unittest tests.test_ui_refresh tests.test_approvals tests.test_local_ui tests.test_local_core
python -m unittest tests.test_codex tests.test_claude tests.test_dot tests.test_local_llm tests.test_codex_discovery
```
