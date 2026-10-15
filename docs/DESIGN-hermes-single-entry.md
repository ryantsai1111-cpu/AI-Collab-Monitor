# 設計：Hermes 單一入口（skill 與協作站收斂）

更新日期：2026-10-15。前置：[HERMES.md](HERMES.md)、[AGENT-CONTEXTS.md](AGENT-CONTEXTS.md)、`AI-Collab-Monitor/docs/claude-hermes-collaboration.md` §9。

## §1 問題

目前 Hermes 有兩條互不相識的入口：

| 入口 | 誰呼叫 | 狀態保存在哪 | 預算 | 協作站看得到嗎 |
| --- | --- | --- | --- | --- |
| A. hermes-delegation skill 的 `run.sh` | Claude Code session 的 Bash | worktree 裡的 `PROGRESS.md`、git、`C:/tools/hermes/runs/<label>.log`、桌面監看器 `logs/hermes.log` | 3000 秒／150 回合 | 否：不經 `core.send_message`，`messages`、`events`、`sessions` 都沒有紀錄 |
| B. 協作站的 `HermesAdapter` | ACW 的 UI 或 orchestrator | `workspace.sqlite3`（sessions、messages、events）與 `raw/*.jsonl` | 600 秒／60 回合，orchestrator 另有 900 秒 step timeout | 是 |

兩條路的互斥已由 `hermes.lock` 統一（2026-10-15，見 `acw/adapters/hermes.py` 的 `HermesLock`）。剩下的差距是**紀錄與呈現**：協作站的「每個 agent 各自綁 project／session」這件事，對 A 路徑完全不成立。

## §2 目標

1. Claude 用 skill 派給 Hermes 的每一步，在協作站裡都有對應的 project、session 與事件，跟從 UI 送出的一樣。
2. 不改變 skill 的操作介面：Claude 仍然是 `bash run.sh <worktree> <briefs> <label>`，仍然靠 `PROGRESS.md` 與 git 做記憶，仍然由 Claude 審查。
3. 不讓 skill 依賴 GUI 開著。

## §3 兩個階段

### §3.1 階段 A：協作站讀 run.sh 的輸出（本次實作）

最小改動，立刻有效：

- `acw/inspection.py` 的 `LegacyReader` 多讀 `logs/hermes.log`。
- `acw/core.py` 的 `poll_legacy` 把 `hermes` 對應到內建的 `local` agent（UI 顯示名稱就是 Hermes），事件型別仍是 `legacy`，內容仍經 `sanitize`。
- 不動 UI：Monitor 模式本來就每秒輪詢 legacy，並把結果放進對應面板的 `LEGACY MONITOR · READ ONLY` 卡片。

效果：skill 跑的每一步，Hermes 面板會即時看到遮罩後的摘要；timeline 事件照舊進 workspace。限制：這是唯讀投影，不建立 session，不進 `messages`，協作站無法接續或取消它。

### §3.2 階段 B：協作站當派工端，run.sh 用請求檔交給它

**為什麼不是獨立 CLI 開同一個資料庫**：`run.py` 用 `QLockFile(data_dir/workspace.lock)` 做單一實例；`WorkspaceCore` 本身不鎖，所以第二個行程開同一個 sqlite 技術上可行，但 GUI 的 `WorkspaceCore` 把 `agents.instances`、`selection.<agent>` 等設定快取在記憶體，另一個行程改資料庫會讓 GUI 的狀態與資料庫脫節。所以 GUI 開著時，**只能由 GUI 那個 core 來派工**。

做法：

1. `run.sh` 啟動前檢查 `data_dir/workspace.lock`（Qt 格式：pid、程式名、主機名各一行）。pid 活著**且** dispatcher 心跳新鮮（`data_dir/requests/.dispatcher.json` 每次 `poll()` 改寫，mtime 距現在不到 15 秒）→ GUI 在跑而且會回應，走請求檔；pid 活著但心跳不存在或太舊（GUI 還是舊版程式、當掉、執行緒卡住）→ 當成 GUI 沒開；否則照現在直接起 hermes.exe（行為不變）。等結果時 run.sh 每 10 秒再看心跳，超過 30 秒沒更新就撤回請求並以 `dispatcher-lost` 結束（不回退，因為 dispatcher 可能已經啟動 Hermes）。
2. 請求檔：`data_dir/requests/<label>.json`，內容 `{worktree, briefs, label, prompt, run_budget, max_turns, created}`。run.sh 寫完後等 `data_dir/requests/<label>.result.json` 出現，再把 result 的 exit code、`hermes_exit`、git 尾段印成和現在一樣的格式。
3. core 新增 `poll_requests()`：由 UI 既有的 100ms tick（`ui.py` 的 `poll_events`）每秒呼叫一次。對每個新請求：
   - 以 `repo_path == worktree` 找 project，沒有就 `create_project`；`select_agent_project('local', ...)`。
   - 守門同 run.sh（`PROGRESS.md`、乾淨工作樹或 `HERMES_ALLOW_DIRTY`）。鎖由 `HermesAdapter` 的 `HermesLock` 負責。
   - `prepare_conversation('local', fresh=True)`（每一步新 session，對應 skill「沒有記憶」的設計），再 `send_message('local', prompt)`，`run_budget`／`max_turns` 用請求裡的值覆寫這一次。
   - 收到該 session 的 `message_end` 後寫 result 檔；失敗或取消也寫（status 不同），run.sh 才不會等到死。
