# 交付規格書 — Codync `codync-host send --wait`（上游 PR，第二份）

> 對象：Codex。**本文件自足。** 目標 repo 是 Ryan fork 的 **Codync**（leepokai/Codync）。本機 clone：`C:\Users\ryant\Desktop\Codync`；remote `origin` = 上游（只讀），`fork` = ryantsai1111-cpu/Codync（可推）。
> 分支 **`feat/cli-send-wait`** 已從 `origin/dev`（`abd7ba43`）切好並 checkout，工作樹乾淨。**直接在這個 clone 工作，不開 worktree**。它和上一個 PR（#157，`feat/hermes-harness`）互相獨立，不要合併或 cherry-pick 那個分支。
> 先讀 `AGENTS.md`、`CLAUDE.md`、`docs/architecture/file-structure.md`、`docs/guides/windows-testing.md`。Rust 1.99.0 與 MSVC Build Tools 已在上一份任務裝好；cargo 在 `%USERPROFILE%\.cargo\bin`，在 `host\` 目錄執行會自動用 `rust-toolchain.toml` 的版本。

---

## 0. 背景與決策

Codync 的 host 有完整的本機 HTTP API（`POST http://127.0.0.1:<port>/api/<method>`，`Authorization: Bearer <~/.codync/token>`），但 CLI 沒有「送一句話給 bot 並等它做完」的非互動指令；`tui` 是互動式。外部腳本（例如 Claude Code 透過 skill 派工、CI、排程）目前只能自己拼 HTTP 呼叫、輪詢 `history` 判斷 turn 結束。Ryan 的使用情境：Claude 寫好規格後，用一行指令把它交給某個 bot（Codex、Hermes…），等完成，拿到最後回覆與結束狀態，再進入審查。

決策：新增 **`codync-host send`** 子命令，只用既有 API（`send`、`history`、bot 狀態），**不新增 API method、不改協定**，對 client（iOS／desktop）完全無影響，所以不需要 `minApp`／`minHost` 變動。

## 1. 不變量

1. 只動 `host/`：`host/src/main.rs`（子命令定義與分派）、可新增 `host/src/cli/send.rs`（或照 `docs/architecture/file-structure.md` 的慣例放）、`host/tests/`（新整合測試）、以及文件（Task C）。不動 `apps/`、`cloud/`、`relay/`、`web/`、API 路由與 store。
2. **不做版本 bump**（Windows 上沒有 xcodegen）；PR 說明寫「version bump left to maintainers (xcodegen not available on Windows)」。
3. Conventional Commits，英文、小寫祈使句、主旨 ≤72 字，scope `host`／`docs`，例：`feat(host): add a send command that can wait for the reply`。
4. 只 push `fork`；PR 用 `gh pr create --repo leepokai/Codync --base dev --head ryantsai1111-cpu:feat/cli-send-wait`，照 `.github/pull_request_template.md`。不 push main、不 force push。
5. 不要把 token 印到 stdout／stderr／log；錯誤訊息照 `local_call` 的風格。
6. **不要把任何個人路徑、使用者名稱、主機名寫進程式碼、測試、文件或 PR 內文**（測試用暫存目錄；文件用 `~/.codync`、`%USERPROFILE%` 這類通用寫法）。

## 2. 現況與整合點

