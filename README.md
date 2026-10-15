# AI Collaboration Workspace

本機桌面程式（Python 3.12 + PySide6），讓多個 AI Agent 各自選擇 project 與 session，並在同一個視窗工作。預設提供下列四個入口，也可按「＋ Agent」新增 Claude、Codex 或 Hermes。連線由使用者觸發；可獨立工作、手動交接，或明確啟動一次有範圍與上限的自動協作：

| 角色 | 後端 | 預設職責 |
| --- | --- | --- |
| Claude | 官方 Claude Code CLI | 依任務派工／實作／驗收 |
| G8毛 | ChatGPT Dot（非官方整合，每次操作需同意） | 轉接／複核 |
| Codex | 官方 Codex CLI（`app-server`） | 依任務派工／實作／驗收 |
| Hermes（原 Local LLM） | Hermes CLI，沿用其 provider／模型設定 | 第二意見／可選實作者 |

啟動時不連線、不讀取認證、不自動交接、不自動核准。

## 啟動

需要 Windows x64 與 CPython 3.11–3.14（目前使用 3.12）。

```powershell
python run.py
```

- 使用隔離資料：`python run.py --data-dir C:\path\to\data`
- 預設資料位置：`%LOCALAPPDATA%\AI-Collaboration-Workspace\data`
- 不想開終端機：建立一個指向 `pythonw.exe "<repo>\run.py"` 的捷徑即可（`*.lnk` 不進版控）
- 本機資料夾已有 `AI Collab Workspace.lnk`，已確認指向這份 `run.py`。更新後請正常關閉舊視窗再重開。

`run.py` 會優先從同層的 `vendor/` 載入 PySide6（不進版控）；沒有 `vendor/` 時執行 `pip install -r requirements.txt`。

## 接續 Claude Desktop 與 Codex 的對話

側欄的「對話」頁會列出這台電腦上保存的 Claude Desktop（Code）對話與 Codex 對話，分組方式與 Desktop 相同
（有 git origin 的用儲存庫名稱，否則用資料夾名稱）。

- 按兩下或「接續對話」：切換到該資料夾、匯入紀錄，並在對應面板接續同一個對話
- 「⋯」選單：只載入紀錄、在此專案開新對話、重新命名、封存、顯示已封存與系統對話
- 匯入的紀錄包含雙方的文字訊息，以及指令、檔案變更與其他工具紀錄；不含思考過程
- 重新命名與封存只存在這個程式裡，不會寫回 Claude Desktop 或 Codex 的檔案
- 只在開啟「對話」頁之後才讀取；同一個對話不要同時在兩邊傳送訊息

## 核准方式

Claude／Codex 面板的「⋯ → 核准方式」可以選，預設是每次都問：

- **每次都問**
- **自動核准讀取與專案內的檔案編輯**：指令仍然會問
- **自動核准全部**：指令和專案內的編輯都不問

不論選哪一種，這些永遠會問：刪除資料夾、`git push`、強制覆寫、修改系統設定、下載後直接執行、修改專案資料夾以外的檔案。
核准卡片上的「一律允許 <程式>」只在這次連線期間有效，而且不涵蓋用 `&&`、`;`、`|` 串接的指令。

Hermes 的工具核准由 Hermes 既有設定管理；單次 CLI 沒有本視窗的逐次核准橋接，既有設定可能自動允許工具。程式不傳 `--yolo`、不改 Hermes 設定。詳見 [Hermes 整合](docs/HERMES.md)。

## 自動協作

標題列的「自動協作…」分別選擇主導 Agent 與實作 Agent，可以使用 **Claude A 派工 → Claude B 實作 → Claude A 驗收**，也可以選擇不同後端。主導者要求修正時自動交回實作者；只有本次主導者通過驗收才結案。可選擇加入 G8毛 複核與轉交。

- 只在你按「開始」後執行，各參與 Agent 沿用自己的 Project／Session；不要求共用 task，也不會自動改綁定。啟動前顯示綁定預覽，執行中可按「停止」
- 預設 3 回合、24 步、60 分鐘有效時間，啟動時可調整；工具核准等待不計時
- 協作本身不會代替你核准工具；各 Agent 仍依你選定的核准方式處理。尚待核准、錯誤、逾時或回覆格式不符會停止推進
- 選用 G8毛 時，自動傳送與讀取需要每次執行前勾選授權，執行結束即失效；直接模式不需要 G8毛
- 開始時可選擇讓 Hermes 加入：當第二意見（不會擋流程），或取代本次實作角色
- 設計與邊界見 [docs/DESIGN-auto-collab.md](docs/DESIGN-auto-collab.md)

## 新增獨立 Agent

