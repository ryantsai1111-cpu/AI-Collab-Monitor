# Troubleshooting

## Startup

If the launcher reports a missing runtime, inspect `python-path.txt` and point it to an already installed compatible Python 3.12 `pythonw.exe`. The tested runtime is recorded in `evidence/toolchain-manifest.json`. Reinstalling system software is not an automatic fallback. PySide6 lives in the application-local vendor directory. `startup-error.log` records a sanitized startup failure.

Use a separate `--data-dir` for tests. A lock prevents two windows from using the same dataset simultaneously. If the process crashed, Qt can recover a stale lock. Do not delete unrelated process state.

Compiled EXE launch was actually attempted and rejected by Windows security; installed EXE subsequently absent. Per-user source installation and shortcut targets were verified, and source Qt50cases plus25last-widget regressions passed. Neither restores EXE startup acceptance. Do not restore/copy/rebuild/retry this launcher or alter protections without explicit new authorization. See EXE-SECURITY-BLOCKER.md, LAUNCHER-STATIC-REVIEW.md and the current Final Acceptance Report. Historical Qt/token errors and failed first runs remain preserved; they are not current blanket UI blockers.

## Backend disconnected / offline

Use Connect, inspect Settings/Diagnostics, and confirm the exact executable path/version. The running Claude Desktop process may show a virtual Roaming path that does not exist from ordinary processes; the tested executable is in the Microsoft Store package LocalCache path.

Connect does not resume a session automatically. Select an existing Workspace session and Resume explicitly. Existing official CLI login is used; if the backend asks for authentication, perform that separately only with user approval. Never copy auth.json or tokens into this app.

An executable being present is not a connection. Errors from handshake or turn execution remain visible. The app does not silently create a replacement conversation after disconnect.

## Claude authentication status

The original error `Failed to authenticate: OAuth session expired and could not be refreshed` is retained in historical evidence. After the user completed official login separately, the [new isolated run](../evidence/claude-live-run-1791165118613641100.json) passed 13 backend checks including messages, streaming, model/effort selection, tools, resume and stop. Do not diagnose the current build as OAuth-blocked based on the earlier report. If the same error recurs, retain the sanitized exact error and use the user's official authentication workflow; Workspace never collects a token or initiates login itself.

## Native session discovery / history

Select the intended Project, sync its directory and use **Discover…**. Claude discovery uses the pinned project-local official TypeScript SDK 0.3.289 and only the selected cwd; worktrees are excluded. Select a result, then **View native history** for read-only **Conversation / activity** and **Sanitized structured records** tabs. If the helper is unsupported or unavailable, that control is disabled and its tooltip gives the reason. Fetching runs in a worker and displays the actual error on failure.

**Import selected (no resume)** stores metadata locally. Neither importing metadata nor viewing native history maps the current Task, resumes, sends a prompt or persists the original transcript into Workspace History. **Resume** remains an explicit separate action, and panel **History** shows locally recorded messages.

The backend reader's [seven-check native acceptance](../evidence/claude-native-session-check-1791165508399169700.json) passed for isolated test sessions; its UI integration still needs revalidation. If discovery fails, inspect `native_session_sdk_version`, `native_session_error` and `native_session_scope` in Diagnostics. Missing helper/runtime/public SDK methods produce an explicit unavailable error; they do not disable stored Workspace history. An empty list can mean no native sessions exist for that exact cwd and is not a reason to search other projects automatically.

Native history rejects an undiscovered session, a different project, missing/unknown transcript size or a file larger than the configured bound (16 MiB default). Select the correct project and rediscover before a deliberate native read. SDK history is paginated; the page limit is 1–500 and offset 0–10000. Importing metadata alone is not transcript-import acceptance.

## Artifacts and screenshots

Use **Diff / Tests → Artifacts → Import file…** for a selected project file. Text must be UTF-8; JSONL must have valid JSON records. Files outside the selected project/artifact roots, credential-like names and files over 16 MiB are refused. Managed copies keep imports available even if their original source later changes. **Open selected** uses Windows file associations for text; an OS handler error does not mean the artifact was lost.

PNG/JPEG screenshot imports require explicit confirmation and structure checks. Image pixels are not redacted. If image export confirmation is disabled, open every image in the review selector, ensure each preview loaded and check the review box; **Actual size** helps inspect small text. Cancelling review cancels the export. Task ZIP includes screenshot bytes only after that review; other task formats retain metadata. Do not interpret text secret-filter tests as proof that an image contains no sensitive text.

Invalid image structure or recognizable sensitive image metadata is rejected. Export targets must have a matching supported extension and an existing parent directory, and cannot be Windows device/alternate-stream paths, symlinks, credential filenames or managed storage files. Choose an ordinary user-selected output file without changing filesystem permissions.

## dot

The current integration is blocked pending a verified official external message bridge. OpenAI API access or Codex app-server with ChatGPT authentication does not provide the original dot conversation. See ADAPTERS.md. Do not install an unofficial bridge as an unreviewed workaround.

## Streaming / command output

Claude and Codex event schemas differ. Codex commandExecution provides combined output, not independent stderr. Empty stderr in a normalized record does not prove the command produced none. UI and exports identify this limitation.

Git diff has separate native command/exit/stderr details. Without an upstream, ahead/behind are unknown, not zero. Before the first commit, the viewer labels unborn HEAD and preserves staged additions and unstaged tracked edits as separate patches. Untracked files have no tracked Git patch. A failed Git command must be read as an error, not as a clean repository.

## Diagnostics and legacy Monitor

Export portable diagnostics from Settings. Diagnostics exclude secrets and hidden reasoning. The old `C:\Users\ryant\Desktop\AI-Collab-Monitor` remains a read-only optional log source and separate fallback; its panes may stay open. Workspace does not launch, stop or reset those panes.


## Current approved Dot integration update

The earlier official-bridge blocker remains historical context. An explicitly approved, pinned unofficial Dot adapter and manual UI are now implemented and offline-tested. See [Dot activation and boundaries](DOT-UNOFFICIAL.md). Only the human may trigger live credential-bearing list/connect/read/send. No live Dot PASS or Final acceptance is claimed. EXE work remains deferred.
