---
name: chatgpt-dot-cli
description: >-
  Read and message the user's ChatGPT Your dot (orbit, tbo) with the
  chatgpt-dot-cli CLI. Use chatgpt-dot-cli MCP tools only if they are already
  connected in this session. Use when the user asks about Your dot, dot status,
  dot messages, ChatGPT usage, orbit, tbo, dot threads, activity, computers,
  automations, email, environment, or wants to send a message to their dot.
  Reply in the user's language. 用 chatgpt-dot-cli 讀取或傳訊息給使用者的
  ChatGPT Your dot：當使用者問到 Your dot、dot 狀態、dot 訊息、ChatGPT 用量、
  orbit、tbo、dot 的 threads、活動、電腦、自動化、email、環境，或想傳訊息給 dot 時使用。
  Do not ask the user to install or enable MCP. 不要要求使用者安裝或啟用 MCP。
---

# ChatGPT Your dot

This CLI is a local client for the user's official ChatGPT Your dot. It is not a second dot. The desktop app calls the dot orbit; the HTTP resource is tbo.

Reply in the user's language.

For cross-agent tasks (ask all three, hand off, digest) use the `trinity-cli` skill.

1. CLI first. Quick check: run `chatgpt-dot-cli list` (about 3 seconds). If it is not on PATH, try `$HOME/.local/bin/chatgpt-dot-cli` on Linux or macOS, or `%USERPROFILE%\.local\bin\chatgpt-dot-cli.exe` on Windows.
2. If neither exists, install the pinned tag, then run `chatgpt-dot-cli --version` and `chatgpt-dot-cli list`:

   Linux or macOS:

   ```bash
   uv tool install git+https://gitlab.com/aa22396584/chatgpt-dot-cli.git@v0.2.2
   ```

   Windows PowerShell:

   ```powershell
   uv tool install "git+https://gitlab.com/aa22396584/chatgpt-dot-cli.git@v0.2.2"
   ```

3. Run `summary` only when the user asks for status. A bare `chatgpt-dot-cli` is not a summary: with no subcommand it prints help and exits 2, and it does not call the API. `summary --no-activity` skips the slow activity read. The default is to fetch activity.
4. Use `chatgpt-dot-cli` MCP tools only if they are already connected in this session. Do not ask the user to install or enable MCP.

"Your dot" is the default name, shown when `display_name` is empty. After the user renames the dot in the ChatGPT app, the CLI prints the new name.

`messages` labels each line `dot:` (the dot spoke) or `you:` (the user spoke). In JSON, `role` is always `user`; never use it to tell who spoke. If the room preview has no aeon member, lines say `unknown:` and stderr notes that. Do not guess from `role`.

## Commands

Run `chatgpt-dot-cli --help` for the full list. Global flags: `--version`, `--auth` (default: `.codex/auth.json` in the home directory), `--json` (default: off). `--json` works before or after the command, but not after a standalone `--`.

- `list` — dots with ids (quick check; this is the first command)
- `summary` — plan type, status, and recent messages; `--no-activity` skips activity (default: activity is fetched)
- `usage` — plan usage
- `primary` — which dot is selected
- `probe` — status codes and field names; `--json` prints a status object
- `show` — one dot. `--dot-id` (preferred) or a positional id. Default: the only dot
- `threads`, `activity`, `root-thread`, `computers`, `env`, `automations`, `email-status` — same `--dot-id` or positional id. Default: the only dot
- `by-thread` — optional `thread_id` (default: the dot's active root thread) and `--dot-id` (used only when the thread id is omitted; default: the only dot)
- `messages` — `--dot-id` only (no positional id), `--limit` default 20 range 1..32, `--before` one message id (default: none), `--after` one message id (default: none). Does not create a room. JSON keys: `name`, `lines`, `messages`, and `note` when there is no room. `messages` are oldest to newest; `lines` are newest first
- `send TEXT` — `--dot-id` default the only dot. `chatgpt-dot-cli send -- "-text starting with a dash"`. Text mode prints `sent to NAME`. Do not send unless the user asked

## Rules

- Do not read the auth file, do not print tokens, and do not send your own HTTP requests to `chatgpt.com`. The file is `$HOME/.codex/auth.json` on Linux and macOS, and `%USERPROFILE%\.codex\auth.json` on Windows. MCP reads only that file and has no `--auth` flag.
- The dot id comes from `list`. `aeon_id` is not a dot id.
- Send a text message only when the user asks you to talk to the dot.
- Messages sent from the CLI go to the dot's messaging inbox; the desktop main view can show them a little later.
- Local computer work still needs the ChatGPT desktop app open.
- Refuse pause, resume, delete, connect, disconnect, email claim, voice, and any request to call `/ps/orbit`. Read-only except `send`.
- On Windows the CLI switches stdout and stderr to UTF-8. It does not inspect Unix permission bits there.

## Troubleshooting

- Exit 0 is OK, including email channel `403` with `ineligible` (that account cannot use email).
- Exit 2: bad arguments, or the auth file is missing or not a ChatGPT login. `--limit` outside 1..32 is exit 2 and does not call the API. `--auth` without a path is exit 2 (`chatgpt-dot-cli: error: --auth requires a path`).
- Exit 3: API or network error, including a non-JSON 403/429/503 after one retry (often Cloudflare). `summary` that is slow or empty of activity: rerun with `--no-activity`.
- On 401, tell the user to run `codex login`.
- The command needs network access.