4. 桌面監看器的 `hermes.log`／`timeline.log`：由 core 的 emitter 在 `message_delta`／`tool_start`／`message_end` 時寫，沿用 `hermes_stream_filter.py` 的遮罩規則（把 `mask()` 抽成可 import 的模組）；直接路徑仍由 run.sh 寫。兩條路徑**不會同時**寫同一個 run。

**前提（2026-10-15 查到的現況）**：預設資料目錄的 `projects` 表是空的，`agent.local` 設定仍是舊的 Local LLM harness（`harness: claude`、`base_url`），也就是協作站還沒被設定成用 Hermes。階段 B 做好之後，要先在 GUI 把 Hermes 面板設定好並連線一次，請求檔路徑才會生效；在那之前 run.sh 會因為 GUI 的 local agent 不是 Connected 而拿到失敗的 result，並回退到直接路徑。

**已知取捨**

- 請求檔路徑下，協作站可以在 UI 取消這個 run（`stop_if_owned`）；直接路徑不能。
- 不經 orchestrator，所以 900 秒 step timeout 與 VERDICT 信封不適用；Claude 的審查流程不變。
- `HermesAdapter` 不支援工具核准，單次模式的核准策略仍由 Hermes 自己的設定決定（Ryan 已設 `approvals.single_query_mode approve`）。

## §4 順序與相依

1. 階段 A：已實作（2026-10-15），動 `inspection.py`、`core.py` 與 `tests/test_core.py`。
2. 階段 B：**已實作（2026-10-15）**。`acw/requests.py`（`RequestDispatcher`）、`core.poll_requests()`、UI `poll_events` 每約 1 秒呼叫、skill 的 `run.sh` 請求模式；格式與流程見 [HERMES.md](HERMES.md)「請求檔派工」。與上文設計的差異：
   - 監看器投影的來源是 core 的事件鉤子（`core._event_taps`），不是查 `events` 表，因為資料庫刻意不保存 `message_delta` 文字。
   - result 的 `rejected` 以 `reason` 的代碼前綴分兩類（請求錯誤 → run.sh REFUSED；協作站接不了 → 回退直接路徑），另有 `expired` 代碼。
   - dispatcher 心跳（見 §3.2 第 1 點）是為了避免 GUI 開著但沒有 dispatcher 時 run.sh 空等整個 `run_budget + 180` 秒。
   - 請求多了 `allow_dirty`（對應 `HERMES_ALLOW_DIRTY=1`）與 `monitor_root`（run.sh 的監看器根目錄，非字串或不存在時就不投影）。
   - 先做不碰資料庫的守門：守門類拒絕（label、worktree、PROGRESS.md、髒工作樹、git、local 不是 Connected）不會留下 project 或 task；`prepare-failed`／`send-failed` 發生時 project 與一個空的 task 已經建立，會留下。
   - `local` agent 處於 `Error` 或 `Disconnected` 時，dispatcher 先呼叫一次 `core.connect('local')` 再判斷；`Busy`／`Connecting` 不動。
   - 監看器的每一行在 core 的 `sanitize` 之後再過 `acw/hermes_mask.py`（direct 路徑遮罩規則的刻意複本），兩條路徑的遮罩一致。
3. 階段 B 完成後，`AI-Collab-Monitor/docs/claude-hermes-collaboration.md` §9 與 skill 的 SKILL.md §3 要改成指向請求檔路徑（SKILL.md §3 已更新；§9 尚未改）。

## §5 不做的事

- 不讓 Claude Code 本身變成協作站裡的一個 adapter；Claude 的 session 由 Claude Desktop 管。
- 不把 skill 的 `PROGRESS.md`／任務卡搬進 sqlite；它們留在 repo 裡是刻意的，Hermes 讀 repo 就夠。
- 不替 Hermes 加逐次核准橋接。
