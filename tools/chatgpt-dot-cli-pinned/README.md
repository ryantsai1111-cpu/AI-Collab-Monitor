# chatgpt-dot-cli

[![pipeline status](https://gitlab.com/aa22396584/chatgpt-dot-cli/badges/main/pipeline.svg)](https://gitlab.com/aa22396584/chatgpt-dot-cli/-/commits/main)
[![release](https://gitlab.com/aa22396584/chatgpt-dot-cli/-/badges/release.svg)](https://gitlab.com/aa22396584/chatgpt-dot-cli/-/releases)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

[中文](#中文) · [English](#english)

Part of the trinity-cli family / trinity-cli 系列的一部分：<https://gitlab.com/aa22396584/trinity-cli>

## 中文

### 這是什麼

`chatgpt-dot-cli` 是 ChatGPT 官方 Your dot 的本機 client，不是第二個 dot。給已經用 ChatGPT 登入、想在終端機查看同一個 dot、讀訊息、傳文字的人。桌面版把這個 dot 叫做 orbit，HTTP 資源是 tbo。

「Your dot」是預設名稱：`display_name` 是空的時候就顯示 Your dot。你在 ChatGPT app 裡改名後，CLI 會印出新名字。

這個 repo 是公開的。需要 Python 3.11、3.12 或 3.13。安裝用 uv 或 pipx。登入來自 Codex 的 ChatGPT 登入檔，CLI 不另外做帳號。

非官方：這是個人專案，跟 OpenAI 沒有關係，也沒有得到 OpenAI 的背書或支援。它呼叫 ChatGPT app 用的、沒有公開文件的介面，OpenAI 隨時可能改掉。自動化使用可能違反 OpenAI 的使用條款，帳號風險自負。

支援的系統見[平台](#平台)。

### 安裝

版本釘在 tag `v0.2.2`。

Linux 或 macOS：

```bash
uv tool install git+https://gitlab.com/aa22396584/chatgpt-dot-cli.git@v0.2.2
chatgpt-dot-cli --version
```

或：

```bash
pipx install git+https://gitlab.com/aa22396584/chatgpt-dot-cli.git@v0.2.2
chatgpt-dot-cli --version
```

指令要在 PATH 裡。uv/pipx 放在 `$HOME/.local/bin`。

Windows（PowerShell）：

```powershell
irm https://astral.sh/uv/install.ps1 | iex
uv tool install "git+https://gitlab.com/aa22396584/chatgpt-dot-cli.git@v0.2.2"
chatgpt-dot-cli --version
```

Windows 的執行檔在 `%USERPROFILE%\.local\bin\chatgpt-dot-cli.exe`。新開一個終端機後 PATH 才會更新。也可以用 pipx：

```powershell
py -3.12 -m pip install --user pipx
pipx install "git+https://gitlab.com/aa22396584/chatgpt-dot-cli.git@v0.2.2"
chatgpt-dot-cli --version
```

`--version` 會印出 `chatgpt-dot-cli 0.2.2`。

GitLab Release 另附與平台無關的 wheel 與 sdist。用 pip 裝 wheel：

```bash
python3 -m pip install "https://gitlab.com/api/v4/projects/aa22396584%2Fchatgpt-dot-cli/packages/generic/chatgpt-dot-cli/v0.2.2/chatgpt_dot_cli-0.2.2-py3-none-any.whl"
```

升級要重新指定 tag。`uv tool upgrade` 不會把釘在 tag 的安裝移到下一個 tag。

```bash
uv tool install --force git+https://gitlab.com/aa22396584/chatgpt-dot-cli.git@v0.2.2
```

```powershell
uv tool install --force "git+https://gitlab.com/aa22396584/chatgpt-dot-cli.git@v0.2.2"
```

移除：

```bash
uv tool uninstall chatgpt-dot-cli
pipx uninstall chatgpt-dot-cli
```

```powershell
uv tool uninstall chatgpt-dot-cli
```

### 第一次設定

1. 安裝 [Codex CLI](https://github.com/openai/codex)，用 ChatGPT 帳號執行 `codex login`。
2. 登入檔的位置：
   - Linux：`$HOME/.codex/auth.json`
   - macOS：`$HOME/.codex/auth.json`
   - Windows：`%USERPROFILE%\.codex\auth.json`
   - 設了 `CODEX_HOME` 時，Codex 和這個 CLI 都改用 `$CODEX_HOME/auth.json`。
3. 檔案在別處時，CLI 用 `--auth 路徑`（可以用 `~`）。MCP 沒有 `--auth`，只讀上面那個預設路徑。
4. 確認可用（唯讀，約數秒）：

```bash
chatgpt-dot-cli list
```

成功時會印一行 dot，最後是 `N dot(s)`。不要把這個檔案貼到聊天裡。Token 不會被印出來。

### 快速開始

最常用的是 `list`、`messages`、`usage`、`summary --no-activity`。`send` 會真的傳訊息，下面只示範輸出形狀。

```text
$ chatgpt-dot-cli list
id=dot_example Example status=active paused=False kind=orbit
1 dot(s)

$ chatgpt-dot-cli messages --limit 2
Example messages=2
dot: example reply
you: example question

$ chatgpt-dot-cli usage
200 GET /wham/usage plan_type=example

$ chatgpt-dot-cli summary --no-activity
plan_type=example
primary available=true
Example status=active paused=False kind=orbit threads=1 activity=skipped computers=1 automations=0 environment=connected email=ineligible
  dot: example reply

$ chatgpt-dot-cli send -- "hello"
sent to Example
```

文字模式的 `usage`、`show` 與各讀取指令印的是欄位型別，不是密文內容。`--json` 的值是假資料時才寫在下面的參考裡。

### 指令參考

全域旗標：

| 旗標 | 預設 | 說明 |
| --- | --- | --- |
| `--version` |  | 印出版本後離開 |
| `--auth PATH` | `$CODEX_HOME/auth.json`，沒設 `CODEX_HOME` 時是家目錄裡的 `.codex/auth.json` | 登入檔路徑。有旗標就必須帶路徑 |
| `--json` | 關 | 印遮罩後的 JSON。可放在子指令前或後，不能放在單獨的 `--` 後面 |

沒有子指令時印出說明並以結束碼 2 離開，不呼叫 API。

#### `summary`

方案、dot 狀態、最近訊息。預設會讀 activity。

```bash
chatgpt-dot-cli summary --no-activity
```

| 旗標 | 預設 |
| --- | --- |
| `--no-activity` | 關（會讀 activity） |

`--json` 鍵：`plan_type`、`usage_http`、`primary_http`、`primary`、`dots`。每個 dot：`id`、`name`、`status`、`paused`、`kind`、`threads`、`threads_http`、`activity`、`activity_http`、`computers`、`computers_http`、`automations`、`automations_http`、`environment`、`environment_http`、`email`、`recent`。`--no-activity` 時 `activity` 與 `activity_http` 是 null，文字模式印 `activity=skipped`。

#### `usage`

```bash
chatgpt-dot-cli usage
```

沒有自己的旗標。`--json` 鍵：`status`、`body`。`body` 裡常用 `plan_type`、`rate_limit`（含 `allowed`）、`limit_reached`、`primary_window`（含 `used_percent`）、`reset_after_seconds`。其他欄位可能存在，密文會被遮罩。

#### `primary`

```bash
chatgpt-dot-cli primary
```

沒有自己的旗標。`--json` 鍵：`status`、`body`。

#### `list`

```bash
chatgpt-dot-cli list
```

沒有自己的旗標。文字：`id=... name status= paused= kind=`，最後 `N dot(s)`。`--json` 是遮罩後的 dot 陣列，常用鍵：`id`、`display_name`、`status`、`is_paused`、`aeon_kind`。

#### `probe`

每個讀取的 HTTP 狀態與欄位名稱。

```bash
chatgpt-dot-cli probe
```

沒有自己的旗標。`--json` 鍵：`usage_http`、`plan_type`、`primary_http`、`list_http`、`dots`。每個 dot：`name`、`status`、`paused`、`kind`、`reads`（`path`、`status`，訊息讀取另有 `items`）。

#### `show`

```bash
chatgpt-dot-cli show
```

| 旗標 | 預設 |
| --- | --- |
| `--dot-id` | 帳號上唯一的 dot |
| 位置參數 `dot_id` | 同上。建議用 `--dot-id` |

`--json` 鍵：`status`、`body`。

#### `threads`、`activity`、`root-thread`、`computers`、`env`、`automations`、`email-status`

都是唯讀。旗標與 `show` 相同：`--dot-id`（建議）或位置參數，預設是唯一的 dot。

```bash
chatgpt-dot-cli threads
chatgpt-dot-cli activity
chatgpt-dot-cli root-thread
chatgpt-dot-cli computers
chatgpt-dot-cli env
chatgpt-dot-cli automations
chatgpt-dot-cli email-status
```

`--json` 鍵：`status`、`body`、`info`。`info` 只有 email 回 403 且 `ineligible` 時是 true，此時結束碼為 0。文字模式會印 `email channel ineligible`。

`body` 裡常用的鍵：`threads` 的 `items`；`activity` 的 `data` 與 `next_cursor`；`computers` 的 `computers[]`（`display_name`、`is_attached`、`kind`、`local_computer_access_disabled_by_admin`；`signaling_url` 會被遮罩）；`env` 的 `status` 與 `capabilities[].type` / `status`；`automations` 的 `items`。

#### `by-thread`

```bash
chatgpt-dot-cli by-thread
```

| 旗標 | 預設 |
| --- | --- |
| 位置參數 `thread_id` | 該 dot 目前的 root thread |
| `--dot-id` | 唯一的 dot。只有省略 thread id 時才用到 |

`--json` 鍵：`status`、`body`。沒有 root thread 且沒給 id 時，結束碼 3，stderr 是 `dot has no active root thread`。

#### `messages`

不建立房間。只有 `--dot-id`，沒有位置參數。

```bash
chatgpt-dot-cli messages --limit 2
```

| 旗標 | 預設 | 限制 |
| --- | --- | --- |
| `--dot-id` | 唯一的 dot | 多個 dot 時必填 |
| `--limit` | 20 | 整數 1..32。超出範圍結束碼 2，不送請求 |
| `--before` | 無 | 一個訊息 id，只取更舊的一頁 |
| `--after` | 無 | 一個訊息 id，只取更新的一頁 |

不送 `cursor`，也不會自動翻頁。`--json` 鍵永遠是 `name`、`lines`、`messages`。沒有房間時兩個清單都是空的，並加上 `note`：`no messages yet (send creates the room)`，結束碼 0。`messages` 由舊到新，`lines` 由新到舊。`role` 永遠是 `user`，不能用來判斷是誰說的。說話者是 `dot:`、`you:` 或 `unknown:`。

#### `send`

唯一會寫入的指令。把文字傳進 dot 的訊息收件匣。

```bash
chatgpt-dot-cli send --help
chatgpt-dot-cli send -- "hello"
```

| 旗標 | 預設 |
| --- | --- |
| 位置參數 `text` | 必填。以 `-` 開頭時前面加 `--` |
| `--dot-id` | 唯一的 dot |

文字模式印 `sent to NAME`。`--json` 是遮罩後的新訊息物件，含 `id`。桌面版主畫面可能晚一點才顯示。

### 結束碼與錯誤訊息

| 結束碼 | 訊息 | 你該做的事 |
| --- | --- | --- |
| 0 | 成功。email 403 且 `ineligible` 也算成功，文字會有 `email channel ineligible` | 不用處理。這表示帳號不能用 email |
| 2 | 沒有子指令。印出說明 | 加上 `list` 或其他子指令 |
| 2 | `chatgpt-dot-cli: error: --auth requires a path` | `--auth` 後面加上檔案路徑 |
| 2 | `limit must be an integer from 1 to 32` | 把 `--limit` 改到 1..32 |
| 2 | `cannot read auth file: ... Run codex login with a ChatGPT account, or pass --auth PATH.` | 執行 `codex login`，或用 `--auth` 指到登入檔 |
| 2 | `auth file is not valid json` | 重新 `codex login` |
| 2 | `auth file is not a chatgpt login` | 用 ChatGPT 帳號登入，不要用 API key 登入檔 |
| 2 | `auth file has no access token` 或 `auth file has no account id` | 重新 `codex login` |
| 3 | `ChatGPT login expired (401). Open Codex or run codex login, then retry.` | 執行 `codex login` 再試 |
| 3 | `network error: ...` | 檢查網路後重試 |
| 3 | `response body was not JSON (likely Cloudflare)` | 等一下再試。`summary` 可改 `--no-activity` |
| 3 | `GET ... STATUS`，有時後面帶 API `code` | 看狀態碼。401 重新登入；403/429/503 稍後再試 |
| 3 | `dot id was not found; run chatgpt-dot-cli list and pass --dot-id` | 用 `list` 的 id |
| 3 | `more than one dot; run chatgpt-dot-cli list and pass --dot-id <id>` | 加上 `--dot-id` |
| 3 | `no dot on this account` | 先在 ChatGPT 建立 dot |
| 3 | `dot has no active root thread` | `by-thread` 改傳 thread id，或先開一個對話 |
| 3 | `message text is empty` | `send` 要有文字 |
| 0 | stderr：`messaging_room_preview has no aeon member` | 說話者標成 `unknown:`。不是失敗 |

### 檔案、環境變數、快取、遮罩

CLI 沒有設定檔，只讀一個環境變數：`CODEX_HOME`，用法跟 Codex 一樣。唯一讀取的檔案是登入檔：

| 系統 | 路徑 |
| --- | --- |
| Linux | `$HOME/.codex/auth.json` |
| macOS | `$HOME/.codex/auth.json` |
| Windows | `%USERPROFILE%\.codex\auth.json` |
| 設了 `CODEX_HOME` | `$CODEX_HOME/auth.json` |

CLI 不寫入這個檔、不改權限、不在磁碟上做快取，所以沒有檔案鎖。Linux 與 macOS 會看 Unix 權限位，但權限位不會讓讀取失敗。Windows 不檢查 Unix 權限位（那裡用的是 ACL）。Windows 主控台會把 stdout/stderr 設成 UTF-8（`errors=replace`），換行是 LF。

MCP 的 `list` 快取只活在該程序裡，15 秒，`dot_send` 之後清掉。

`--json` 會遮罩鍵名符合 `token`、`secret`、`key`、`cookie`、`authorization`、`password`、`session` 的欄位，以及精確鍵名 `email`、`account_id`、`user_id`、`signaling_url`、`magic_link_url`、`magic_link_share_text`、`inspector_url`。`account_user_id`、`id`、`aeon_id`、`created_at`、`content`、`preview`、`display_name`、`kind`、`is_attached` 不會因為這個清單被遮罩。

### 安全

除了 `send` 以外都是唯讀。`send` 只會 POST 文字訊息；若還沒有房間，會一併打開訊息房間。

這個工具不會：暫停、恢復、刪除 dot，連接或中斷電腦，申請 email，使用語音，或呼叫 `/ps/orbit`。

### 疑難排解

- 找不到指令：Linux/macOS 把 `$HOME/.local/bin` 加入 PATH；Windows 新開終端機，或用 `%USERPROFILE%\.local\bin`。
- 登入檔不在：執行 `codex login`。結束碼 2。
- `--limit 33` 或 `0`：結束碼 2，沒有發出請求。
- `summary` 很慢，或 activity 是空的：改跑 `chatgpt-dot-cli summary --no-activity`。
- 非 JSON 的 403/429/503：多半是 Cloudflare。CLI 會重試一次，然後結束碼 3。
- email 403 `ineligible`：正常，結束碼 0。
- 多個 dot：每個讀取都加 `--dot-id`。`messages` 與 `send` 只有 `--dot-id`。
- 要 dot 操作你的電腦：ChatGPT 桌面版仍要開著。

### MCP 與 trinity-cli

MCP 是可選的。stdio 指令是 `chatgpt-dot-cli-mcp`。它只讀預設登入檔。

```bash
uv tool install --force "chatgpt-dot-cli[mcp] @ git+https://gitlab.com/aa22396584/chatgpt-dot-cli.git@v0.2.2"
```

從這個 repo 的工作目錄：

```bash
uv pip install -e ".[mcp]"
```

沒裝 MCP 套件時，`chatgpt-dot-cli-mcp` 以結束碼 1 離開，並印出上面兩行。

跨 agent（同時問三個、交接、摘要）用 [trinity-cli](https://gitlab.com/aa22396584/trinity-cli)。

給 agent 的 skill：Linux 與 macOS 可以把 tag `v0.2.2` clone 到 `$HOME/.local/share/chatgpt-dot-cli`。目錄已存在時改為 `fetch --tags` 再 `checkout --detach`。目標已存在而且不是 symlink 時，stderr 印跳過，不覆蓋。clone 失敗不會建立連結。

```bash
src="$HOME/.local/share/chatgpt-dot-cli"
if [ -d "$src/.git" ]; then
  git -C "$src" fetch --tags origin &&
  git -C "$src" checkout --detach v0.2.2
else
  git clone --branch v0.2.2 https://gitlab.com/aa22396584/chatgpt-dot-cli.git "$src"
fi && [ -f "$src/skills/chatgpt-dot-cli/SKILL.md" ] &&
for d in "$HOME/.claude/skills" "$HOME/.codex/skills" "$HOME/.agents/skills" \
         "$HOME/.config/opencode/skills" "$HOME/.config/opencode/skill" \
         "$HOME/.cursor/skills" "$HOME/.grok/skills"; do
  mkdir -p "$d" || exit 1
  dest="$d/chatgpt-dot-cli"
  if [ -e "$dest" ] && [ ! -L "$dest" ]; then
    echo "chatgpt-dot-cli: skip $dest (exists and is not a symlink)" >&2
    continue
  fi
  ln -sfn "$src/skills/chatgpt-dot-cli" "$dest"
done
```

Windows 沒有這組 symlink。把 `skills\chatgpt-dot-cli` 複製到該 agent 的 skill 目錄即可。

本機測試：

```bash
python3 -m unittest discover -s tests -q
```

CI：預設使用 GitLab.com 的 runner。Linux 跑 Python 3.11、3.12、3.13。Windows 在 tag、手動執行，以及 main 上改到程式、測試或打包檔時跑 Python 3.12。維護者可設定 CI/CD 變數 `LINUX_RUNNER_TAG` 與 `WINDOWS_RUNNER_TAG`，把 job 指到自己的 runner。macOS 沒有 CI。推上 tag 會建立 GitLab Release，並附上 wheel 與 sdist。MIT 授權，見 [LICENSE](LICENSE)。

### 隱私

- 這個 CLI 只連 `chatgpt.com`，用你自己的 ChatGPT 登入。沒有遙測，也不在磁碟上存任何東西。
- 登入檔只讀不寫，token 不會印出來。`--json` 會遮罩上面列的欄位。
- 文字輸出和 `--json` 仍然有訊息內容、dot 名稱和 id。貼到 issue 前先刪掉。

### 平台

| 系統 | Python | 驗證方式 |
| --- | --- | --- |
| Linux | 3.11、3.12、3.13 | GitLab CI：離線單元測試 |
| Windows | 3.12 | GitLab CI：同一套測試，改到程式、測試或打包設定時自動跑 |
| macOS | 3.11、3.12、3.13 | 維護者本機：同一套測試，加上照這份 README 從 tag 安裝的首次使用檢查 |

測試不連 ChatGPT。macOS 沒有 CI。

### 參與開發

見 [CONTRIBUTING.md](CONTRIBUTING.md)。安全問題照 [SECURITY.md](SECURITY.md) 回報，不要開公開 issue。

### 相關專案

- trinity-cli — 一個 CLI 管三個常駐 agent（Your dot、Grok Bot、Muse）：<https://gitlab.com/aa22396584/trinity-cli>
- chatgpt-dot-cli — ChatGPT Your dot（這個 repo）：<https://gitlab.com/aa22396584/chatgpt-dot-cli>
- grok-bot-cli（fork，`gbot`）— Grok Bot：<https://gitlab.com/aa22396584/grok-bot-cli>
- muse-web-cli — 透過網頁使用 Meta Muse：<https://gitlab.com/aa22396584/muse-web-cli>

---

## English

### What it is

`chatgpt-dot-cli` is a local client for the official ChatGPT Your dot, not a second dot. It is for someone who already logs in with ChatGPT and wants to check that same dot, read messages, and send text from a terminal. The desktop app calls the dot orbit; the HTTP resource is tbo.

"Your dot" is the default name, shown when `display_name` is empty. After you rename the dot in the ChatGPT app, the CLI prints the new name.

This repo is public. It needs Python 3.11, 3.12, or 3.13. Install with uv or pipx. Auth comes from the Codex ChatGPT login file. This CLI does not have its own account flow.

Unofficial: this is a personal project, not affiliated with, endorsed by, or supported by OpenAI. It calls the undocumented interfaces the ChatGPT app uses, and OpenAI can change them at any time. Automated use may break OpenAI's terms; any account risk is yours.

Supported systems: see [Platforms](#platforms).

### Install

Pinned to tag `v0.2.2`.

Linux or macOS:

```bash
uv tool install git+https://gitlab.com/aa22396584/chatgpt-dot-cli.git@v0.2.2
chatgpt-dot-cli --version
```

Or:

```bash
pipx install git+https://gitlab.com/aa22396584/chatgpt-dot-cli.git@v0.2.2
chatgpt-dot-cli --version
```

The command must be on PATH. uv and pipx put it in `$HOME/.local/bin`.

Windows (PowerShell):

```powershell
irm https://astral.sh/uv/install.ps1 | iex
uv tool install "git+https://gitlab.com/aa22396584/chatgpt-dot-cli.git@v0.2.2"
chatgpt-dot-cli --version
```

On Windows the executable is `%USERPROFILE%\.local\bin\chatgpt-dot-cli.exe`. Open a new terminal so PATH updates. pipx works too:

```powershell
py -3.12 -m pip install --user pipx
pipx install "git+https://gitlab.com/aa22396584/chatgpt-dot-cli.git@v0.2.2"
chatgpt-dot-cli --version
```

`--version` prints `chatgpt-dot-cli 0.2.2`.

The GitLab Release also attaches a platform-independent wheel and sdist. Install the wheel with pip:

```bash
python3 -m pip install "https://gitlab.com/api/v4/projects/aa22396584%2Fchatgpt-dot-cli/packages/generic/chatgpt-dot-cli/v0.2.2/chatgpt_dot_cli-0.2.2-py3-none-any.whl"
```

To upgrade, install that tag again. `uv tool upgrade` will not move an install that is pinned to a tag.

```bash
uv tool install --force git+https://gitlab.com/aa22396584/chatgpt-dot-cli.git@v0.2.2
```

```powershell
uv tool install --force "git+https://gitlab.com/aa22396584/chatgpt-dot-cli.git@v0.2.2"
```

Uninstall:

```bash
uv tool uninstall chatgpt-dot-cli
pipx uninstall chatgpt-dot-cli
```

```powershell
uv tool uninstall chatgpt-dot-cli
```

### First-time setup

1. Install the [Codex CLI](https://github.com/openai/codex) and run `codex login` with a ChatGPT account.
2. The login file lives at:
   - Linux: `$HOME/.codex/auth.json`
   - macOS: `$HOME/.codex/auth.json`
   - Windows: `%USERPROFILE%\.codex\auth.json`
   - When `CODEX_HOME` is set, Codex and this CLI both use `$CODEX_HOME/auth.json` instead.
3. If the file is somewhere else, pass `--auth PATH` to the CLI (`~` works). MCP has no `--auth` flag and reads only the default path above.
4. Confirm it works with a read-only command (a few seconds):

```bash
chatgpt-dot-cli list
```

Success prints one line per dot and ends with `N dot(s)`. Do not paste that file into chat. Tokens are never printed.

### Quick start

The commands you will use most are `list`, `messages`, `usage`, and `summary --no-activity`. `send` really does send; the block below only shows the shape of the output.

```text
$ chatgpt-dot-cli list
id=dot_example Example status=active paused=False kind=orbit
1 dot(s)

$ chatgpt-dot-cli messages --limit 2
Example messages=2
dot: example reply
you: example question

$ chatgpt-dot-cli usage
200 GET /wham/usage plan_type=example

$ chatgpt-dot-cli summary --no-activity
plan_type=example
primary available=true
Example status=active paused=False kind=orbit threads=1 activity=skipped computers=1 automations=0 environment=connected email=ineligible
  dot: example reply

$ chatgpt-dot-cli send -- "hello"
sent to Example
```

In text mode, `usage`, `show`, and the other read commands print field types, not secret values. The `--json` samples in the reference use fake values.

### Command reference

Global flags:

| Flag | Default | Notes |
| --- | --- | --- |
| `--version` |  | print the version and exit |
| `--auth PATH` | `$CODEX_HOME/auth.json`, or `.codex/auth.json` in the home directory when `CODEX_HOME` is unset | required when the flag is present |
| `--json` | off | redacted JSON. Before or after the subcommand, not after a standalone `--` |

With no subcommand the CLI prints help and exits 2. It does not call the API.

#### `summary`

Plan, dot status, and recent messages. Activity is fetched unless you skip it.

```bash
chatgpt-dot-cli summary --no-activity
```

| Flag | Default |
| --- | --- |
| `--no-activity` | off (activity is fetched) |

`--json` keys: `plan_type`, `usage_http`, `primary_http`, `primary`, `dots`. Each dot has `id`, `name`, `status`, `paused`, `kind`, `threads`, `threads_http`, `activity`, `activity_http`, `computers`, `computers_http`, `automations`, `automations_http`, `environment`, `environment_http`, `email`, `recent`. With `--no-activity`, `activity` and `activity_http` are null and the text line says `activity=skipped`.

#### `usage`

```bash
chatgpt-dot-cli usage
```

No flags of its own. `--json` keys: `status`, `body`. Useful keys inside `body`: `plan_type`, `rate_limit` (including `allowed`), `limit_reached`, `primary_window` (including `used_percent`), `reset_after_seconds`. Other fields may be present. Secrets are redacted.

#### `primary`

```bash
chatgpt-dot-cli primary
```

No flags of its own. `--json` keys: `status`, `body`.

#### `list`

```bash
chatgpt-dot-cli list
```

No flags of its own. Text is `id=... name status= paused= kind=` and then `N dot(s)`. `--json` is an array of redacted dot objects. Useful keys: `id`, `display_name`, `status`, `is_paused`, `aeon_kind`.

#### `probe`

HTTP status and field names for every read.

```bash
chatgpt-dot-cli probe
```

No flags of its own. `--json` keys: `usage_http`, `plan_type`, `primary_http`, `list_http`, `dots`. Each dot has `name`, `status`, `paused`, `kind`, `reads` (`path`, `status`, and `items` on the message read).

#### `show`

```bash
chatgpt-dot-cli show
```

| Flag | Default |
| --- | --- |
| `--dot-id` | the only dot on the account |
| positional `dot_id` | same. Prefer `--dot-id` |

`--json` keys: `status`, `body`.

#### `threads`, `activity`, `root-thread`, `computers`, `env`, `automations`, `email-status`

All read-only. Same flags as `show`: `--dot-id` (preferred) or a positional id. Default: the only dot.

```bash
chatgpt-dot-cli threads
chatgpt-dot-cli activity
chatgpt-dot-cli root-thread
chatgpt-dot-cli computers
chatgpt-dot-cli env
chatgpt-dot-cli automations
chatgpt-dot-cli email-status
```

`--json` keys: `status`, `body`, `info`. `info` is true only when email returns 403 `ineligible`, and that case exits 0. Text mode prints `email channel ineligible`.

Useful keys inside `body`: `items` for `threads`; `data` and `next_cursor` for `activity`; `computers[]` (`display_name`, `is_attached`, `kind`, `local_computer_access_disabled_by_admin`; `signaling_url` is redacted) for `computers`; `status` and `capabilities[].type` / `status` for `env`; `items` for `automations`.

#### `by-thread`

```bash
chatgpt-dot-cli by-thread
```

| Flag | Default |
| --- | --- |
| positional `thread_id` | the dot's active root thread |
| `--dot-id` | the only dot. Used only when the thread id is omitted |

`--json` keys: `status`, `body`. If there is no root thread and you omit the id, exit 3 and stderr says `dot has no active root thread`.

#### `messages`

Does not create a room. `--dot-id` only; there is no positional id.

```bash
chatgpt-dot-cli messages --limit 2
```

| Flag | Default | Limit |
| --- | --- | --- |
| `--dot-id` | the only dot | required when there is more than one |
| `--limit` | 20 | integer 1..32. Outside that range exits 2 and sends no request |
| `--before` | none | one message id; one older page, then stop |
| `--after` | none | one message id; one newer page, then stop |

The CLI does not send `cursor` and does not follow further pages. `--json` keys are always `name`, `lines`, and `messages`. With no room both lists are empty and `note` is `no messages yet (send creates the room)`; exit 0. `messages` is oldest to newest. `lines` is newest first. `role` is always `user` and does not say who spoke. Speakers are `dot:`, `you:`, or `unknown:`.

#### `send`

The only command that writes. It posts text into the dot's messaging inbox.

```bash
chatgpt-dot-cli send --help
chatgpt-dot-cli send -- "hello"
```

| Flag | Default |
| --- | --- |
| positional `text` | required. Put `--` before text that starts with `-` |
| `--dot-id` | the only dot |

Text mode prints `sent to NAME`. `--json` is the redacted created message, including `id`. The desktop main view can show it a little later.

### Exit codes and error messages

| Exit | Message | What to do |
| --- | --- | --- |
| 0 | Success. Email 403 `ineligible` is also success and prints `email channel ineligible` | Nothing. That account cannot use email |
| 2 | No subcommand. Help is printed | Add `list` or another subcommand |
| 2 | `chatgpt-dot-cli: error: --auth requires a path` | Pass a path after `--auth` |
| 2 | `limit must be an integer from 1 to 32` | Use `--limit` from 1 to 32 |
| 2 | `cannot read auth file: ... Run codex login with a ChatGPT account, or pass --auth PATH.` | Run `codex login`, or point `--auth` at the login file |
| 2 | `auth file is not valid json` | Run `codex login` again |
| 2 | `auth file is not a chatgpt login` | Log in with a ChatGPT account, not an API-key file |
| 2 | `auth file has no access token` or `auth file has no account id` | Run `codex login` again |
| 3 | `ChatGPT login expired (401). Open Codex or run codex login, then retry.` | Run `codex login`, then retry |
| 3 | `network error: ...` | Check the network and retry |
| 3 | `response body was not JSON (likely Cloudflare)` | Wait and retry. For `summary`, use `--no-activity` |
| 3 | `GET ... STATUS`, sometimes with an API `code` | 401: log in again. 403/429/503: retry later |
| 3 | `dot id was not found; run chatgpt-dot-cli list and pass --dot-id` | Use an id from `list` |
| 3 | `more than one dot; run chatgpt-dot-cli list and pass --dot-id <id>` | Pass `--dot-id` |
| 3 | `no dot on this account` | Create a dot in ChatGPT first |
| 3 | `dot has no active root thread` | Pass a thread id to `by-thread`, or open a chat first |
| 3 | `message text is empty` | `send` needs text |
| 0 | stderr: `messaging_room_preview has no aeon member` | Lines say `unknown:`. This is not a failure |

### Files, environment, cache, redaction

The CLI has no config file and reads one environment variable, `CODEX_HOME`, the same way Codex does. The only file it reads is the login file:

| System | Path |
| --- | --- |
| Linux | `$HOME/.codex/auth.json` |
| macOS | `$HOME/.codex/auth.json` |
| Windows | `%USERPROFILE%\.codex\auth.json` |
| `CODEX_HOME` set | `$CODEX_HOME/auth.json` |

The CLI does not write that file, does not change its permissions, and does not keep a disk cache, so it takes no file lock. On Linux and macOS it can see Unix mode bits, and those bits never block a read. On Windows it does not check Unix mode bits (Windows uses ACLs). On Windows, stdout and stderr are set to UTF-8 with `errors=replace`, and newlines are LF.

The MCP `list` cache lives only in that process, for 15 seconds, and is cleared after `dot_send`.

`--json` redacts keys whose names match `token`, `secret`, `key`, `cookie`, `authorization`, `password`, or `session`, plus the exact keys `email`, `account_id`, `user_id`, `signaling_url`, `magic_link_url`, `magic_link_share_text`, and `inspector_url`. `account_user_id`, `id`, `aeon_id`, `created_at`, `content`, `preview`, `display_name`, `kind`, and `is_attached` are not redacted by that list.

### Safety

Every command is read-only except `send`. `send` POSTs a text message. If there is no room yet, it also opens the messaging room.

This tool never pauses, resumes, or deletes a dot, never connects or disconnects a computer, never claims email, never uses voice, and never calls `/ps/orbit`.

### Troubleshooting

- Command not found: on Linux or macOS add `$HOME/.local/bin` to PATH. On Windows open a new terminal, or call `%USERPROFILE%\.local\bin`.
- Auth file missing: run `codex login`. Exit 2.
- `--limit 33` or `0`: exit 2, and no request is sent.
- `summary` is slow, or activity comes back empty: run `chatgpt-dot-cli summary --no-activity`.
- A non-JSON 403, 429, or 503 is usually Cloudflare. The CLI retries once, then exits 3.
- Email 403 `ineligible` is normal and exits 0.
- More than one dot: pass `--dot-id` on each read. `messages` and `send` accept only `--dot-id`.
- For the dot to work on your computer, the ChatGPT desktop app still has to be open.

### MCP and trinity-cli

MCP is optional. The stdio command is `chatgpt-dot-cli-mcp`. It reads only the default login file.

```bash
uv tool install --force "chatgpt-dot-cli[mcp] @ git+https://gitlab.com/aa22396584/chatgpt-dot-cli.git@v0.2.2"
```

From a checkout of this repo:

```bash
uv pip install -e ".[mcp]"
```

If the MCP package is missing, `chatgpt-dot-cli-mcp` exits 1 and prints those two lines.

For cross-agent work (ask all three, hand off, digest) use [trinity-cli](https://gitlab.com/aa22396584/trinity-cli).

Agent skill install on Linux and macOS: clone tag `v0.2.2` to `$HOME/.local/share/chatgpt-dot-cli`. If that checkout already exists, it runs `fetch --tags` and `checkout --detach`. If a target already exists and is not a symlink, the script prints a skip message on stderr and leaves it alone. A failed clone creates no links.

```bash
src="$HOME/.local/share/chatgpt-dot-cli"
if [ -d "$src/.git" ]; then
  git -C "$src" fetch --tags origin &&
  git -C "$src" checkout --detach v0.2.2
else
  git clone --branch v0.2.2 https://gitlab.com/aa22396584/chatgpt-dot-cli.git "$src"
fi && [ -f "$src/skills/chatgpt-dot-cli/SKILL.md" ] &&
for d in "$HOME/.claude/skills" "$HOME/.codex/skills" "$HOME/.agents/skills" \
         "$HOME/.config/opencode/skills" "$HOME/.config/opencode/skill" \
         "$HOME/.cursor/skills" "$HOME/.grok/skills"; do
  mkdir -p "$d" || exit 1
  dest="$d/chatgpt-dot-cli"
  if [ -e "$dest" ] && [ ! -L "$dest" ]; then
    echo "chatgpt-dot-cli: skip $dest (exists and is not a symlink)" >&2
    continue
  fi
  ln -sfn "$src/skills/chatgpt-dot-cli" "$dest"
done
```

Windows has no matching symlink loop. Copy `skills\chatgpt-dot-cli` into the agent's skill directory.

Run the tests locally:

```bash
python3 -m unittest discover -s tests -q
```

CI: jobs use GitLab.com runners by default. Linux runs on Python 3.11, 3.12, and 3.13. Windows runs Python 3.12 on tags, manual runs, and main commits that change code, tests, or packaging. Maintainers can point jobs at their own runners by setting the CI/CD variables `LINUX_RUNNER_TAG` and `WINDOWS_RUNNER_TAG`. There is no macOS CI. Pushing a tag creates a GitLab Release and attaches the wheel and sdist. MIT, see [LICENSE](LICENSE).

### Privacy

- The CLI talks only to `chatgpt.com`, with your own ChatGPT login. There is no telemetry, and nothing is stored on disk.
- The login file is read, never written, and tokens are never printed. `--json` redacts the fields listed above.
- Text output and `--json` still contain message text, dot names, and ids. Remove them before pasting into an issue.

### Platforms

| OS | Python | How it was checked |
| --- | --- | --- |
| Linux | 3.11, 3.12, 3.13 | GitLab CI: the offline unit suite |
| Windows | 3.12 | GitLab CI: the same suite, run automatically when code, tests, or packaging change |
| macOS | 3.11, 3.12, 3.13 | Maintainer machine: the same suite, plus a first-run check that installs from the tag as this README says |

The tests do not contact ChatGPT. There is no macOS CI.

### Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Report security problems as described in [SECURITY.md](SECURITY.md), not in a public issue.

### Related projects

- trinity-cli — one CLI over three always-on agents (Your dot, Grok Bot, Muse): <https://gitlab.com/aa22396584/trinity-cli>
- chatgpt-dot-cli — ChatGPT Your dot (this repo): <https://gitlab.com/aa22396584/chatgpt-dot-cli>
- grok-bot-cli (fork, `gbot`) — Grok Bot: <https://gitlab.com/aa22396584/grok-bot-cli>
- muse-web-cli — Meta Muse via the web: <https://gitlab.com/aa22396584/muse-web-cli>
