# AI-Collab-Monitor v0.1

本次實機驗收與原始文字證據請見 [驗收紀錄](evidence/ACCEPTANCE-REPORT.md)。

這是放在桌面的四 Agent 監看器。它在單一 Windows Terminal 視窗中，即時顯示 Claude、dot、Codex、Hermes 與協作時間線的文字 log。v0.1 只是 **observability layer（可觀測性層）**：讀取已寫入的紀錄，協助人工追蹤輸入、輸出、公開摘要、審查、handoff、命令、diff 與測試結果。

Monitor 不會啟動、控制或協調 Agent，不會派工、批准執行、觸發下一步或建立 orchestrator。它不會自動抓取 Agent 對話、其他 Terminal 畫面、設定或憑證，也不會擷取任何 Agent 的隱藏 chain-of-thought。`REASONING SUMMARY` 只供 Agent 主動提供的公開推理摘要與 decision rationale 使用。

## 角色與畫面

| 位置 | 標題 | 角色 | 監看的檔案 |
| --- | --- | --- | --- |
| 左上 | CLAUDE - PRIMARY REVIEWER | 第一審查者，提供理解、公開摘要與審查決策 | `logs\claude.log` |
| 中上 | DOT - SECONDARY REVIEW / RELAY | 獨立複審與轉交，提出補充發現 | `logs\dot.log` |
| 右上 | CODEX - IMPLEMENTER | 實作方，記錄計畫、檔案、真實工具紀錄、diff 與測試 | `logs\codex.log` |
| 最右上 | HERMES - IMPLEMENTER | 本機 Qwen 實作方；由 hermes-delegation 的 `run.sh` 自動寫入遮罩後的回覆、工具呼叫與結果 | `logs\hermes.log` |
| 下方橫跨 | COLLABORATION TIMELINE | 按寫入順序顯示跨 Agent 事件 | `logs\timeline.log` |

```text
┌───────────┬───────────┬───────────┬───────────┐
│  CLAUDE   │    DOT    │   CODEX   │  HERMES   │
├───────────┴───────────┴───────────┴───────────┤
│            COLLABORATION TIMELINE             │
└───────────────────────────────────────────────┘
```

CLI 語法依 Ryan-PC 現有 Windows Terminal **1.24.12741.0** 的本機 help 確認。視窗大小、字型與使用者 Terminal 設定會影響可顯示的文字寬度；每格內容開頭也會顯示自己的標題。

## 目錄

```text
AI-Collab-Monitor\
├─ logs\
│  ├─ claude.log
│  ├─ dot.log
│  ├─ codex.log
│  ├─ hermes.log
│  └─ timeline.log
├─ archive\
├─ tasks\
├─ helpers\
│  ├─ common.ps1
│  └─ watch-pane.ps1
├─ .monitor\
│  └─ sessions\            # 每次啟動的獨立 session 與生命週期紀錄
├─ start-monitor.ps1
├─ stop-monitor.ps1
├─ reset-monitor.ps1
├─ AI-Collab-Monitor.bat
└─ README.md
```

安裝位置為 `C:\Users\ryant\Desktop\AI-Collab-Monitor`；若該處已有資料而使用新的版本子目錄，請以本 README 所在目錄為實際根目錄。所有腳本都以自身所在位置定位檔案，可處理含空格的路徑。`tasks\` 留給使用者保存任務資料；v0.1 不會解讀或執行其中的內容。

## 啟動

使用一般使用者權限，雙擊 `AI-Collab-Monitor.bat`。也可在本目錄的 PowerShell 執行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start-monitor.ps1
```

腳本先確認 `wt.exe` 與五個 log；只安全補建不存在的 log，不清空既有內容。接著開啟單一 Windows Terminal 視窗與五格監看（上排四格等寬、下排時間線）。重複啟動同一套監看器會被阻擋，並以非零結束碼回報；不會再開一組監看。

每格使用 Windows 原生 .NET 檔案讀取方式，以約 200 毫秒的輪詢週期等待新內容，並同時檢查停止訊號。不需要 Node、Electron、Tauri、Web server 或系統管理員權限。`ExecutionPolicy Bypass` 只適用該次 PowerShell 子程序，不修改系統或使用者的永久 ExecutionPolicy。

## 停止

