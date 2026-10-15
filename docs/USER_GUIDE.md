# AI Collaboration Workspace — 使用指南

更新日期：2026-10-15。對應目前 Python／PySide6 介面；驗證範圍見 [測試紀錄](../tests/README.md)。舊 EXE、三份 ZIP 與歷史驗收文件不代表目前啟動方式。

## 啟動與資料

在專案根目錄執行：

```powershell
python run.py
```

本機資料夾已有 `AI Collab Workspace.lnk`，指向同層 `run.py`；雙擊即可啟動。已開啟的視窗需正常關閉再載入更新。捷徑不隨 Git 散布。程式優先使用 `vendor/` 的 PySide6，請保留此資料夾。

預設資料位於 `%LOCALAPPDATA%\AI-Collaboration-Workspace\data`。同一資料目錄一次只能開一個視窗。隔離測試可用：

```powershell
python run.py --data-dir C:\path\to\isolated-data
```

重開會還原 Agent、設定、project／task／session 綁定與本機歷史，不自動連線、resume 或重送任務。草稿只保留在本次程式記憶體。

## Project、Session 與獨立 Agent

1. 專注模式按右側成員卡片、並排模式按上方分頁選擇 Agent；窄視窗收起右欄時也使用上方分頁。左側欄自動跟隨目前 Agent，顯示角色、狀態與綁定的 Project／Session；Project 旁邊「＋」可建立專案。
2. 在 Agent 面板按「連線」。Claude／Codex 已有綁定 session 時會接續它；Hermes 先檢查 CLI 協定，按「開啟」或 Send 才恢復已保存的 Hermes 對話。沒有 session 時可按「新對話」，或直接輸入首次訊息。忙碌中的 Agent 必須完成或停止工作後才能切換。
3. 右側 Agent 欄底部按「＋ 新增 Agent」，或從右上「⋯ → 新增 Agent…」，選 Claude、Codex 或 Hermes、名稱與專案。同一 provider 可建立多個視窗，新增本身不連線或送出任務。
4. Session 下拉清單只列出此 Agent／Project 已保存的對話。選取本身不會開啟；按「開啟對話」才接續原 session 與歷史。「新對話」建立獨立歷史，不覆蓋原對話。

側欄上半「目前綁定」保留 Project、Session 搜尋／選取與「新對話／開啟對話」，下半「可接續的對話」顯示目前 Agent 的本機歷史。Session 旁「⋯」提供重新命名、詳細／ID、探索原生對話與專案資訊（工作目錄、Git 狀態）；Hermes Agent 另有「Hermes 設定…」，直接開啟該 instance 的設定分頁。側欄不再重複顯示 Agent 分頁或工作目錄／Git 詳情。檢視模式改從右上「⋯ → 檢視」切換。

聊天不需要先建立或選擇任務。內部沿用 task 表保存歷史關聯，不改 DB schema。右上「⋯ → 工作紀錄…」對話框保留舊任務、筆記與狀態；這些選取只供紀錄管理，不會切換 Agent。主視窗第一次載入時固定舊共用選取，往後各自獨立。工作區保存 Agent 定義、設定、綁定與視窗布局，不強制共用 Project。

切換檢視或其他 Agent 不會重新派工。文字、附件與畫面狀態按情境保存在本次記憶體；關閉前請處理尚未送出的草稿。綁定規則見 [AGENT-CONTEXTS](AGENT-CONTEXTS.md)。

## 連線與模型

| Provider | 整合方式 |
| --- | --- |
| Claude | 官方 Claude Code CLI；能力依實際 handshake 回報 |
| Codex | 官方 Codex CLI 的 app-server |
| Hermes（原 Local LLM） | Hermes CLI 的 stream-json，provider／模型可沿用 Hermes 設定 |
| G8毛 | 釘選的非官方 Dot 整合；手動操作有個別同意，協作有本次 run 的範圍與上限 |

「設定」可調整各 Agent 的 CLI 與模型；每個 Hermes Agent 有自己的 executable、provider、模型、執行預算與回合上限。provider／模型留白沿用 Hermes 設定。設定會在下次明確連線時套用，憑證值不填入程式設定。

Hermes 設定頁的「檢查 Hermes CLI」使用目前表單值執行 CLI help，不儲存、不建立 session、不做推論。成功只代表協定可用，認證、推論與工具仍須實際驗證。

舊 `config/local-llm.json` 不再覆蓋已存設定。只有明確指定 `harness: "hermes"` 且沒有已存 Local 設定時才作一次性 seed；新增 instance 各自保存。舊 example JSON 保留作歷史參考。詳見 [Hermes 整合](HERMES.md)。

Claude／Codex 連線到已有綁定 session 時會接續它，不讀取其他對話；未綁定者只連接後端。Local 的連線與恢復分開，開啟或 Send 時才恢復指定 session。模型／effort 依後端能力提供；Local 模型使用自己的設定。斷線或找不到原 session 時不會默默建立替代對話。首次明確傳送才準備尚未建立的對話；傳送失敗保留文字與附件，不自動重送。

## 原生對話與同步

