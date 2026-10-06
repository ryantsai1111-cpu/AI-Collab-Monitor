# AI-Collab-Monitor v0.1 — Ryan-PC 驗收紀錄

交付位置：`C:\Users\ryant\Desktop\AI-Collab-Monitor`

建立前檢查目錄不存在，因此直接建立此目錄；沒有覆寫既有資料。使用現有 Windows Terminal 1.24.12741.0 與 Windows PowerShell 5.1。沒有安裝軟體、修改 Agent 設定、PATH、ACL、sandbox、永久 ExecutionPolicy 或正式 repo，也沒有 commit、push、排程、Web server 或 orchestrator。

## 交付檔案

```text
AI-Collab-Monitor\
  logs\claude.log
  logs\dot.log
  logs\codex.log
  logs\timeline.log
  archive\20261005-003712\  (四份已驗收的舊 log)
  tasks\acceptance-sentinel.txt
  start-monitor.ps1
  stop-monitor.ps1
  reset-monitor.ps1
  AI-Collab-Monitor.bat
  README.md
  helpers\common.ps1
  helpers\watch-pane.ps1
  .monitor\                (本監看器的 gate、session、lease、stop 訊號)
  evidence\                (本文件與原始文字驗收證據)
```

`tasks\acceptance-sentinel.txt` 是清楚標識的驗收檔，用來證明 reset 不刪除或改寫 tasks。`file-manifest.json` 記錄正式腳本、README 與批次檔的 SHA-256。

## A–D：啟動、即時更新與畫面

`start-monitor.ps1` 退出碼 0。只建立一個 Windows Terminal 視窗，四個 pane：

| Pane | 位置（實際 UI 座標與尺寸） | 兩輪即時追加驗收 |
| --- | --- | --- |
| CLAUDE - PRIMARY REVIEWER | x=0, y=39, 637×768 | `Claude pane test ACCEPTANCE-633f92ef09ea`、`CLAUDE live append 2` |
| DOT - SECONDARY REVIEW / RELAY | x=643, y=39, 634×768 | `Dot pane test ACCEPTANCE-633f92ef09ea`、`DOT live append 2` |
| CODEX - IMPLEMENTER | x=1283, y=39, 637×768 | `Codex pane test ACCEPTANCE-633f92ef09ea`、`CODEX live append 2`、`中文 🙂` |
| COLLABORATION TIMELINE | x=0, y=813, 1920×327 | 包含 ISO 8601、TASK-ACCEPTANCE、MONITOR_TEST 的兩筆時間軸 |

上方三欄，下方橫跨全寬，時間軸約佔高度 30%。標題與 log 對應正確，四個內容區均為 `Offscreen=false`。這是直接讀取已開啟 Terminal 的 accessibility TextPattern 與實際座標所得的文字證據，不以命令成功代替畫面驗證。未製作截圖。

原始證據：`pane-uia-first.json`、`pane-uia-evidence.json`、`appends.json`、`start-result.json`、`wt-local-help.txt`。測試內容明確標為 Monitor acceptance test，沒有偽裝為 Agent 審查或工具結果。

## E：安全停止與其他工作階段

`stop-monitor.ps1` 退出碼 0。每次啟動使用新的 GUID session；停止時只在本監看器的 session 寫入 `stop.signal`，由讀取程序自行退出，並確認所有獨占 lease 已釋放。沒有 PID 終止操作，因此不受 PID 重用影響。延遲啟動的 pane 也會先檢查 stop 訊號。

Terminal 的完成畫面顯示 `[MONITOR STOPPED]` 與程序退出碼 `0 (0x00000000)`。本機 Terminal 會保留部分已完成窗格，因此驗收時在所有 lease 釋放後，只對先前記錄的 monitor HWND/PID 關閉該視窗。正式 stop 腳本不會強制關閉視窗，而是提示使用者手動關閉本監看視窗。

前後快照比對 PID **與啟動時間**：原有 13 個 Claude、2 個 Codex、1 個 PowerShell 程序全部仍是同一個程序。驗收開始前沒有既有 Windows Terminal 程序，因此沒有宣稱已測到不存在的其他 Terminal 視窗。

證據：`stop-result.json`、`stopped-pane-text.txt`、`processes-before.json`、`processes-after-stop.json`、`unrelated-process-survival.json`、`window-close-verification.json`。最初驗收報表的日期字串型別比較曾產生錯誤結果，已依未修改的原始快照修正為 DateTimeOffset 比較；說明保存在 `comparison-note.txt`。這不是產品程式的錯誤。

## F：Reset

運行中 reset 以退出碼 1 拒絕，未輪替 log。停止後 reset 退出碼 0，將四個 log 移到：

`archive\20261005-003712\`

四份封存檔的 SHA-256 與 reset 前完全相同；新建的四個 log 均為 0 bytes；tasks 驗收檔的 SHA-256 未變。README、腳本與既有封存均保留。

證據：`active-reset-result.json`、`reset-result.json`、`logs-before-reset.json`、`reset-verification.json`。

## 其他必要檢查

- 重複 start 退出碼 1，不建立第二組 monitor：`duplicate-start-result.json`。
- 五個 PowerShell 腳本通過 Windows PowerShell 5.1 語法解析。
- 真正執行交付批次檔，從含空格與中文的獨立測試路徑啟動：退出碼 0；四格 UI 內容均驗證成功；stop 退出碼 0，測試視窗已關閉。證據：`portable-summary.json`、`portable-uia.json`、`portable-stop.json`。
- 獨立程式審查找出的分段 UTF-8 字元緩衝區問題已修正；停止期間保留 lifecycle gate，避免與同時 start 競爭。
- Windows PowerShell 5.1.26100.9444 的獨立回歸檢查 18/18 通過：跨 8192-byte 邊界分段寫入 emoji 與中文，輸出完整且無替代字元；pending/active reset 拒絕、閒置 cooperative stop、取消待啟動 session、封存名稱碰撞、tasks 與腳本保留。這些檢查在工作區的獨立測試副本執行，沒有操作桌面正式交付資料。證據：`regression-results.json`。

## 使用及限制

雙擊 `AI-Collab-Monitor.bat` 即可啟動。停止與 reset 的完整命令見 README。Bypass 只用於該次 PowerShell 子程序。

v0.1 只顯示已追加至 log 的文字，不自動取得 Agent 對話，不啟動或控制 Agent，不擷取隱藏 chain-of-thought。Log 請使用 UTF-8。Reset 前需暫停外部 writer；本工具無法替任意外部 writer 協調封存。手動關閉視窗後，再啟動或 reset 前請先執行 stop，以保守地取消尚未完成的 session。Terminal 若保留已完成窗格，請手動關閉本監看視窗。Log 以文字顯示，沒有 diff 上色、搜尋、結構化解析或決策執行。

下一階段僅建議：分別為 Claude、dot、Codex 設計經授權的公開輸出 adapter／hook，以 UTF-8 追加公開摘要、decision、handoff 與真實 command/output/exit code/diff/test，使用共同 TASK_ID 寫 timeline，並協調單一 writer、敏感內容遮罩及 reset。這些整合尚未實作；本輪沒有進入 v0.2 或 orchestrator。
