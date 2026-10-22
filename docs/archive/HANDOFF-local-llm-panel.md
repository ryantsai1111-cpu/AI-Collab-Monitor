# 交付規格書 — 第四個角色視窗：Local LLM（跑在 Codex 或 Claude Code 環境內）

> 歷史文件（2026-10-09 標註）：保留原始交付／驗收內容。啟動與現況以 [文件索引](../README.md)、[使用指南](../USER_GUIDE.md) 及 [目前測試紀錄](../../tests/README.md) 為準；文內舊計數、路徑或操作授權不能直接套用本版。部分 evidence 未隨此 checkout 提供。
> 後續使用者已要求自由新增同 provider Agent 與可選主導者，取代本文件固定角色 tuple／不參與協作的舊範圍；目前設計見 [UI-REFRESH](../UI-REFRESH.md)。

> 對象：接手的 AI agent（Codex）。**本文件自足，不需先前對話脈絡。**
> 先讀 `docs/ARCHITECTURE.md`、`docs/ADAPTERS.md`、`docs/UI-REFRESH.md`（PySide6 桌面程式，Python 3.12，無 build 工具）。
> 起點分支：`ui/desktop-workspace-100pct-20261006`。本任務在新 branch `codex/local-llm-panel` 進行，
> **完成並通過驗收前不得 push `main`，也不要直接 push 到起點分支**（合併由審查者／Ryan 決定）。

---

## §0 背景與決策（照做，不要自行改方向）

本程式目前有三個並排的角色視窗：Claude（主審）、G8毛（轉接／複核，非官方 Dot 整合）、Codex（實作）。
Ryan 要新增**第四個視窗**，把他自己的本地模型接進來，而且要「跑在 Claude 或 Codex 的環境裡」——
也就是沿用官方 CLI 的 agent harness（工具呼叫、核准、工作目錄、對話紀錄），只把模型端點換成本地伺服器。

已定決策：

1. 新角色的內部 ID 是 `local`，顯示名稱 `Local LLM`，角色標籤 `本地模型`。
2. **不寫新的聊天協定**。`local` 重用既有 adapter，以薄子類別實作：
   - `LocalCodexAdapter(CodexAdapter)`：**預設 harness**。Codex 原生支援自訂 `model_providers`（OpenAI 相容端點），
     Ollama、LM Studio、llama.cpp、vLLM 都講這個協定。
   - `LocalClaudeAdapter(ClaudeAdapter)`：可選 harness。Claude Code 需要 Anthropic Messages 相容端點
     （例如 Ollama ≥ 0.14，或使用者自備的轉譯代理）。
3. 端點、模型名稱、harness 由使用者在「設定」填寫，存在既有的 `agent.local` 設定鍵。**沒有預設端點**。
4. 設定只能透過**該子程序的命令列參數或環境變數**生效。**絕對不可寫入或修改** `~/.codex/config.toml`、
   `~/.claude/` 下任何檔案，也不可改動目前程序的 `os.environ`（否則會污染真正的 Claude／Codex 視窗）。
5. 既有的 Claude → G8毛 → Codex 交接流程不變。`local` 只出現在每則訊息的「轉交」選單，不加入流程按鈕。

不要改用：自己寫 OpenAI client 直連端點、引入 LiteLLM／LangChain／任何新套件、把角色做成外掛註冊系統。

## §1 不變量（沒有明確同意不得違反）

1. 不引入新的 runtime 依賴；`requirements.txt` 維持只有 `PySide6==6.11.2`。需要 HTTP 就用標準庫 `urllib`。
2. **不過度工程、只做本規格範圍**。角色清單仍是 `AGENTS` 這個 tuple，不要抽象成 registry／plugin。不確定就停下回報。
3. 啟動時不連線、不探測端點、不讀取認證。所有網路行為只發生在使用者按下「連線」之後（與現有三個角色一致）。
4. 不可儲存 API key 明文。若端點需要金鑰，設定只存**環境變數名稱**，啟動子程序時才從該環境變數讀值。
5. 本任務不應觸碰：`acw/security.py`、`acw/adapters/dot.py`、`acw/theme.py`、`acw/assets/`、`AI-Collab-Monitor/`、`tools/`。
   若判斷需要碰，先停下回報。
6. 既有測試必須維持 §2.6 的基準結果；新增邏輯要補測試。
7. commit message 英文；一個邏輯任務一個 commit；secrets 不進 repo。
8. 這台機器的 Codex 沙箱曾有問題（見 `codex-env-diag-20261004/`）。若沙箱內跑不起 Qt 測試，
   **貼出錯誤原文並停下**，不要改測試、不要標示通過。

