# AI Collaboration Workspace

本機桌面程式（Python 3.12 + PySide6），把三個 AI 角色放在同一個視窗並排協作，所有連線與交接都由人手動觸發：

| 角色 | 後端 | 預設職責 |
| --- | --- | --- |
| Claude | 官方 Claude Code CLI | 主審 |
| G8毛 | ChatGPT Dot（非官方整合，每次操作需同意） | 轉接／複核 |
| Codex | 官方 Codex CLI（`app-server`） | 實作 |

啟動時不連線、不讀取認證、不自動交接、不自動核准。

## 啟動

需要 Windows x64 與 CPython 3.11–3.14（目前使用 3.12）。

```powershell
python run.py
```

- 使用隔離資料：`python run.py --data-dir C:\path\to\data`
- 預設資料位置：`%LOCALAPPDATA%\AI-Collaboration-Workspace\data`
- 不想開終端機：建立一個指向 `pythonw.exe "<repo>\run.py"` 的捷徑即可（`*.lnk` 不進版控）

`run.py` 會優先從同層的 `vendor/` 載入 PySide6（不進版控）；沒有 `vendor/` 時執行 `pip install -r requirements.txt`。

## 接續 Claude Desktop 與 Codex 的對話

側欄的「對話」頁會列出這台電腦上保存的 Claude Desktop（Code）對話與 Codex 對話，分組方式與 Desktop 相同
（有 git origin 的用儲存庫名稱，否則用資料夾名稱）。

- 按兩下或「接續對話」：切換到該資料夾、匯入紀錄，並在對應面板接續同一個對話
- 「⋯」選單：只載入紀錄、在此專案開新對話、重新命名、封存、顯示已封存與系統對話
- 匯入的紀錄包含雙方的文字訊息，以及指令、檔案變更與其他工具紀錄；不含思考過程
- 重新命名與封存只存在這個程式裡，不會寫回 Claude Desktop 或 Codex 的檔案
- 只在開啟「對話」頁之後才讀取；同一個對話不要同時在兩邊傳送訊息

## 目錄

| 路徑 | 內容 |
| --- | --- |
| `run.py` | 進入點 |
| `acw/` | 程式本體：`core`、`store`（SQLite）、`security`、`ui`、`theme`（金屬風格樣式）、`adapters/` |
| `tests/` | 離線測試；執行方式與基準結果見 [tests/README.md](tests/README.md) |
| `docs/` | 架構、adapter、安全、使用說明；介面現況見 [docs/UI-REFRESH.md](docs/UI-REFRESH.md) |
| `scripts/` | 歷次驗收與打包用腳本（多數依賴當時的本機環境） |
| `tools/` | 釘選版本的 Dot CLI 與 Claude session helper 來源 |
| `AI-Collab-Monitor/` | 舊版 PowerShell 唯讀監看工具（獨立於本程式） |
| `codex-env-diag-20261004/` | Codex 沙箱問題的診斷紀錄 |

## 進行中的工作

- 第四個角色視窗（Local LLM，跑在 Codex 或 Claude Code 環境內）：規格見 [docs/HANDOFF-local-llm-panel.md](docs/HANDOFF-local-llm-panel.md)
- 其他 agent 協作工具的做法與本專案的取捨：見 [docs/LANDSCAPE.md](docs/LANDSCAPE.md)

## 歷史文件

- [docs/BASELINE-README.md](docs/BASELINE-README.md)：整理前的 README（EXE 被 Windows 攔截時的驗收狀態）
- [docs/CANDIDATE-PACKAGE-README.md](docs/CANDIDATE-PACKAGE-README.md)：三份 ZIP 候選包的解壓說明