- CLI：`host/src/main.rs:69` `#[derive(Subcommand)]` 的頂層 enum（`Serve`、`Pair`、`Info`、`Devices`、`Access`、`Cloud`、`Install`、`Uninstall`、`Stop`、`Update`、`Compat`、`Status`、`Statusline`、`ResetToken`、`Tui`…），各子命令的 `port: u16` 參數寫法照現有（例如 `Status { port }`）。分派在 `main.rs` 約 330-370 行，`Devices`／`Cloud` 等用 `local_call`。
- `host/src/main.rs:582-600` `local_call(port, method, body)`：讀 `service::data_dir()/token`、20 秒逾時、非 2xx 時把 `error` 欄位變成錯誤。**長等待不能用這個 20 秒逾時**：輪詢時每次呼叫各自 20 秒即可，總等待由 `--timeout` 控制。
- `send`：`host/src/api/bots.rs` 的 `"send" =>` 分支：參數 `botId`、`text`、`attachments?`、`threadId?`、`clientNonce?`；`clientNonce` 相同時回傳既有 entry（冪等）。回傳 `{entry}`，entry 有 `seq`、`turn`。
- `history`：參數 `botId`、`beforeSeq?`（缺省為最新）、`limit?`（1-500，預設 100）。回傳 `{entries}`，每個 entry 有 `seq`、`kind`（`user`／`agent`／`thought`／`tool`／`plan`／`permission`／`notice`，`host/src/store/model.rs:20-28`）、`turn`（`model.rs:179`）、`data`。最終回覆是 `kind: "agent"` 且 `data.final == true`（`host/src/agent/bot/turn.rs:223-235`）。
- turn 結束：`host/src/agent/bot/turn.rs:183-340` `finish_turn`：依 `stopReason`（`end_turn`／`cancelled`／`max_tokens`／`max_turn_requests`／`refusal`／錯誤）收尾，非正常結束會寫 `kind: notice`（`turn.rs:246-257` 的文字），最後把 bot 狀態設回 Idle 或 Error（`turn.rs:320-325`）。bot 狀態列舉在 `host/src/hub.rs:27-31`（`Idle`／`Working`／`NeedsInput`，另有 Error）。
- 核准：`permission: ask` 的 bot 會產生 `kind: permission`、`data.status: "pending"` 的 entry，bot 狀態變 `NeedsInput`（`host/src/agent/bot/updates.rs:158-192`）；回應用 `respondPermission`。
- 取得 bot 狀態與清單：找出 client 用來列 bot 與狀態的 API（`hello` 或 snapshot 類方法，看 `host/src/api/host.rs`、`host/src/hub.rs:349-376` 的 bot 事件）；若沒有直接「列 bots」的方法，就用 client 啟動時用的那個，並在回報寫明用了哪個。也可訂閱 SSE `GET /events?since=<rev>`（`host/src/api/http.rs:193-206`、`events.rs:55-93`），但輪詢 `history` 較簡單，**擇一，偏好輪詢**。
- 整合測試的寫法照 `host/tests/turns_e2e.rs`、`host/tests/team_e2e.rs`（用 `host/tests/fake_agent.py` 與 `fixtures/*.py` 當假的 ACP agent、在暫存 `CODYNC_HOME` 起 host）。

---

## Task A：`codync-host send`

**介面**：

```
codync-host send --bot <id-or-name> [--file <path> | <text>...] [--wait] [--timeout <secs>] [--json] [--thread <entryId>] [--port <port>]
```

- `--bot`：bot id，或名稱（完全相符、不分大小寫；多個同名時報錯並列出 id）。
- 訊息來源：位置參數的文字，或 `--file` 讀 UTF-8 檔（`-` 表示 stdin）。兩者都沒有就報錯。
- 每次呼叫產生一個 `clientNonce`（UUID），重試時重用，避免重送。
- 不加 `--wait`：送出後印出 entry 的 `seq` 與 `turn`，exit 0。
- `--wait`：送出後輪詢（每 1 秒，每次 `history` limit 100），直到這則訊息之後（`seq` 大於送出那則）的 turn 結束：
  - 結束條件：出現 `kind: agent` 且 `data.final == true` 的 entry，**且** bot 狀態回到 Idle（或 Error）；只看到 final 但 bot 仍 Working 時繼續等（同一 turn 可能還在收尾）。
  - bot 狀態變 `NeedsInput` 且有 pending permission：stderr 印一行 `waiting for approval: <title or command 摘要>`，**計時暫停**，直到該 card 不再 pending。
  - 非正常結束（turn 的 notice 是 Stopped／limit／declined／failed，或 bot 進 Error）：視為失敗。
  - `--timeout`（預設 1800 秒，不含等待核准的時間）到期：exit 4，印 `timed out after <n>s (the bot is still working; nothing was stopped)`，**不要**替使用者呼叫 `stop`。