## §2 現況與整合點（動手前必讀）

### §2.1 角色清單寫死在三處

| 檔案 | 位置 | 內容 |
| --- | --- | --- |
| `acw/core.py` | L13 | `AGENTS = ('claude','dot','codex')` |
| `acw/ui.py` | L28–L32 | `AGENTS`、`ROLE_NAMES`、`ROLE_LABELS` |
| `run.py` | L29 | `for agent, cls, default in [('claude',ClaudeAdapter,...),('dot',DotAdapter,''),('codex',CodexAdapter,...)]` |

新順序固定為 `('claude','dot','codex','local')`——`local` 放最後，既有索引（分頁 0/1/2、Ctrl+1/2/3）不變。

### §2.2 資料表有每個角色一欄（`acw/store.py` L46–L57）

- `projects`：`claude_cwd`、`codex_cwd`、`dot_metadata`
- `tasks`：`claude_session`、`dot_session`、`codex_session`

`store.py` 目前**沒有任何 migration 機制**（只有 `CREATE TABLE IF NOT EXISTS`）。既有使用者資料庫位於
`%LOCALAPPDATA%\AI-Collaboration-Workspace\data\workspace.sqlite3`，必須能直接升級。

### §2.3 `acw/core.py` 中依角色名稱組欄位的地方

L123（`create_project` 寫入 `claude_cwd`/`codex_cwd`）、L164、L329、L343、L363–L365、L397（皆為 `agent+'_session'` 或 `agent+'_cwd'`）。
L236 `if agent=='claude':` 與 L463 `agent=='dot'` 是角色專屬行為，`local` 不應落入這些分支，除非 harness 行為真的需要（需要就回報）。

### §2.4 `acw/ui.py` 中假設三個角色的地方

- L1478 `self._grid_sizes = [400, 400, 400]`
- L1714 `for index, agent in enumerate(AGENTS, 1)` → 快捷鍵會自然多出 Ctrl+4
- L1734 以 `agent + "_session"` 組情境快取鍵
- L1783 `update_workspace_layout`：自動布局判斷「寬度夠不夠放三欄」
- L2094 `for agent in ("claude", "codex")`：更新分支標籤，`local` 也要顯示
- L2290 交接流程 `((1, "claude", "dot"), (2, "dot", "codex"))`：**不要改**
- L2401 歷史頁角色篩選、L2692 設定對話框逐角色建分頁（L2692–L2760）

### §2.5 兩個 adapter 的子程序啟動點

- `acw/adapters/codex.py` L308：`subprocess.Popen([self.executable, "app-server", "--listen", "stdio://"], ...)`，
  沒有傳 `env`。L342 用 `model/list` 取模型；L417 會以 `Model was not advertised by Codex model/list` 拒絕未列出的模型。
- `acw/adapters/claude.py` L104 `_argv()` 組參數；L154 `subprocess.Popen(self._argv(), cwd=self.cwd, ...)`，沒有傳 `env`。
- 兩者的 `__init__(self, emit, executable='', **settings)` 會把 `agent.<id>` 設定原樣收進 `self.settings`（見 `run.py` L30–L33）。

### §2.6 測試基準（2026-10-06 於本機量測，Python 3.12，Windows）