在本目錄執行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\stop-monitor.ps1
```

每次啟動使用新的 GUID session。每格監看程序在存活期間持有自己的獨占 lease；停止腳本向本套監看器的 session 寫入 `stop.signal`，由各格自行結束，並阻止該 session 尚未完成的延遲啟動。生命週期 gate 用來避免啟動、停止、reset 的競爭。

停止不依賴 PID 強制終止，不會執行 `taskkill`，也不會關閉其他 PowerShell、Windows Terminal、Claude 或 Codex 工作階段。若 Terminal 的使用者設定保留已結束的 pane，確認監看已停止後，手動關閉這個 Monitor 視窗即可。若腳本不能安全確認狀態，依它顯示的提示手動關閉這個 Monitor 視窗；不要批次終止程序。不要手動刪除 `.monitor` 或其中的 session 檔案來略過安全檢查。

若直接手動關閉 Monitor 視窗，session 仍會保守地視為運作中或待啟動。**重新啟動或 reset 前，仍須執行一次 `stop-monitor.ps1`**，讓該 session 收到停止訊號，也阻止可能延遲出現的 pane 啟動。

## Reset 與封存

先暫停所有會寫入這些 log 的外部來源，再停止 Monitor；確認監看已結束後，在本目錄執行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\reset-monitor.ps1
```

reset 會先檢查監看狀態；仍在監看或仍有待完成的啟動時，會拒絕執行並提示安全操作方式，不會在背景偷偷替換 log。

安全狀態下，reset 會：

1. 建立 `archive\YYYYMMDD-HHmmss\`；名稱碰撞時使用唯一後綴，保留既有封存。
2. 將目前的五個 log 移入該封存目錄。
3. 在 `logs\` 建立新的五個空 log。

reset 不會刪除 `tasks\`、既有 `archive\`、README 或腳本。完成後可重新啟動 Monitor，再恢復外部寫入。它只能掌握自己的監看程序，不能替任何外部 writer 暫停或協調 log rotation；若 writer 在 reset 期間持續寫入，可能發生檔案占用或資料落到封存檔，因此暫停 writer 是操作前提。

## 如何寫入 log

五個 log 初始為空檔。v0.1 不會自動從 Agent 收集資料（Hermes 委派循環除外，見下一段）；只有實際寫入檔案的內容才會出現在 pane。請以 **UTF-8、附加寫入、每筆以換行結尾** 的方式記錄，避免在監看期間覆寫、截短、刪除或替換檔案。監看器逐批顯示新讀到的文字，不必等到整行完成；跨批次的 UTF-8 字元會保留解碼狀態。

以下是可在 Windows PowerShell 5.1 使用的手動測試；請在 Monitor 根目錄執行。這些文字只是測試，不代表真實 Agent 的審查或執行結果：

```powershell
$monitorRoot = (Get-Location).Path
$utf8 = [Text.UTF8Encoding]::new($false)
[IO.File]::AppendAllText((Join-Path $monitorRoot 'logs\claude.log'), "[TEST DATA] Claude pane test`r`n", $utf8)
[IO.File]::AppendAllText((Join-Path $monitorRoot 'logs\dot.log'), "[TEST DATA] Dot pane test`r`n", $utf8)
[IO.File]::AppendAllText((Join-Path $monitorRoot 'logs\codex.log'), "[TEST DATA] Codex pane test`r`n", $utf8)
[IO.File]::AppendAllText((Join-Path $monitorRoot 'logs\hermes.log'), "[TEST DATA] Hermes pane test`r`n", $utf8)
$timelineLine = '{0} | TEST-MANUAL | MONITOR | PANE_TEST | Timeline pane test (test data)' -f (Get-Date -Format o)
[IO.File]::AppendAllText((Join-Path $monitorRoot 'logs\timeline.log'), ($timelineLine + "`r`n"), $utf8)
```

不要把密碼、token、cookie、`.env` 內容或其他秘密寫入 log。Monitor 直接顯示文字，不提供自動去識別、過濾或秘密遮罩（Hermes 的寫入端 `hermes_stream_filter.py` 自己會先遮罩）。每個 log 建議由一個 writer 寫入；多個 writer 同時附加可能互相爭用或交錯。

### Hermes 委派循環由 run.sh 自動寫入

Claude 用 `hermes-delegation` skill 無頭執行 Hermes 時，`~/.claude/skills/hermes-delegation/scripts/run.sh` 會自動寫監看器，不需要手動記錄：

- 監看器根目錄由環境變數 `HERMES_MONITOR_ROOT` 指定，預設就是本目錄；目錄不存在時 `run.sh` 印出 `monitor: off (<path> not found)` 並照常執行。
- `logs\hermes.log`：Hermes 的回覆文字、`[TOOL] <name> <input 摘要>`、`[TOOL DONE] <name> <ms> error=<bool>`、`[RESULT exit=N] <最後回覆>`。**不含**工具輸出內容；`sk-…`、`ghp_…`、`AKIA…`、`Bearer …`、`password=`/`token=`/`api_key=` 之後的值會被換成 `***`。完整未遮罩的原始紀錄在 `C:/tools/hermes/runs/<label>.log`（不在本目錄）。
- `logs\timeline.log`：`<時間> | <label> | HERMES | <EVENT> | <訊息>`，事件為 `RUN_STARTED`、`DECISION_NEEDED`（Hermes 輸出 `[DECISION NEEDED]`）、`REPETITION_DETECTED`、`RUN_ENDED`（含 `exit=`、`result_exit=`、`dirty=<n> files`）。
- 同一時間只允許一個 Hermes 執行：`C:/tools/hermes/runs/hermes.lock` 記錄 run.sh 這個 bash 行程的 pid（原子建立）；重複啟動會被 `REFUSED`。run.sh 正常結束或被 Ctrl-C／TERM 會刪鎖；被硬殺（taskkill）時鎖會殘留，下次啟動發現 pid 已死會自動清掉。
- 寫入是附加、UTF-8 無 BOM、CRLF 結尾；`reset-monitor.ps1` 前要先確認沒有 Hermes 正在執行。
- `logs\claude.log` 與 timeline 的 `CLAUDE` 事件由同一個 skill 的 `progress.mjs` 寫入：Claude 核准（`APPROVE`）、核准但先停住（`HOLD`）或退回重做（`REWORK`）一步時，各加一段決策紀錄。Claude 的其他對話內容不會進來。

## Agent log 範本

下列只是預期格式，省略號應由主動輸出的真實內容取代。不要用範本中的 `APPROVE / BLOCK` 或其他佔位文字冒充實際決策。

### Claude

```text
[INPUT]
...