側欄「可接續的對話」只列目前 Agent 的 provider 對應的本機 Claude Desktop **Code** 或 Codex 歷史，一般 Claude Chat 尚未整合。預設依綁定 Project 的目錄篩選；勾「顯示全部專案」可瀏覽其他資料夾。尚未綁定 Project 時顯示全部並停用該核取方塊。Hermes／G8毛 會顯示沒有本機歷史對話的說明。可只載入紀錄、接續對話，或在所選專案開新對話。重新命名與封存僅作用於 Workspace，不寫回 Desktop。

各 Agent 綁定自己的 session，以定時更新同步內容，不跟隨 Desktop 焦點。目前不是完整雙向即時同步。新增 instance 可透過自己的 session 控制與「探索原生對話」使用後端支援的功能。

探索、唯讀預覽、匯入 metadata、resume 是不同操作，依畫面說明執行。同一 Workspace 禁止兩個同類 Agent 同時控制同一 native session；程式無法偵測另一個 Desktop 是否也正在送訊息。

## 聊天、核准與轉交

Ctrl+Enter 傳送、Enter 換行。各 Agent 的停止操作只針對自身工作，是否支援取決於 adapter。附件依模型能力及允許路徑提供。

Claude／Codex 的「⋯ → 核准方式」預設每次詢問，也可明確選擇自動核准讀取／專案編輯或全部模式。Hermes 則沿用自身單次工具核准設定，可能自動允許工具，本視窗不能逐次核准；Workspace 不傳 `--yolo`、不改 Hermes config。詳見 [SECURITY](SECURITY.md)。

訊息的「轉交」可選其他 Agent。「預覽後傳送」先查看 envelope 與補充說明；「手動直接傳送」以點選目標作為傳送動作。來源訊息與註解分開保存，狀態不明的傳送不會在重啟後自動重試。

## 自動協作

標題列「自動協作…」選主導者、實作者、任務及執行限制。可使用 Claude A → Claude B → Claude A，也可混用 provider。主導者決定是否通過驗收，未通過則交回修正。

參與者須連線、選好各自 Project 與對話；可以使用不同 project／task。啟動前確認綁定預覽，流程不會默默調整它們。協作只鎖定參與者，其他 Agent 可以繼續工作。可選 G8毛 複核／轉交或 Hermes 第二意見。預設 3 回合、24 步、60 分鐘有效時間，啟動時可調整。核准等待不計時；錯誤、逾時、參與者綁定變更或無法關聯的回覆會停止推進。可隨時要求停止。

目前一個 run 為一位主導者、一位實作者及可選複核，尚無多實作者平行排程、自動增添隊員或 worktree 隔離。詳見 [DESIGN-auto-collab](DESIGN-auto-collab.md)。

## Monitor 與工作紀錄

主畫面「Monitor 工作台」可直接操作各 Agent 對話，預設為暖灰底的 desktop 主題；「設定 → 外觀 → 主題」可立即切換 desktop／hacker／metal 並保存選擇，關閉設定對話框也保留即時主題選擇。預設專注模式有主要對話與右側 Agent 狀態欄；點右側成員只切換操作對象，不會改 project／session 或啟動工作。窄視窗自動收起狀態欄，改由上方 Agent 分頁切換。desktop 主題以黃色標示待核准、紅色標示錯誤／中斷／受阻，其餘狀態維持輔助色。

標題列「工作台 │ 協作總覽」切換的「協作總覽」，或「⋯ → 檢視 → 協作總覽（唯讀）」顯示規則、派工／驗收、待核准項目與交接事件。時間線／歷史模式下，頂列這兩格都不選取。總覽仍是唯讀頁，按頂列「工作台」或 Agent 卡片回到可操作對話。右側欄及總覽每秒更新本機狀態，不會因此讀取 backend 原生歷史。

頂列「版面」可切換自動、專注或並排並保存選擇，原本的聊天元件、草稿、附件與 session 不會因切換而重建。工作詳情、筆記、匯出與 Git 檢視依目前 Agent 的對話／專案；「工作紀錄…」對話框開啟時則使用所選紀錄，關閉後回到目前 Agent 的脈絡。歷史頁雙擊任務只查看本機紀錄，不會恢復 Agent。Tests 顯示已觀察到的結果，不會因開啟畫面就執行測試。Git diff 檢視不包含 commit、push 或 merge 操作。

匯入 artifact／截圖、匯出 task 與診斷有各自檢查。圖片像素不自動遮罩，匯出圖片需檢視確認。診斷不收集 backend credential 檔案；Raw 是安全過濾後的公開事件，不包含隱藏 reasoning。

舊 `AI-Collab-Monitor/` 是獨立 PowerShell 工具；Workspace 只讀取指定 legacy root 的既定 log，不啟動、重設或清除它。

## 結束與限制

正常關閉保存視窗與持久化資料，有工作時依畫面確認是否取消。重新連線前可先查本機歷史與「診斷」。

目前驗收主要為離線測試，完整原生 Chat、雙向同步與多 Agent 真實並行仍需驗證。歷史 PASS 計數不等於本版完整驗收。問題排查見 [TROUBLESHOOTING](TROUBLESHOOTING.md)。