執行方式（PowerShell）：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'; $env:PYTHONPATH = 'vendor;tests'
python -m unittest tests.test_ui_refresh
```

各檔基準結果見 `tests/README.md` 的「Baseline」表。交付時每個檔案的結果必須**等於或優於**該表；
表中標示為已知失敗的項目不需要你修，但不可增加新的失敗。

### §2.7 這台機器目前沒有本地模型伺服器

已確認未安裝 Ollama／LM Studio，埠 11434、1234、8080、8000、5000 皆未開啟。
因此**真實端點的連線驗收不在你的範圍**（見 §5），你的驗收以可重現的離線測試為準。

---

## Task A：資料層與核心支援第四個角色

**要求**：

1. `acw/store.py`：`CREATE TABLE` 加入 `projects.local_cwd` 與 `tasks.local_session`（皆 `TEXT DEFAULT ''`）。
   另加一段冪等的升級：以 `PRAGMA table_info` 檢查，缺欄位才 `ALTER TABLE ... ADD COLUMN`。不要引入版本號表。
2. `acw/core.py`：`AGENTS` 加入 `'local'`；`create_project` 一併寫入 `local_cwd`；確認 §2.3 列出的各處對 `local` 正確運作。
3. `local` 的工作目錄語意與 `codex` 相同（專案 repo 路徑）。

**驗收條件（全部要過，附執行輸出原文）**：

- 新測試：以**舊結構**（不含兩個新欄位）建立一個 SQLite 檔並寫入一筆 project 與 task，再用 `Store` 開啟 →
  兩個新欄位存在、舊資料逐欄位不變、重複開啟第二次不出錯。
- 新測試：`WorkspaceCore` 對 `local` 執行 `create_session`／`resume_session` 後，`tasks.local_session` 正確更新，
  且 `claude_session`／`dot_session`／`codex_session` 不受影響。
- `python -m unittest tests.test_core tests.test_offline_contracts` 結果不劣於基準。

## Task B：Local adapter（兩種 harness）

**要求**：

1. 在 `CodexAdapter` 與 `ClaudeAdapter` 各加一個最小的擴充點，讓子類別能提供「額外參數」與「子程序環境變數」。
   預設實作必須讓既有行為**位元組等價**（既有 argv 不變、未指定時不傳 `env`）。
2. 新檔 `acw/adapters/local.py`：
   - `LocalCodexAdapter(CodexAdapter)`，`agent = 'local'`。以 `-c key=value` 覆寫注入自訂 provider
     （`model_provider`、`model_providers.<id>.name`、`.base_url`、`.wire_api`、必要時 `.env_key`）與 `model`。
     **`-c` 是否被 `codex app-server` 接受、`wire_api` 在已安裝版本的合法值，必須以
     `codex app-server --help` 與官方文件 <https://developers.openai.com/codex/config-advanced> 實際確認後再寫，
     並在回報中貼出確認依據。** 不要憑記憶假設。
   - `LocalClaudeAdapter(ClaudeAdapter)`，`agent = 'local'`。以子程序 `env`（複製自 `os.environ` 後再覆寫）設定
     `ANTHROPIC_BASE_URL`、`ANTHROPIC_AUTH_TOKEN`，並把模型名稱傳給既有的 `--model=` 機制。
   - 工廠函式 `make_local_adapter(emit, **settings)`：依 `settings['harness']`（`'codex'` 預設／`'claude'`）回傳對應子類別。
3. 模型清單：`local` 的模型選單來源是設定中的模型名稱；連線成功後可另外向 `{base_url}/models`（OpenAI 相容）
   查詢並合併。查詢失敗時不可讓連線失敗，只在能力說明中顯示「模型清單查詢失敗」。
   `LocalCodexAdapter` 必須處理 §2.5 提到的 L417 檢查，使設定的本地模型名稱可被送出。
4. `base_url` 驗證：只接受 `http://` 或 `https://`，其餘在「連線」時以明確錯誤拒絕。未設定 `base_url` 或模型名稱時，
   `connect()` 進入 `Offline` 並給出繁體中文訊息「請先在設定填入本地端點與模型名稱」，**不得啟動任何子程序**。
5. API key：設定只存 `api_key_env`（環境變數名稱）。啟動子程序時讀取；該環境變數不存在則以明確錯誤拒絕。
   金鑰值不得出現在 `diagnostics()`、事件、日誌或例外訊息中。
6. `run.py` L29 的註冊迴圈加入 `local`。`executable` 依 harness 沿用對應官方 CLI 的自動偵測結果。

**驗收條件（全部要過，附執行輸出原文）**：

- 新測試檔 `tests/test_local_llm.py`，`subprocess.Popen` 全程 mock，至少涵蓋：
  1. codex harness：實際傳給 `Popen` 的 argv 以既有的 `[exe, "app-server", "--listen", "stdio://"]` 為基礎，並含有 provider／model 覆寫；
  2. claude harness：`Popen` 收到的 `env` 含正確的 `ANTHROPIC_BASE_URL`，且**測試前後 `os.environ` 完全相同**；
  3. 未設定端點 → `Offline`、`Popen` 呼叫次數為 0；
  4. `base_url='file:///x'` 與 `'ftp://x'` → 被拒絕、`Popen` 呼叫次數為 0；
  5. `api_key_env` 指向一個測試用假值 → 該值不出現在 `diagnostics()` 的序列化結果中；
  6. 測試過程不寫入任何位於使用者家目錄下的檔案（以 mock `open`／`Path.write_text` 或檢查暫存 HOME 驗證）。
