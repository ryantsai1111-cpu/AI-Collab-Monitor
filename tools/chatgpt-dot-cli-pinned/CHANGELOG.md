# Changelog

## Unreleased

- The login file follows `CODEX_HOME`, the same way Codex does. `--auth` expands `~`.
- A missing login file says where the CLI looked (`~/.codex/auth.json`, `auth.json in CODEX_HOME`, or the `--auth` file) and what to run: `codex login` with a ChatGPT account, or `--auth PATH`. It never prints a full local path.
- A login file saved with a UTF-8 byte-order mark loads. A file that is not UTF-8 or not a JSON object is an auth error (exit 2), not a traceback.
- Docs: disclaimer, privacy, platform matrix, and `CODEX_HOME`. CONTRIBUTING.md, SECURITY.md, and issue and merge request templates. The README no longer names the CI runner or a mirror.

## v0.2.2

Usage docs cover every command, flag, JSON key, and failure mode in zh-TW and English. Help text states defaults and ranges. The auth path is `.codex/auth.json` in the home directory on Linux, macOS, and Windows. Windows consoles are switched to UTF-8 so zh-TW text does not crash cp950 or cp1252. Unix permission bits are not checked on Windows.

Supported operating systems:

- Linux: tested in CI (Python 3.11, 3.12, 3.13) on this project's runner
- Windows: tested in CI (Python 3.12) on GitLab hosted runners
- macOS: tested locally

Install:

- Linux and macOS: `uv tool install git+https://gitlab.com/aa22396584/chatgpt-dot-cli.git@v0.2.2`
- Windows (PowerShell): `uv tool install "git+https://gitlab.com/aa22396584/chatgpt-dot-cli.git@v0.2.2"`

The Release attaches the platform-independent wheel and sdist.

Part of trinity-cli: https://gitlab.com/aa22396584/trinity-cli

Related: https://gitlab.com/aa22396584/chatgpt-dot-cli, https://gitlab.com/aa22396584/grok-bot-cli, https://gitlab.com/aa22396584/muse-web-cli.

## v0.2.1

The v0.2.0 tag stays where it is. Its release job failed because `apt-get update` received HTTP 500 from the Debian mirror, so that tag has no GitLab Release.

- The tag release job downloads release-cli v0.24.0 with Python, using `dpkg --print-architecture`, and no longer uses apt.
- Package version is 0.2.1. Behavior matches v0.2.0.

## v0.2.0

### Breaking

- `messages --json` is always an object with `name`, `lines`, and `messages`. `messages` is the raw items, oldest to newest. `lines` are speaker-labeled and newest first. A bare array is no longer printed. With no room, both lists are empty, `note` is set, and the exit code is 0.
- `--limit` must be an integer from 1 to 32. The default is still 20. `0`, `33`, and any other value outside that range exit 2 and do not call the API.

### 破壞性變更

- `messages --json` 一律是含 `name`、`lines`、`messages` 的物件。`messages` 是原始訊息，由舊到新；`lines` 是帶說話者的文字，由新到舊。不再輸出純陣列。沒有房間時兩個清單都是空的，並附上 `note`，結束碼為 0。
- `--limit` 必須是 1 到 32 的整數，預設仍是 20。`0`、`33` 和其他範圍外的值結束碼為 2，而且不會送出請求。

### Added

- `messages --before` and `messages --after` take one message id and return a single page. The CLI does not send `cursor` and does not follow more pages.
- `summary --no-activity` skips the activity read. Activity is still fetched unless this flag is set.
- `probe --json` prints a status object. Probe text is buffered and printed in the original order.
- `chatgpt-dot-cli --version`.
- Summary JSON adds each dot's `id` and a top-level `primary_http`.
- Exact redaction of `email`, `account_id`, `user_id`, `signaling_url`, `magic_link_url`, `magic_link_share_text`, and `inspector_url`.

### Changed

- Summary and probe share independent GETs across at most 3 workers. Each request still retries at most once.
- A non-JSON 403, 429, or 503 after that retry stops `summary` with exit 3. Stderr says the body was not JSON (likely Cloudflare).
- Any other non-200 response, except an ineligible email channel, prints one stderr line with the path, status, and detail summary, then exits 3. Email ineligible still exits 0.
- With no subcommand, the CLI prints help and exits 2. It does not run `summary`.
- `send` text output is `sent to {name}`.
- An empty set of dot sender ids is labeled `unknown:`, with one stderr note that `messaging_room_preview` has no aeon member.
- MCP tool failures propagate as MCP errors. An empty room and a missing root thread return JSON notes.
- Suffix commands given `--dot-id` fetch that dot directly and skip the dot list. `messages` and `send` still list dots so they can read the room and its members.
- Package metadata is 0.2.0 under MIT, for Python 3.11–3.13.

### Removed

- The root `client.py` script. Use `chatgpt-dot-cli probe`.

## v0.1.3

- MIT license, GitLab CI tests, and tag-based GitLab Releases.
- README and skill rewritten. The README says the repo is public and that "Your dot" is the default name until the dot is renamed.

## v0.1.2

- Message speakers are labeled from account ids (`dot:`, `you:`). The skill checks setup with `list`.

## v0.1.1

- README and skill in Traditional Chinese and English.

## v0.1.0

- First release: a read-only client for the Your dot backend, a CLI that reads a dot and can send it a message, a local MCP server with the same commands, and an agent skill.
- The command and project are named `chatgpt-dot-cli`.