- 對話分頁右側「＋ Agent」選擇後端、名稱與專案；同一後端可以新增多次。
- 各視窗獨立保有 adapter、Project、Session、草稿、核准與串流狀態。在「Agent」頁選 Project、連線後開啟或新增對話；首次直接傳送會準備自己的對話，不需要先填任務表單。
- 「紀錄」頁保留舊任務與狀態管理，切換紀錄不會碰到任何 Agent。開啟主視窗時把舊的共用選取固定為各 Agent 自己的初始綁定，之後不再跟隨全域選取。
- 協作只鎖定參與者，其他 Agent 可以繼續獨立工作；總覽可自行開啟。新對話使用獨立歷史容器，開啟舊 session 回到原本紀錄。
- 原 Local LLM 面板改為 Hermes；每個 instance 可選 CLI 路徑、provider、模型、執行秒數與工具回合上限。provider／模型留白沿用 Hermes 設定，認證仍由 Hermes 管理。
- 關閉程式後會保存 instance、設定與 session 綁定；草稿仍只保留在本次應用程式記憶體。重開不會自動連線或重送工作。
- 同一個 Workspace 內不允許兩個同類 Agent 同時控制同一 native session。此檢查不能偵測外部 Desktop 是否也正在送訊息。
- 目前自動流程為一位主導者與一位實作者，加上既有可選複核。多位實作者平行排程、自動增加隊員、移除／封存 Agent 與 worktree 隔離尚未實作。

## Monitor 工作台與協作總覽

主畫面已套用近黑／磷光綠的控制台主題，可直接在既有 Agent 對話框聊天。預設「專注」：中央主要對話、右側 Agent 狀態側欄；上方可切「並排」或「自動布局」，切換保留原本的草稿、session、核准與工作。布局選擇會保存。窄視窗收起右側欄，以 Agent 分頁切換對話。

標題列「協作總覽」是另外的唯讀頁面，顯示執行規則、派工／驗收、待核准與交接事件。自動協作開始後切到總覽，按 Agent 卡片或「返回工作台」回到操作介面。右側 Agent 狀態及總覽每秒讀取本機狀態，不觸發 backend history 請求；「檢視唯讀對話與 legacy 紀錄」保留原監看模式。重新開啟程式不會自動恢復協作。

更新 UI 後須正常關閉舊視窗，再用原捷徑重開；執行中的 Python 視窗不會熱載入原始碼。一般 Claude Chat、完整 Desktop 雙向同步、聊天中自動識別派工意圖尚未完成。

## 目錄

| 路徑 | 內容 |
| --- | --- |
| `run.py` | 進入點 |
| `acw/` | 程式本體：`core`、`store`（SQLite）、`security`、`ui`、`monitor`、`theme`（控制台主題）、`adapters/` |
| `tests/` | 離線測試；執行方式與基準結果見 [tests/README.md](tests/README.md) |
| `docs/` | 架構、adapter、安全、使用說明；介面現況見 [docs/UI-REFRESH.md](docs/UI-REFRESH.md) |
| `scripts/` | [維護入口與歷史腳本分類](scripts/README.md)；不要批次執行整個資料夾 |
| `tools/` | 釘選版本的 Dot CLI 與 Claude session helper 來源 |
| `AI-Collab-Monitor/` | 舊版 PowerShell 唯讀監看工具（獨立於本程式） |

## 開發與文件

- [文件索引](docs/README.md)：區分現況、設計目標與歷史驗收。
- [清理紀錄](docs/CLEANUP-REVIEW.md)：過時腳本與分包資料已移出使用目錄，可從本機備份還原。
- [使用指南](docs/USER_GUIDE.md)、[疑難排解](docs/TROUBLESHOOTING.md)。
- `python scripts/run_tests.py`：每個頂層測試模組使用獨立程序，保留失敗與略過紀錄；不執行舊 `legacy_ui`。
- `python scripts/run_ui_tests.py`：目前 UI 離線測試。
- `python scripts/package_source.py`：產生含 manifest 的新原始碼 ZIP，排除本機設定、資料庫、憑證、runtime 與驗收產物；不代表可攜 EXE。
- Hermes、手動新增 Agent、Monitor 聊天工作台已實作。完整 Desktop 同步、自然對話啟動派工、多實作者平行排程仍是後續工作；見 [UI-REFRESH](docs/UI-REFRESH.md)。
- 其他 agent 協作工具的做法與本專案的取捨：見 [docs/LANDSCAPE.md](docs/LANDSCAPE.md)

## 歷史文件

- [docs/BASELINE-README.md](docs/BASELINE-README.md)：整理前的 README（EXE 被 Windows 攔截時的驗收狀態）
- [docs/CANDIDATE-PACKAGE-README.md](docs/CANDIDATE-PACKAGE-README.md)：三份 ZIP 候選包的解壓說明
