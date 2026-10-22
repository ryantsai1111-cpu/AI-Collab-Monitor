# 交付規格書 — Codync 內建 Hermes Agent 支援（上游 PR）

> 對象：Codex。**本文件自足。** 這次的目標 repo 不是 AI-Collab-Workspace，而是 Ryan fork 的 **Codync**（leepokai/Codync，Rust host + Electron 桌面 + iOS 的「把本機 coding agent 當 bot」工具，Apache 2.0）。
> 本機 clone：`C:\Users\ryant\Desktop\Codync`。remote `origin` = 上游 leepokai/Codync（只能讀），remote `fork` = ryantsai1111-cpu/Codync（可推）。分支 `feat/hermes-harness` 已從 `origin/dev` 切好並 checkout，工作樹乾淨。**直接在這個 clone 工作，不要再開 worktree**；上游 PR 一律對 `dev`，不對 `main`。
> 先讀 `AGENTS.md`、`CLAUDE.md`、`docs/architecture/file-structure.md`，那是上游的規矩（Conventional Commits、測試指令、PR 範本）。

---

## 0. 背景與決策

Hermes Agent（NousResearch，本機跑 Qwen 的 agent，執行檔 `%LOCALAPPDATA%\hermes\hermes-agent\.hermes\bin\hermes.exe`）有自己的 ACP 模式：`hermes acp`（`hermes acp --check` 驗證依賴，`hermes acp --setup` 設定 provider/model）。2026-10-18 Ryan 在這台 Windows 上用 Codync v2.17.5 的 `backend: "custom"` + `command: "\"…\\hermes.exe\" acp"` 建了一個 bot，第一則訊息就正常：Hermes 用 terminal 工具列目錄、以繁體中文回覆、turn 正常結束，不需要任何 host 改動。

決策：把 Hermes 做成 Codync 的**內建 harness**，讓它像 Qwen Code 一樣被自動偵測、在 bot 編輯器裡直接選，而不用手填 custom command。範圍只有這件事；`send --wait` 之類的 CLI 是下一份規格。

## 1. 不變量（上游的規矩，沒商量）

1. 只動 `host/src/agent/backends.rs`（加 harness 與偵測目錄）、其測試、以及必要的文件（見 Task B）。不動 `apps/`、`cloud/`、`relay/`、`web/`。
2. **不做版本 bump**：`AGENTS.md` 的 bump 規則需要 `xcodegen generate`，Windows 上沒有；PR 說明裡寫明「version bump left to maintainers (xcodegen not available on Windows)」。
3. commit 訊息：Conventional Commits，英文、小寫祈使句、主旨 ≤72 字，scope 用 `host`／`docs`，例如 `feat(host): detect Hermes Agent and run it over acp`。一個邏輯改動一個 commit。
4. 不碰 `.githooks` 以外的 CI 設定；可以 `git config core.hooksPath .githooks` 啟用上游的 pre-commit。
5. 不要 push `origin`，只 push `fork`；PR 用 `gh pr create --repo leepokai/Codync --base dev --head ryantsai1111-cpu:feat/hermes-harness`，照 `.github/pull_request_template.md`（Summary / Validation / What's New）寫。
6. 不要 push main、不要 force push、不要 rebase 已推出去的 commit。

## 2. 現況與整合點

- `host/src/agent/backends.rs:18-35`：`Harness { id, name, bins, local, registry, setup, install, login, signed_in }`；`Install` enum 在 `:38-45`（`Script`／`Scripts { unix, windows }`／`Npm`）。
- `:85-437` `HARNESSES` 內建約 28 個 agent；**照 Qwen Code 的寫法**（`:204-217`）：`bins: &["qwen"]`, `local: Some("{bin} --acp")`, `registry: Some("qwen-code")`, `setup`, `install: Some(Install::Scripts{…})`, `login: "{bin}"`, `signed_in: None`。
- `:440` `by_id`、`:563-614` `list()`（API `refreshBackends` 的資料來源）、`:636` 登入檢查、`:667-668` bin 名稱衝突規則。
- 偵測：`:445-523` `hydrate_path` 把登入 shell 的 PATH 加上常見目錄；`:458-470` 的額外目錄清單，Windows 分支目前加 `%APPDATA%\npm`、`Program Files\nodejs`、`%LOCALAPPDATA%\omp`；之後對每個 home-relative 的 `rel`（`.local/bin` 等）也會加。`:525-542` `which()` 在 Windows 補 `.exe/.cmd/.bat`。
- 啟動：`host/src/agent/bot/session.rs:342-351` 有 `cfg.command` 就用它，否則 `backends.rs:677-697` 以 `local` 優先、registry 後備；ACP initialize 在 `session.rs:398-447`，client 回報 `fs`/`terminal` 都是 false（Hermes 自己有 terminal 工具，今天實測可用）。
- 測試：`backends.rs:742-775` 有 `detects_executables_on_search_path`（unix only）與 `every_harness_is_unique`。
- Hermes 事實（這台機器）：執行檔在 `%LOCALAPPDATA%\hermes\hermes-agent\.hermes\bin\hermes.exe`，**不在 PATH**；`hermes acp --help` 的選項：`--accept-hooks`、`--version`、`--check`、`--setup`、`--setup-browser`、`--yes`。官方文件 https://hermes-agent.nousresearch.com/docs/ ；安裝指令與 macOS／Linux 的安裝路徑**請到官方文件查證後再填**（不要憑印象），查不到就 `install: None` 並在 `setup` 文字寫「依官方文件安裝」。
- 上游的 host 測試指令：`cd host && cargo fmt --check && cargo clippy --all-targets -- -D warnings && cargo test`（`AGENTS.md:23-27`）。這台機器**還沒有 Rust 工具鏈與 MSVC 連結器**（見 Task C）。

