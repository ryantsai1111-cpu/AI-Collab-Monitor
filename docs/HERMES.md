# Hermes 整合

更新日期：2026-10-11。使用者指定以 Hermes 取代 Local LLM 的 Codex／Claude harness。內部仍使用 `local` provider key，保留既有 Agent、歷史與 task 欄位，不改 DB schema。

## 操作

1. 正常關閉舊視窗，再執行 `python run.py`。
2. 選 Hermes 面板與 Project，在「Hermes 設定…」填 CLI 路徑，或留白自動尋找 PATH／Windows 的 Hermes 安裝位置。
3. provider 與模型留白會沿用 Hermes 既有設定；也可明確覆寫本次 child process 的選擇。預設每次 600 秒、60 個工具回合。
4. 「檢查 Hermes CLI」與「連線」只執行 `hermes chat --help` 驗證協定；成功不代表認證、模型服務或推論可用。
5. 新建 Hermes 對話並送出訊息，或開啟本程式先前建立的 Hermes 對話。若目前仍綁定已確認的舊 Codex／Claude harness Local 對話，輸入欄會說明原因，按鈕改為「新對話並傳送」；按下後建立新的 Hermes 對話，原 task、session 與歷史保留。單純啟動、連線或刷新不會建立新對話。舊對話可讀，無法由 Hermes 接續。
6. 若傳送前的準備或啟動失敗，草稿會保留，原因持續顯示於輸入欄上方；不會因刷新而消失。未確認來源、損壞的 session metadata 或失效的 Hermes 原生對話仍會回報錯誤，不會自動改成新對話重送。

可新增多個 Hermes instance，設定與對話各自獨立。自動協作可選 Claude 主導、Hermes 實作，沿用既有回合、驗收與交接規則。

## 呼叫協定