- `git diff ui/desktop-workspace-100pct-20261006 -- acw/adapters/dot.py acw/security.py acw/theme.py` 輸出為空。
- `python -m unittest tests.test_claude tests.test_codex tests.test_codex_adapter` 結果不劣於基準
  （證明擴充點沒有改變既有兩個 adapter 的行為）。

## Task C：介面第四個視窗與設定

**要求**：

1. `acw/ui.py`：`AGENTS`／`ROLE_NAMES`／`ROLE_LABELS` 加入 `local`。面板、側欄對話分頁、角色分頁、Ctrl+4、
   歷史篩選、訊息「轉交」選單都要出現 `Local LLM`。§2.4 各點逐一處理。
2. 自動布局：寬度足夠時四欄並排；不足時沿用既有的「一次顯示一個角色＋角色分頁」行為。
   每欄最小寬度維持既有的 300。不要新增其他布局模式。
3. 設定對話框的 `Local LLM` 分頁，在既有欄位之外新增：
   - Harness（下拉：`Codex`／`Claude Code`）
   - 端點 Base URL（文字）
   - 模型名稱（文字）
   - API key 環境變數名稱（文字，可空）
   變更後需重新連線才生效，沿用既有的儲存方式（`agent.local` 設定鍵）。
4. 未設定端點時，面板說明列顯示「請先在設定填入本地端點與模型名稱」，「連線」按鈕停用。
5. 外觀完全沿用 `acw/theme.py` 既有樣式，不新增配色、不改 QSS。

**驗收條件（全部要過，附執行輸出原文）**：

- `tests/test_ui_refresh.py::test_three_independent_agent_panels_and_default_roles` 內的分頁數斷言由 3 改為 4，
  並補上第 4 個分頁標題含 `Local LLM` 的斷言。**這是唯一允許修改的既有測試斷言**；其餘 66 個測試不得修改且必須通過。
- 新 UI 測試（放在 `tests/test_local_llm.py` 或新檔），沿用 `tests/test_ui_refresh.py` 的 `OfflineAdapter`／`OfflineWindow` 替身：
  1. 啟動與 `poll_events()` 後，`local` 的 adapter 沒有任何呼叫；
  2. 視窗 1900×950 自動布局 → 四個面板皆可見；760×720 → 只有一個面板可見且水平捲軸最大值為 0；
  3. 在 Claude 訊息的轉交選單可找到 `Local LLM`；交接流程選單項目數量與改動前相同；
  4. 設定對話框存入 harness／base URL／模型後，`core.get_setting('agent.local')` 內容相符。
- 提供一張 1900×950 的實際截圖（真實 Windows 字型，非 offscreen）存於 `docs/evidence/local-llm-panel.png`，
  畫面中四個面板標題與輸入區皆完整可見。

---

## §3 交付總回報格式

每個任務一節：改／增哪些檔（路徑）、驗收逐條 PASS／FAIL 附**執行輸出原文**、根因說明（若有 debug）、未盡事項與風險。
最後附：

- §2.6 全部測試檔逐一執行的結果行（`Ran N tests ... OK／FAILED`）原文；
- `git log --oneline ui/desktop-workspace-100pct-20261006..HEAD`；
- `git diff --stat ui/desktop-workspace-100pct-20261006`；
- Task B 要求的 `codex app-server --help` 相關片段與所依據的文件段落。

過不了的驗收明講卡在哪，不要寫「大致完成」。

## §4 不做（避免範圍擴張）

- 不做自動協作、不做角色之間的自動轉送、不改交接流程。
- 不做端點自動偵測、不做模型下載或管理、不啟動或安裝任何本地伺服器。
- 不重構既有三個 adapter 的協定處理；擴充點以外不動。
- 不新增依賴、不改 `requirements.txt`、不改主題、不建 EXE、不新增 BAT／CMD／PS1 啟動器。
- 不 push `main`。

## §5 上線步驟（給審查者／Ryan，非 Codex 程式碼範圍）

1. 在本機或區網啟動本地模型伺服器，並確認端點可用，例如 Ollama：`http://<host>:11434/v1`（Codex harness）
   或 `http://<host>:11434`（Claude harness，需 Ollama ≥ 0.14）。
2. 開啟程式 → 設定 → `Local LLM` 分頁，填入 harness、Base URL、模型名稱 → 回主畫面按「連線」。
3. 送一則訊息並要求列出工作目錄檔案，確認工具呼叫與核准提示正常。
4. 同時連線真正的 Claude 與 Codex 視窗各送一則訊息，確認它們仍連到官方服務（沒有被本地端點設定污染）。
