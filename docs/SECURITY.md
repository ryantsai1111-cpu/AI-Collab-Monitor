# Security

The user-authorized scope is a new desktop application and isolated test projects. Existing production sessions and the original Monitor are preserved. Workspace never reads, copies, logs or exports authentication files. The user completed official Claude login separately; the successful later live tests use that existing official CLI state. Workspace does not invoke login, extract credentials or store an API key. Private dot endpoints, unapproved third-party bridges, system installation and security-setting changes remain outside its operation.

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

Agent permissions remain backend-owned. The Workspace has no auto-approve path. Approval dialogs display actual requested operation and require a user decision. Stop calls the backend cancellation protocol; global stop requires confirmation. No process-tree termination or sandbox bypass is used.

## Local storage and retention

Data uses SQLite WAL and raw JSONL under the per-user application data directory or an explicit isolated test directory. Rotation/retention concern only application-owned log data. Original Monitor logs are never rotated, reset or modified. Text exports apply credential/hidden-reasoning filtering; separately reviewed screenshot bytes retain their original pixels. Diagnostics include only allowlisted runtime metadata and sanitized events, never backend credential/config files or screenshot pixels. An OS credential store is not used because the app stores no credentials.


## Current approved Dot integration update

The earlier official-bridge blocker remains historical context. An explicitly approved, pinned unofficial Dot adapter and manual UI are now implemented and offline-tested. See [Dot activation and boundaries](DOT-UNOFFICIAL.md). Only the human may trigger live credential-bearing list/connect/read/send. No live Dot PASS or Final acceptance is claimed. EXE work remains deferred.
