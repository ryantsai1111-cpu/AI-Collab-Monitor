# Security

Updated 2026-10-11 for the current source checkout. Claude/Codex/Hermes authentication remains backend-owned; Workspace does not collect their authentication files or initiate login. The Local role now calls Hermes with its existing provider configuration; legacy endpoint/key settings are not used. The pinned unofficial Dot transport has a separate credential-bearing consent boundary; see [DOT-UNOFFICIAL](DOT-UNOFFICIAL.md). Historical live-test reports do not authorize new calls.

## Persistence boundary

Core sanitizes input, output, errors, metadata, raw records, diagnostics and exports before writing. Structured credential keys, recognizable tokens, auth headers, cookies, password assignments, URL credentials and private-key blocks are redacted. Hidden reasoning/thinking is omitted, including corresponding stream events. Raw fidelity is subordinate to these controls and the audit records state when fields were removed. Detection cannot mathematically identify every arbitrary secret value; do not deliberately submit secret-bearing prompts or files.

Fragmented stream payloads need stateful treatment; security regression tests use synthetic markers and inspect SQLite/WAL/JSONL and export data. This is distinct from merely checking a rendered bubble. See final acceptance for measured results.

## Files and permissions

Artifact reads resolve paths against the selected project and application artifact roots, enforce a 16 MiB size limit and deny credential-like paths (including auth.json, .env and key/certificate files). Text imports become sanitized managed copies; JSONL is parsed and sanitized record by record. Export destinations cannot overwrite managed database/raw/artifact storage, use credential filenames, symlinks, Windows device paths or alternate data streams.

Read-only Git commands use argument arrays, disabled optional locks/pagers/hooks/fsmonitor/external diff/textconv, and literal pathspecs. Credential paths are excluded before patch generation and rename detection is disabled. Commit, push and merge are absent. Existing legacy logs are read-only and sanitization applies before displaying/importing them.

### Screenshots and image attachments

An explicitly selected PNG/JPEG screenshot can be copied into managed artifact storage after structural validation and import confirmation. The UI states that **pixels are not automatically redacted**. Recognizable sensitive text in supported image metadata is rejected, but this cannot prove the pixels are free of secrets. Screenshot safety must not be inferred from the text redaction tests.

Opening a managed screenshot shows a preview. Exporting its bytes opens `ScreenshotReviewDialog`: each image must load, and the user must check the review confirmation. Individual exports then pass `screenshot_reviewed=True`; task ZIP exports explicitly pass `include_screenshots=True`. The Core API defaults both flags to false. ZIPs include a screenshot security note; JSON/Markdown/HTML keep screenshot metadata without embedding image bytes. Cancelling image review cancels that export. Image attachments sent to a capable agent also retain their pixels; this is distinct from importing or exporting a task artifact.

### Native session reader

Claude native discovery uses the public official SDK only after an explicit action. The helper is pinned locally at 0.3.289 with install scripts and optional CLI binaries disabled. It has no login or inference command. Reads require the selected project directory; worktree expansion is false. History requires explicit prior discovery, matching session/cwd, bounded pagination and a known transcript size (16 MiB default). Core verifies project scope again after the read and discards results if the project changed. Metadata titles may contain prompt text and cross the same sanitizer. Native reasoning blocks and embedded attachment data are omitted before history is returned.

**View native history** is an explicit, read-only preview gated by actual helper capability; it does not persist transcript messages or remap a Task. Importing a session adds sanitized local metadata without resuming it or changing task ownership. Backend native-reader acceptance passed separately; the newly authored GUI controls still await a visible rerun.

Backend permissions remain backend-owned. Claude/Codex Workspace requests default to asking; `acw/approvals.py` also supports user-selected edits/all modes and connection-local allow rules. The classifier is not a general shell sandbox. Hermes one-shot does not expose an interactive approval bridge: its existing settings may approve tools automatically, so Workspace approval controls are unavailable for Hermes. The adapter never passes yolo/hook-acceptance flags or writes Hermes config. Hermes Stop terminates only the owned invocation's process tree; Claude/Codex retain protocol cancellation. The orchestrator does not grant pending requests or change policies. See [HERMES](HERMES.md).

## Local storage and retention

Data uses SQLite WAL and raw JSONL under the per-user application data directory or an explicit isolated test directory. Rotation/retention concern only application-owned log data. Original Monitor logs are never rotated, reset or modified. Text exports apply credential/hidden-reasoning filtering; separately reviewed screenshot bytes retain their original pixels. Diagnostics include only allowlisted runtime metadata and sanitized events, never backend credential/config files or screenshot pixels. An OS credential store is not used because the app stores no credentials.


## Current approved Dot integration update

The earlier official-bridge blocker remains historical context. The pinned unofficial Dot adapter supports consented manual operations and bounded send/read grants for an explicitly started collaboration run. See [Dot activation and boundaries](DOT-UNOFFICIAL.md) and [collaboration rules](DESIGN-auto-collab.md). Starting the app grants neither. Current offline tests do not establish live Dot or EXE acceptance.