---

## Task A：加 Hermes harness

**要求**：
1. 在 `HARNESSES` 加一筆（放在 Qwen Code 附近，順序照現有的分組慣例）：
   - `id: "hermes"`, `name: "Hermes Agent"`, `bins: &["hermes"]`, `local: Some("{bin} acp")`, `registry: None`（ACP registry 沒有 Hermes；若查證後有，填正確 id）。
   - `setup`: 一句英文，說明安裝 Hermes 並執行 `hermes acp --setup` 選 provider／模型；`login: "{bin} acp --setup"`；`signed_in: None`。
   - `install`: 依官方文件；Windows 若有 PowerShell 安裝指令就用 `Install::Scripts`，否則 `None`。
2. 偵測目錄：Windows 分支加 `%LOCALAPPDATA%\hermes\hermes-agent\.hermes\bin`（用 `dirs::data_local_dir()`），並依官方文件加 macOS／Linux 的安裝目錄（例如 `~/.hermes/bin`，要查證）；寫在既有的註解風格裡。
3. 確認 `bins` 名稱 `hermes` 不和現有 harness 衝突（`:667-668` 的規則），`every_harness_is_unique` 仍過。
4. 新增一個測試：`HARNESSES` 裡 `hermes` 的 `local` 以 `{bin}` 開頭且含 `acp`；若你加了跨平台的偵測目錄，寫一個不依賴真實安裝的單元測試驗證該目錄被納入搜尋清單（看 `hydrate_path` 能不能被注入，不能就說明為什麼不測）。

**驗收**：
- `cargo test -p codync-host backends`（或整個 `cargo test`）通過；`cargo fmt --check`、`cargo clippy --all-targets -- -D warnings` 乾淨。
- 本機實測：用剛建好的 host（Task C）跑 `POST /api/refreshBackends`，回傳裡 `id: "hermes"` 的 `installed: true`、`path` 指到 hermes.exe、`command: "{bin} acp"`。
- 用 API `createBot {name:"Hermes-builtin", backend:"hermes", cwd:"<任一存在的資料夾>", permission:"ask"}` 建 bot（**不填 command**），`send` 一句「請用一句話自我介紹並列出目前目錄的檔案，不要修改任何檔案」，`history` 裡出現 `kind: agent` 且 `data.final: true` 的回覆。API 用法：token 在 `%USERPROFILE%\.codync\token`，`POST http://127.0.0.1:19222/api/<method>`，header `Authorization: Bearer <token>`，JSON body；範例見 `docs/guides/windows-testing.md:35-45` 與 `host/src/main.rs:583-600`。

## Task B：文件

**要求**：找出上游列舉「支援的 agent」的地方（`README.md`、`docs/`、`web/`；用 grep 找 `Qwen Code` 或 `oh-my-pi`），若有清單就加 Hermes Agent 一列；沒有清單就只在 `docs/` 裡與 agent／backend 相關的頁面加一段 Hermes 的說明（安裝位置、`hermes acp --setup`、Windows 路徑）。不要新開一整頁。

**驗收**：`git diff --stat` 列出改了哪些文件；文字是英文（上游語言）。

## Task C：本機 Rust 工具鏈（為了跑驗收）

**要求**：
1. 檢查 `cargo --version`；沒有就用官方 `rustup-init.exe`（https://win.rustup.rs/x86_64 ，下載到一個新的空目錄）安裝：`rustup-init.exe -y --default-toolchain none`，之後在 `host/` 目錄跑 `cargo --version` 會依 `rust-toolchain.toml` 自動裝 1.99.0。
2. MSVC 連結器：`where link.exe` 若只找到 Git 的 `link.exe`，用 `winget install --id Microsoft.VisualStudio.2022.BuildTools --override "--quiet --wait --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"` 安裝（會跳 UAC，請 Ryan 按允許；要幾 GB，先在回報裡講一聲）。裝完開新 shell 再試 `cargo build`。
3. 若工具鏈實在裝不起來：仍完成 Task A、B，把 PR 開出去讓上游 CI（`.github/workflows/host.yml` 跑 ubuntu/macos/windows）驗，並在 PR 的 Validation 誠實寫明本機沒跑過 cargo 的原因；Task A 的 API 實測改用 Codync 已安裝的 v2.17.5 host 配 `backend: custom` 證明 ACP 路徑可用（那個已經驗過，可引用）。

## 3. 交付總回報格式

每個 Task 一節：改了哪些檔（路徑:行號）、驗收逐條 PASS/FAIL 附執行輸出原文（cargo 三個指令、refreshBackends 的 hermes 那段 JSON、bot 回覆）、未盡事項。最後附 `git log --oneline origin/dev..HEAD`、PR 連結、PR 內文的 Validation 段落原文。過不了的明講卡在哪，不要寫「大致完成」。

## 4. 不做

- 不做 `send --wait` 或任何 CLI／API 新功能（下一份規格）。
- 不改 bot 編輯器 UI（內建 harness 會自動出現在下拉，若實測沒出現再回報）。
- 不 bump 版本、不動 `apps/`。
- 不 push `origin`、不對 `main` 開 PR。