- 輸出：
  - 預設：stdout 印最終回覆文字（`data.text`），結尾一個換行；其他資訊（核准等待、notice）走 stderr。
  - `--json`：stdout 印一行 JSON：`{"botId","entrySeq","turn","status":"completed|failed|timeout","stopReason"?, "reply"?, "notices":[…], "elapsedSeconds","waitedForApprovalSeconds"}`。
- 結束碼：`0` 完成；`1` 失敗（stop/limit/declined/error）；`2` 參數或找不到 bot；`3` host 沒在跑或 API 拒絕；`4` 逾時。在 `--help` 裡寫明。
- `--port` 預設與其他子命令相同（看 `environment.rs` 的預設埠，dev 版不同）。

**驗收（附執行輸出原文）**：
- `host/tests/send_cli_e2e.rs`（新）：用暫存 `CODYNC_HOME` 起 host，建一個用 fake agent 的 bot，至少涵蓋：
  1. `send --wait` 正常回覆 → exit 0、stdout 等於 fake agent 的最終文字。
  2. `--json` 的欄位與 `status: completed`。
  3. fake agent 回 `max_turn_requests` 或被 stop → exit 1、`status: failed`。
  4. `--timeout 2` 對一個會掛住的 fixture → exit 4，之後 bot 仍在 Working（沒有被停）。
  5. `permission: ask` 的 bot 觸發核准，測試裡用 API `respondPermission` 回應後，`send --wait` 完成，且 `waitedForApprovalSeconds > 0`。
  6. `--bot` 用名稱查詢成功；不存在的名稱 → exit 2。
  若某個 fixture 不存在，照 `fixtures/` 既有寫法新增最小 Python fixture。
- `cd host && cargo fmt --check && cargo clippy --all-targets -- -D warnings && cargo test --test send_cli_e2e` 全過；`cargo test` 其餘部分相對上游 `dev` **沒有新增失敗**（已知 `files_e2e::rejects_invalid_sources_without_a_file_entry` 在這台 Windows 上 dev 原樣就會失敗；`routines_e2e` 也可能，先在 `origin/dev` 跑一次記基準）。
- 本機實測：對 Ryan 已安裝並在跑的 Codync（v2.17.5，埠 19222）用新建的 `codync-host.exe send --bot Hermes --wait --json "請用一句話自我介紹，不要修改任何檔案"`（Ryan 已有一個名為 Hermes 的 bot），貼 JSON 輸出。**注意**：用 `cargo build` 產生的 binary 對既有 host 呼叫即可，不要停掉或取代 Ryan 已安裝的 host。

## Task B：`--help` 與錯誤訊息

- `codync-host send --help` 列出所有選項與結束碼。
- host 沒在跑時的訊息與 `local_call` 一致（`codync-host isn't running here. Start it with ...`）。

## Task C：文件

- 找到上游記錄 CLI 子命令的地方（`README.md` 的 Terminal 段落、`docs/` 裡關於 TUI／CLI 的頁面；grep `codync-host tui` 或 `codync-host status`），加一段 `send` 的用法與一個 `--wait --json` 範例（英文）。不要新開整頁。

## 3. 交付總回報格式

每個 Task 一節：改了哪些檔（路徑:行號）、驗收逐條 PASS/FAIL 附執行輸出原文（cargo 三件套、新測試、基準比較、本機實測 JSON）、未盡事項。最後附 `git log --oneline origin/dev..HEAD`、PR 連結、PR 的 Validation 段落原文。過不了的明講卡在哪，不要寫「大致完成」。

## 4. 不做

- 不新增或修改 API method、不改 SSE、不改 iOS／desktop。
- 不加「送出後自動停止」或「自動核准」。
- 不 bump 版本、不 push origin、不對 main 開 PR、不碰 `feat/hermes-harness` 分支。
