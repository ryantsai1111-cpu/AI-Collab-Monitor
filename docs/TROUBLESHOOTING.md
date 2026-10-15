# 疑難排解

更新日期：2026-10-09；依目前原始碼入口整理。舊 EXE 與舊驗收報告只作歷史參考。

## 開不起來或仍是舊畫面

從本 repo 執行 `python run.py`，或雙擊本機 `AI Collab Workspace.lnk`。捷徑應指向這份 checkout 的 `run.py`，而非舊安裝目錄或 EXE。執行中的 Python 不會自動載入修改，請先正常關閉再啟動。

找不到 PySide6 時先確認同層 `vendor/` 存在。若沒有，依 `requirements.txt` 安裝到使用中的 Python 環境；不要刪除現有 vendor。錯誤可能寫入根目錄 `startup-error.log`。

「This data directory is already open」表示相同資料已被另一個視窗使用。先找既有視窗，不要直接刪除 lock 或資料庫。測試用 `--data-dir` 指向新目錄。

## Codex／Claude 更新後無法連線

1. 打開該 Agent 的設定與診斷，確認實際 executable、狀態及錯誤。
2. 自訂 executable 若指向已移除的版本，改成有效 CLI，或清空自訂欄位後重啟 Workspace，讓啟動流程重新偵測。
3. 新增 Agent 各有獨立設定；修改原始 Codex／Claude 不會覆寫其他 instance 的自訂值。
4. 找得到 CLI 不代表 handshake 成功。保留實際錯誤判斷協定或登入問題，不應用新 session 掩蓋它。

官方 backend 要求登入時，使用官方工具處理，不要把 token 或 credential 檔案貼入 Workspace。離線回歸不能證明本機最新版 CLI 已實際連線成功。

## Hermes 設定或連線

原 Local LLM 面板已改接 Hermes。CLI 路徑留白會自動尋找 Hermes；找不到時指定 `hermes.exe`。provider 與模型留白沿用 Hermes 設定；Workspace 不收集或改寫其認證。

舊 `config/local-llm.json` 不再覆蓋已保存的 UI 設定。舊 endpoint、harness 與 executable 不會套用於 Hermes；不必刪除此檔案。新增 Hermes instance 的設定各自保存。

舊 Local harness 的 session 無法由 Hermes 接續；請建立新對話，原歷史仍保存。Hermes native session 遺失或被外部刪除時，錯誤會保留，不會默默建立替代 session。

「檢查 Hermes CLI」與連線只驗證本機 `chat --help` 是否支援 stream-json、query-file、resume 與預算參數。這不會驗證模型推論或認證；送出失敗時查診斷中的 error 與有界 stderr。只接受 Hermes executable，不接受 `.cmd`／`.bat` shell wrapper。詳細邊界見 [HERMES](HERMES.md)。

Hermes provider 的 endpoint 或認證問題須在 Hermes／服務端排查。Workspace 不再執行舊 Local endpoint 的 `/v1/models` 檢查。

Local Connect 不會自動恢復已存對話；開啟舊對話或 Send 時才恢復確切 session。若 Claude 回報 `No conversation found with session ID`，Workspace 紀錄可能仍在，但原生 session 不存在或 cwd 不符。確認 Project 後開啟正確對話，或重新連線並明確按「新增」建立新對話；不會自動刪除歷史或以新對話取代失敗的恢復。

## Session、專案與歷史

核對該 Agent 的 project、task、session，不只看共用導覽。新增 Agent 不跟隨其他 Agent 或 Desktop 焦點。

Connect、匯入 metadata、resume 是不同動作。離線歷史仍可查看；後端工作需連線與正確 session。兩個同類 Agent 控制同一 session 會被拒絕，外部 Desktop 的傳送狀態則無法由此偵測。

側欄原生對話與 adapter 原生探索是不同入口。Claude SDK 探索受 cwd、helper 能力、頁數與大小限制；空清單不表示可搜尋所有專案。請看 capability／error。一般 Claude Chat 尚未支援。

定時同步不是完整雙向同步，Workspace 重新命名與封存不寫回 Desktop。

## 協作沒有前進

Monitor 顯示目前負責者、待核准要求、回合／步數／有效時間及事件。參與者須選相同 project／task、有各自 session，且符合連線要求。

錯誤、逾時、綁定變更、無法關聯的回覆或不明傳送結果，都不能當成可直接重送的情況。先核對歷史與後端結果。重啟程式不會重播協作。

主導者與實作者必須是不同 instance，可同為 Claude。一次 run 尚無多實作者平行排程。

## G8毛與工具紀錄

G8毛 使用釘選的非官方整合，啟動不連線。手動與協作授權規則見 [DOT-UNOFFICIAL](DOT-UNOFFICIAL.md) 與 [DESIGN-auto-collab](DESIGN-auto-collab.md)。舊「官方 bridge 不可用」不等於現在沒有 Dot adapter。

Codex command output 可能是 combined stdout/stderr；空 stderr 不等於沒有錯誤。無 upstream 的 ahead/behind 是未知，Git 查詢失敗不等於工作目錄乾淨。

Artifact 須符合範圍、格式與大小限制；圖片像素不自動遮罩。Raw 是安全過濾後事件，詳見 [SECURITY](SECURITY.md)。

## 測試與維護

`python scripts/run_tests.py` 以每模組獨立程序執行目前頂層測試，報告寫入新的 `evidence/test-runs/` 子目錄。缺少 fixture、Windows symlink 權限或歷史測試不相容會如實顯示。

`tests/legacy_ui/` 不由目前 runner 執行。更多限制見 [tests/README](../tests/README.md)。不要批次執行整個 scripts 資料夾，其中有歷史 live 驗收、部署與一次性文件重寫程式。