[UNDERSTANDING]
...

[REASONING SUMMARY]
...

[DECISION]
APPROVE / BLOCK

[OUTPUT / HANDOFF]
...
```

### Dot

```text
[INPUT]
...

[INDEPENDENT REVIEW]
...

[ADDITIONAL FINDINGS]
...

[DECISION]
APPROVE / BLOCK

[HANDOFF]
...
```

### Codex

```text
[INPUT]
...

[PLAN]
...

[FILES]
...

[TOOL / COMMAND]
...

[COMMAND OUTPUT]
...

[EXIT CODE]
...

[DIFF]
...

[TEST]
...

[OUTPUT]
...
```

`COMMAND OUTPUT`、`EXIT CODE`、`DIFF` 與 `TEST` 應記錄真實工具結果。若尚未執行或無法驗證，應明確寫出，不能以推測代替證據。

## Timeline 格式

```text
ISO8601_TIMESTAMP | TASK_ID | ACTOR | EVENT | OPTIONAL_MESSAGE
```

timestamp 應包含時區，`TASK_ID` 用於對照各方紀錄。最後一欄可省略。以下全部為格式範例，不是已發生的事件：

```text
2026-10-05T00:42:01+08:00 | TASK-0001 | CLAUDE | REVIEW_STARTED
2026-10-05T00:42:20+08:00 | TASK-0001 | CLAUDE | APPROVE
2026-10-05T00:42:23+08:00 | TASK-0001 | DOT | REVIEW_STARTED
2026-10-05T00:42:40+08:00 | TASK-0001 | DOT | APPROVE
2026-10-05T00:42:45+08:00 | TASK-0001 | CODEX | IMPLEMENTATION_STARTED
```

Monitor 不會解析決策、排序 timestamp、驗證 actor 身分或根據事件採取動作；時間線顯示的是檔案內的寫入順序。

## 已知限制與下一階段

- 除了 Hermes 委派循環（由 `run.sh` 寫入）之外，目前沒有 Agent 自動寫入整合，也沒有 orchestrator、事件派送或背景常駐服務；關閉視窗或停止監看後，不再顯示新增內容。
- 只支援文字 log 顯示，不提供 diff 上色、結構化搜尋、測試報告解析或跨檔案一致性保證。
- Terminal 版本、視窗尺寸與使用者設定可能影響外觀；若 pane 結束後仍保留，手動關閉該 Monitor 視窗即可。
- 外部 writer 必須配合停止與 reset；本工具不會擅自中斷 writer 或修改 Agent 設定。

下一階段可另外設計經使用者授權的 writer adapter，讓 Claude、dot、Codex 透過各自支援的明確輸出或 hook，把公開摘要、審查決策、handoff 與真實工具結果附加到對應 log，並由同一個受控 writer 寫入帶有 task ID 的 timeline。應先定義事件格式、寫入鎖、秘密遮罩、長輸出處理與 reset 協定，再逐一整合。這些整合 **尚未實作**，不屬於 v0.1；也不需要擷取任何隱藏思考。