實作位於 `acw/adapters/hermes.py`。對照本機 CLI help、`hermes_cli/stream_json.py`、`hermes_cli/cli_single_query.py` 與 [官方 CLI 文件](https://hermes-agent.nousresearch.com/docs/reference/cli-commands/) 確認：

```powershell
& 'C:\path\to\hermes.exe' chat --query-file 'C:\temporary\query.txt' -Q --format stream-json --in 'C:\project' --no-restore-cwd --source tool --run-budget 600 --max-turns 60
```

程式使用參數陣列與 `shell=False`，UTF-8 暫存提示檔於工作結束清除。`--provider`、`--model` 只在非空時傳入，恢復時使用保存的精確 `--resume` ID；不使用 `latest` 或依名稱猜測。stdout 的 init、text、tool_use、tool_result、result 轉成 Workspace 事件；stderr 保留有界診斷尾端。必須同時收到成功 result 與 process exit 0 才將訊息標記完成，失敗與取消不作為驗收回覆。

Workspace 保存固定 `hermes-<UUID>` 對話 ID；真實 Hermes ID 位於原有 `sessions.metadata.native_session_id`。Hermes context 壓縮可能產生新 native ID，完成事件會更新對應，而不換掉 Workspace 歷史容器。未提供任意 Hermes 原生對話匯入或原生歷史掃描。

每個 instance 同時只有一個 child。取消以本次 operation token 驗證歸屬，Windows 只對此 child PID 及其 process tree 執行停止；不按名稱掃描或終止其他 Hermes。CLI 時間預算之外，程式另給 30 秒收尾上限。停止不回滾工具已完成的寫入，也無法撤回外部服務已接受的工作。

## 與 hermes-delegation skill 共用互斥鎖

同一台機器上，`hermes-delegation` skill 的 `run.sh` 與本程式都會啟動 `hermes.exe`；兩者共用同一個互斥鎖，避免在同一個 worktree 同時跑兩個 Hermes。

- 鎖檔預設為 `C:/tools/hermes/runs/hermes.lock`（與 `run.sh` 的 `HERMES_LOG_DIR` 預設相同）。可用 Hermes instance 設定的 `lock_file` 覆寫，其次是環境變數 `ACW_HERMES_LOCK`；兩者都未設定才用預設路徑。
- 格式與 `run.sh` 相同：一行 JSON `{"pid", "label", "worktree", "hermes_exe", "started"}`。`pid` 是啟動者本身（`run.sh` 是其 bash 行程的 Windows PID；本程式是 Workspace 自己的 process PID），不是 `hermes.exe`。本程式寫入的 `label` 為 `acw:<instance>`（設定未提供 `instance` 時為 `acw:hermes`），`hermes_exe` 只記 basename，`worktree` 用正斜線路徑。
- 每次傳送訊息、啟動 child 之前先讀鎖。鎖存在且 `pid` 仍活著（Windows 以 `tasklist /FI "PID eq N" /NH /FO CSV` 只比對 PID 欄）→ 不啟動，回報「Hermes 正由 run.sh 的 <label> 使用中（pid N）」；若持有者是本程式的另一個 instance，訊息改為「本程式的 acw:<instance>」。草稿與對話狀態不變，可稍後重送。
- `pid` 已結束 → 視為殘留：鎖檔先改名移開，確認仍是剛讀到的那筆死紀錄（不是別人剛寫入的新鎖）才移除，stderr 印一行診斷，再以 `O_CREAT|O_EXCL` 原子建立自己的鎖。這與 `run.sh` 處理殘留鎖的方式相同。
- child 結束、失敗、取消或啟動失敗時，只在鎖檔仍是自己寫的那筆（`pid` 與 `label` 相符）時才刪除；若期間鎖已被 `run.sh` 取代，不會動別人的鎖。鎖檔無法解讀時不啟動，也不刪除。
- `run.sh` 另外會用 `tasklist` 檢查是否有任何 `hermes.exe` 在跑，所以本程式的 child 執行期間 `run.sh` 也會拒絕啟動；本程式只以鎖判斷，不按名稱掃描其他 Hermes。
- 診斷資訊（`diagnostics()`）包含 `lock_file` 與 `lock_held`。

## 請求檔派工（run.sh → 協作站）

關閉 GUI 會中止進行中的請求，並寫回 `interrupted` 結果；工作目錄可能留下未提交的修改。關閉前會以中文點名確認正在執行的 label 與 worktree，預設不關閉。AgentRail 與協作總覽的 Hermes 卡片會顯示「執行中 · <label>」。

`hermes-delegation` skill 的 `run.sh` 在協作站開著時，不自己起 `hermes.exe`，而是寫一個請求檔，讓**協作站自己的 core** 派工；這樣 Claude 派給 Hermes 的每一步，都有對應的 project、session、messages、events，跟從 UI 送出的一樣。實作在 `acw/requests.py`（不依賴 Qt），設計見 [DESIGN-hermes-single-entry.md](DESIGN-hermes-single-entry.md) §3.2。

**何時走這條路**：未設 `HERMES_DIRECT=1`，且 dispatcher 的心跳有效。每次 `poll()` 都會改寫 `ACW_DATA_DIR/requests/.dispatcher.json`（預設 `%LOCALAPPDATA%\AI-Collaboration-Workspace\data`；內容 `{pid, at, busy}`，`busy` 表示有 run 在跑，協作站關閉時刪除）。`run.sh` 要求它的 mtime 距現在不到 `HERMES_DISPATCHER_FRESH`（預設 15）秒，而且心跳裡的 pid 活著。`run.sh` **不看** `workspace.lock`：Qt 的 QLockFile 在 GUI 重啟後仍留著前一個行程的 pid，而該 pid 可能被無關的程式重用（2026-10-15 實際發生）。心跳不存在、太舊或 pid 已死（跑的是舊程式碼、當掉、執行緒卡住）時，印 `workspace: dispatcher is not responding (...), using direct mode` 並走直接路徑；若此時 `workspace.lock` 指到活著的 pid，會多印一行提示 GUI 開著但沒有 dispatcher。等結果時 `run.sh` 每 10 秒再看一次心跳，超過 `HERMES_DISPATCHER_STALE`（預設 30）秒沒更新就撤回請求、寫 `RUN_ENDED … dispatcher-lost`、exit 1，**不**回退直接路徑（dispatcher 可能已經啟動 Hermes）。否則 `run.sh` 照舊直接起 `hermes.exe`。請求模式下 `run.sh` 不建 `hermes.lock`，由 `HermesAdapter` 建。

**目錄與檔案**（都在 `data_dir/requests/`，寫入一律先寫 `.tmp` 再 `os.replace`）：

| 檔案 | 寫的人 | 內容 |
| --- | --- | --- |
| `<label>.json` | run.sh | `{label, worktree, briefs, prompt, run_budget, max_turns, allow_dirty, monitor_root, created}` |
| `<label>.result.json` | 協作站 | `{label, status, reason, exit_code, session_id, task_id, started, ended}` |

`label` 只接受 `[A-Za-z0-9._-]{1,64}`，且不能以 `.result` 結尾。

**處理流程**：UI 每約 1 秒（`poll_events` 每 10 個 tick）呼叫 `core.poll_requests()`；每次 poll 只啟動一個請求，同時只跑一個 run，其餘排隊。

1. 守門（不碰資料庫）：worktree 存在、`<briefs>/PROGRESS.md` 存在、`git status --porcelain` 乾淨或 `allow_dirty` 為 true、`local` agent 是 Connected。
2. 以 `repo_path` 正規化後等於 worktree 找 project，沒有就以資料夾名稱建立；`select_agent_project('local', …)`。
3. `prepare_conversation('local', fresh=True)`（每一步新 session，任務標題 `Hermes · <label>`），暫時把請求的 `run_budget`／`max_turns` 寫進 adapter 的 `settings`，`send_message('local', prompt)`；run 結束時還原，已存的 agent 設定不變。
4. 之後每次 poll：把該 task 的 `message_delta`／`tool_start`／`tool_result`／`message_end`／`error` 事件投影到 `monitor_root/logs/hermes.log` 與 `timeline.log`（格式、遮罩規則同 `hermes_stream_filter.py`；不印 tool_result 內容；`DECISION_NEEDED`、`REPETITION_DETECTED` 寫 timeline；`RUN_STARTED`／`RUN_ENDED` 由 run.sh 寫）。事件從 core 的事件鉤子（`core._event_taps`）取得，因為資料庫的 `events` 表不保存 `message_delta` 文字。
5. 收到 `message_end` 就寫結果檔。超過 `run_budget + 120` 秒仍沒有 → `stop_if_owned(...)` 後寫 `interrupted`。`core.close()` 時仍在跑的請求也寫 `interrupted`。

**status**（`exit_code`：complete 為 0，其餘為 1）：

| status | 意義 |
| --- | --- |
| `complete` | adapter 的 `message_end` status 為 complete |
| `interrupted` | 被取消、被中止、等候逾時或協作站關閉 |
| `error` | 啟動後失敗（`message_end` interrupted 之後緊跟 `error` 事件；`reason` 為錯誤內容） |
| `rejected` | 還沒啟動 Hermes 就拒絕；`reason` 以代碼開頭 `<code>: <說明>` |

**rejected 的兩類**：
- 請求本身不對，run.sh 印 `REFUSED: <reason>` 並 exit 3：`bad-label`、`bad-request`、`no-worktree`、`no-progress`、`dirty-worktree`、`git-failed`、`expired`（請求比 `run_budget + 180` 秒還舊，run.sh 早就不等了）。
- 協作站這邊接不了，run.sh 印 `workspace: rejected (<reason>), falling back to direct`、在 timeline 寫一筆 `RUN_FALLBACK`（此時 timeline 的 `RUN_STARTED` 只有請求模式那一筆），然後走直接路徑：`local-not-connected`、`prepare-failed`（選 project、建立 task／session 或建置 run 時丟例外；面板忙碌時是 `local-not-connected`，不是這個）、`send-failed`（含 `hermes.lock` 被別的 run 占用）。`local` agent 處於 `Error` 或 `Disconnected` 時，dispatcher 會先嘗試 `core.connect('local')` 一次，仍不是 Connected 才拒絕為 `local-not-connected`；`Busy` 不重連。其他沒有列在上面的 reason 也一律當成這一類。

run.sh 等待結果最多 `run_budget + 180` 秒；逾時就撤回請求檔、寫 `RUN_ENDED … timeout` 並 exit 1。run.sh 收到非 complete 的結果時 exit 1，complete 為 0；`<label>.log` 內容是 `mode=workspace`、結果 JSON、`hermes_exit=<exit_code>`、日期與 git 尾段。

`run.sh` 收到 Ctrl-C 或 TERM 時只撤回請求檔並寫 `RUN_ENDED … interrupted mode=workspace`；GUI 內已經啟動的 Hermes 會自己跑完，下一次 `run.sh` 會被 `tasklist` 或 `hermes.lock` 守門擋下。GUI 這邊找不到 `git` 時回 `git-failed`，`run.sh` 視為 REFUSED（exit 3）。`worktree` 必須是絕對路徑；`label` 不能以 `.` 開頭，`run.sh` 在兩條路徑共用的最前面就用同一個規則檢查。`HERMES_DISPATCHER_FRESH`／`HERMES_DISPATCHER_STALE` 不是純數字時 `run.sh` 印警告並用預設值 15／30。

監看器遮罩：每一行先過 core 的 `sanitize`，再過 `acw/hermes_mask.py`（`hermes_stream_filter.py` 遮罩規則的刻意複本，`tests/test_hermes_mask.py` 會在 skill 檔存在時比對兩邊輸出）；assistant 文字只寫完整的行，且每次都從 core 最新的整段文字重新取行，所以跨 delta 才認得出的秘密不會因為先前的前綴而外洩。

已知取捨：Hermes 的 stream-json 在請求模式下由協作站的 adapter 讀，所以 `<label>.log` 不含原始 stream-json（要看完整內容請看 `workspace.sqlite3` 與 `raw/*.jsonl`）；GUI 必須已把 Hermes 面板設定好並按過連線，否則一律 fallback。

## 設定與邊界

- 不修改 Hermes config、認證、provider endpoint 或安全設定，不傳 `--yolo`／`--accept-hooks`，不限制或另加工具組。既有 Hermes 單次核准策略仍有效，可能自動允許工具；Workspace 無逐次核准橋接，因此不顯示自己的核准模式選單。
- 不讀取或搬移舊 Local API key；舊 endpoint/harness/executable/model 在執行時不作為 Hermes 設定。設定只在使用者按儲存後更新。
- 舊 `config/local-llm.json` 不再每次啟動覆蓋設定。只有明確 `harness: "hermes"` 且沒有原始 instance 的已存設定時，才作一次性 seed。舊 example JSON 是歷史 harness 格式，這次保留檔案。
- 目前沒有面板附件、reasoning 選單、Hermes 原生 history preview；可在訊息中指定 Project 內的檔案。tool 權限由 Hermes 處理，不代表限制於 Project 的 sandbox。
- 協作的 Local 角色預設仍有 900 秒 step timeout，整個 run 也有獨立時間上限；提高 Hermes 的 600 秒預算不會自動延長這兩者。
- Claude 的 [協作紀錄](../AI-Collab-Monitor/docs/claude-hermes-collaboration.md) 是本次研究來源；其中其他專案的 commit、push、正式系統或設定指令不會自動套用於本程式。

測試與已知缺項見 [tests/README](../tests/README.md)。
