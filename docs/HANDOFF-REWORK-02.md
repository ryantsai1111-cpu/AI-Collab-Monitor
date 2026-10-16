# 返工規格 02 — Codex 派工以「回合結束」判定完成，並投影指令事件

> 對象：Codex。**本文件自足。** 承接已合併的 PR #9（`docs/HANDOFF-playbooks-dispatch.md`、`docs/HANDOFF-REWORK-01.md`）。
> 在新 branch `codex/codex-turn-completion`（從 `ui/desktop-workspace-100pct-20261006` 切）上做，用 `git worktree add ../AI-Collab-Workspace-codex-turn codex/codex-turn-completion` 在另一個目錄工作；**不得用 junction／symlink 連 `vendor/`**（需要就 `python -m pip install --target vendor "PySide6==6.11.2"`）。不要啟動 `run.py`。完成後開 PR 到 `main`，**不得 push main**。

## 0. 背景：2026-10-16 實機煙霧測試的結果

審查者用協作站派了一個極小規格給 Codex（建一個檔並 commit）。`scripts/dispatch_request.py` 在 15 秒後回 `complete`、exit 0，但當時 Codex 只講完第一句「我會先讀取規格…」，檔案根本還沒建。事件順序（`data_dir/raw/codex-*.jsonl`，task `task-1f06bb71…`）：

```
13:15:44 prompt_sent / state Busy
13:15:48 message_start
13:15:49 message_end (completed)      ← dispatcher 在這裡寫了 complete
13:15:55 command inProgress → failed
13:16:05 command inProgress
13:16:05 approval item/commandExecution/requestApproval
…（回合仍在進行，等使用者核准）
```

原因：

1. `acw/requests.py` 的 `_advance`（約 544-557 行）對所有 provider 都把**第一個** `message_end` 當成 run 結束。Hermes 一個 run 只有一則最終訊息，所以沒問題；Codex app-server 一個回合裡每則 agent 訊息都會發 `message_end`（`acw/adapters/codex.py:266`），回合真正結束是 `turn/completed`：adapter 在 `codex.py:214-232` 發 `self._emit("event", summary="Turn " + status, status=status, turn_id=…)` 並 `set_state("Connected")`。
2. `WANTED`（`acw/requests.py:36`）沒有 `event`、`state`、`command`、`file`、`diff`、`test`，所以 dispatcher 看不到回合結束，`codex.log` 也看不到 Codex 跑了哪些指令。Codex adapter 會發的事件類型：`approval, command, diff, error, event, file, message_delta, message_end, message_start, raw, session, test, tool_result`。

## 1. 不變量

1. 只動 `acw/requests.py`、`tests/test_codex_requests.py`（或新測試檔）、`docs/HERMES.md`。不碰 `acw/adapters/*`、`acw/store.py`、`acw/core.py`、`scripts/dispatch_request.py`（它的行為不用改）。
2. Hermes（provider `local`）的完成判定與投影**完全不變**；`tests/test_hermes_requests.py` 不得修改斷言，必須全過。skill 的離線測試 `bash ~/.claude/skills/hermes-delegation/scripts/tests/run-offline.sh` 必須 `OFFLINE TEST PASS`。
3. `python scripts/run_tests.py --ui` 全綠，全套 0 FAIL。

## Task A：Codex 的 run 以回合結束判定完成

**要求**：
1. `_on_event` 對 provider `codex` 的 run 額外收：`event`（只收 `summary` 以 `Turn ` 開頭者，保留 `status`、`turn_id`）、`state`（保留 `state`）、`command`（保留 `command`、`status`、`exit_code`，**不收輸出內容**）、`file`（保留路徑與動作）、`diff`（只保留檔案數或路徑清單，不收 diff 內容）、`test`（保留名稱與結果）。Hermes 的 run 維持現有 `WANTED`。
2. `_advance` 對 codex：
   - `message_end` 只是一則訊息結束，**不**結束 run。
   - 收到 `Turn ` 事件時結束：`status` 為 `completed` → `complete`；`interrupted`／`cancelled` → `interrupted`；`failed` 或其他 → `error`（reason 用最後一個 `error` 事件內容，沒有就用 `Turn <status>`）。
   - 後備：若沒有收到 `Turn ` 事件，但看到 adapter `state` 從 `Busy` 變回 `Connected` 且超過 5 秒沒有新事件，也以 `complete` 結束，並在 timeline 寫 `TURN_END_INFERRED`。
   - 有未決核准時（既有的暫停計時）照舊暫停，不受影響。
3. 結果檔多兩個欄位（只對 codex）：`turn_status`、`messages`（這個回合的 agent 訊息則數）。`dispatch_request.py` 不需要改。

## Task B：`codex.log` 的投影

**要求**（`MonitorProjection`，只在 provider `codex` 時生效）：
1. 每則 agent 訊息照現有方式逐行輸出文字；`message_end` 時**不**印 `[RESULT …]`，改為一行空白分隔。
2. `command`：`inProgress` 時印 `[CMD] <指令 ≤120 字>`；結束時印 `[CMD DONE] status=<status> exit=<exit_code>`。不印輸出。
3. `file`：`[FILE] <動作> <路徑>`；`diff`：`[DIFF] <n> files`；`test`：`[TEST] <名稱> <結果>`。
4. 回合結束時印一次 `[RESULT exit=<0|1>] <最後一則訊息的第一行 ≤200 字>`，並寫 timeline `TURN_END | <status>`。
5. 遮罩：所有輸出照現有 `sanitize` + `hermes_mask.mask`。

## 驗收（附執行輸出原文）

- `tests/test_codex_requests.py` 新增一個替身 Codex adapter 的完整回合：`message_start` → `message_end`（第一則）→ `command` inProgress → `approval` → `approval_response` → `command` completed → `message_start` → `message_end`（第二則）→ `event` `Turn completed` → `state Connected`。斷言：
  - 第一個 `message_end` 之後結果檔**不存在**；`Turn completed` 之後才是 `complete`。
  - `codex.log` 含兩則訊息的文字、`[CMD]`、`[CMD DONE]`，`[RESULT` 只出現一次，且不含任何指令輸出。
  - timeline 有 `APPROVAL_NEEDED`、`APPROVAL_RESOLVED`、`TURN_END`。
  - 結果檔有 `turn_status: completed`、`messages: 2`。
- 另一個測試：`Turn failed` + 前面一個 `error` 事件 → 結果 `error`、reason 是那個錯誤。
- 另一個測試：沒有 `Turn` 事件、只有 `state Busy → Connected` 且之後 5 秒（可注入 clock）無事件 → `complete`，timeline 有 `TURN_END_INFERRED`。
- `tests/test_hermes_requests.py` 不改、全過；skill 離線測試 `OFFLINE TEST PASS`。
- `--ui` 全綠；全套 0 FAIL。

## 回報格式

每個 Task 一節：改/增哪些檔（路徑:行號）、驗收逐條 PASS/FAIL 附執行輸出原文、未盡事項。最後附 `--ui` 與全套輸出、skill 離線測試輸出、`git log --oneline main..HEAD`、PR 連結。不要寫「大致完成」。

## 不做

- 不改 Codex adapter、不改核准策略或沙箱設定（那是使用者在 GUI 的設定）。
- 不改 `dispatch_request.py`、不改 Hermes 路徑。
- 不要 push main。
