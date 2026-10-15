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

### §3.2 階段 B：非 GUI 入口，run.sh 改走 adapter

新增 `python -m acw.cli hermes-run --worktree <path> --briefs <dir> --label <label> [--data-dir ...]`：

1. 開 `WorkspaceCore(data_dir)`（core、store、adapter 都不依賴 Qt，已確認）。
2. 找或建一個 provider 為 `local` 的 Hermes instance，`set_project(worktree)`；每一步**新建** session（對應 skill「每次都是新對話」的設計），不 `--resume`。
3. 做 skill 現有的三個守門（`PROGRESS.md` 存在、工作樹乾淨或 `HERMES_ALLOW_DIRTY`、無其他 hermes），鎖交給 adapter。
4. 用 `core.send_message` 送固定啟動句，`run_budget`／`max_turns` 由 CLI 參數覆寫 adapter 預設（3000／150）。
5. 阻塞等 `message_end`，把 `result` 的 exit code、`hermes_exit`、git 尾段印到 stdout，格式與現在的 `<label>.log` 尾段相同，Claude 端不用改讀法。
6. 同時仍寫桌面監看器（`hermes.log`、`timeline.log`），沿用 `hermes_stream_filter.py` 的遮罩與事件規則；或改成 core 的 emitter 直接寫，二擇一，避免雙寫。

`run.sh` 變成薄包裝：守門後呼叫 CLI。`C:/tools/hermes/runs/<label>.log` 保留為完整原始紀錄。

**已知取捨**

- GUI 開著時，CLI 寫進同一個 sqlite（WAL）沒有問題，但 GUI 的 in-memory 事件佇列不會即時收到 CLI 的事件；GUI 要在刷新 context 或重開 transcripts 時才看到。即時畫面仍由桌面監看器與階段 A 的 legacy 投影負責。
- CLI 不經 orchestrator，所以 orchestrator 的 900 秒 step timeout 與 VERDICT 信封不適用；Claude 的審查流程不變。
- `HermesAdapter` 不支援工具核准，單次模式的核准策略仍由 Hermes 自己的設定決定（Ryan 已設 `approvals.single_query_mode approve`）。

## §4 順序與相依

1. 階段 A：現在做，動 `inspection.py`、`core.py` 與 `tests/test_core.py`。
2. 等「讓 ACW 的 Hermes adapter 共用 hermes.lock」那個 session 完成並驗收後，再做階段 B，因為 B 依賴 adapter 的鎖。
3. 階段 B 完成後，`AI-Collab-Monitor/docs/claude-hermes-collaboration.md` §9 與 skill 的 SKILL.md §3 要改成指向 CLI。

## §5 不做的事

- 不讓 Claude Code 本身變成協作站裡的一個 adapter；Claude 的 session 由 Claude Desktop 管。
- 不把 skill 的 `PROGRESS.md`／任務卡搬進 sqlite；它們留在 repo 裡是刻意的，Hermes 讀 repo 就夠。
- 不替 Hermes 加逐次核准橋接。
