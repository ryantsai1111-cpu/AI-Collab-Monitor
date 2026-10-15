# AI Collaboration Workspace：介面整理候選版

## 2026-10-15 更新：以 Agent 為中心的工作台

本節取代下方歷史版面的三頁側欄與預設 hacker 描述。預設主題為 desktop；「設定 → 外觀 → 主題」可即時切換 desktop／hacker／metal 並保存至 `ui.theme`。舊的明確主題設定仍保留。

- 專注模式由右側 AgentRail 選取 Agent，隱藏中央角色分頁；並排模式只顯示角色分頁。寬度不足 760、AgentRail 收起時，保留角色分頁作為唯一可見的替代選取器。
- 左欄固定顯示目前 Agent 的名稱、角色與狀態、「目前綁定」及「可接續的對話」，不再有對話／Agent／紀錄分頁或 Claude／Codex 來源分頁。切換統一經由 `select_role` 同步左欄、聊天、成員卡片與頂列標題。
- 可接續對話依目前 Agent 的 provider 列出本機 Claude Code／Codex 歷史，預設只顯示綁定 Project 的正規化目錄；「顯示全部專案」可展開其他專案。未綁定 Project 時顯示全部並停用該核取方塊；Hermes／G8毛 顯示沒有本機歷史對話的說明。
- 「⋯ → 工作紀錄…」保留全域 Project／Task／狀態管理、筆記與匯出，不改任何 Agent 綁定。頂列「工作台 │ 協作總覽」可見切換，時間線／歷史模式下兩格都不選取；時間線、歷史與新增 Agent 仍可從「⋯」操作。AgentRail 底部保留新增 Agent 與並排檢視。
- 麵包屑只顯示於頂列，面板內保留「專案與對話…」操作入口，完整脈絡可由 tooltip 查看。布局選單明確標示「版面」，內部資料值 Auto／Three panes／Focus 維持不變。
- desktop 使用中性邊框、六像素圓角及三級文字層級；橘色 `#d97757` 用於選取中的卡片左框、主要按鈕、目前分頁底線與鍵盤焦點。待核准使用 `#e3b341`，Error／Interrupted／Blocked 使用 `#f27d6b`，其餘狀態維持輔助色。控制台小標與說明降為輔助色。版面間距共用 `SPACE`，圓角共用 `RADIUS`，無新依賴。
- 這次只改 UI、主題、測試與本操作文件。Core、adapter、核准、派工、儲存與資料模型保持原有實作。

## 2026-10-11 更新：Local 改接 Hermes

使用者指定 Local LLM 改用 Hermes CLI，已替換面板、設定與協作 adapter。provider／模型可留白沿用 Hermes 設定；不再設定本程式的 endpoint 或 Claude/Codex harness。工具核准由 Hermes 管理，Workspace 不提供逐次核准橋接。此更新取代下方早期 Local harness 的現況描述，既有歷史與 provider key 保留。操作與驗證見 [HERMES](HERMES.md) 和 [測試 README](../tests/README.md)。

## Monitor 產品方向（2026-10-09 訪談確認，尚未實作完成）

本節記錄使用者目前確認的產品目標；下方舊候選版描述保留為歷史，不代表目前程式狀態。尤其固定角色權責與唯讀 Monitor 的舊限制，不再是新版產品目標。

- Monitor 是主要對話與協作介面，操作感受像 Desktop app。平常可討論、蒐集資料，收到實際工作要求後才開始協作派工，不要求使用者重填任務表單或重述需求。
- 每個 AI 有獨立的 project、session 與選取狀態；目標是與原生 Desktop 及時同步。切換其中一個 AI 不應默默改變其他 AI 的綁定。
- Claude Chat 與 Code 都納入目標，由使用者選擇。完整原生功能是產品方向；各功能仍需依實際整合能力逐項驗證，不能以外觀相似宣稱功能等價。
- Claude 與 Codex 都可以派工或執行，由當次任務決定主導者；不固定誰永遠主審或實作。自動協作需有可見、可調整的規則與執行狀態。
- 使用者提供的 Claude Desktop 畫面，以及 Claude UI Mod、官方 Claude Code Mods，都可作為設計參考。參考授權不等於安裝 Mod 或修改原生 app。
- 同時提供「主要對話＋協作者側欄」及「多個完整對話並排」，由使用者切換模式。切換屬於呈現方式，不應重新派工或改變各 AI 的 project／session；目前實作初次預設專注，後續保存使用者選擇。
- 每個 Agent 視窗各自固定 project／session，持續同步所綁定 session 的內容，不跟隨原生 Desktop 的焦點或 session 切換。此決定取代先前建議的預設自動跟隨。
- 使用者可以自行新增 Agent 視窗，同一 provider 可有多個 Agent，各自在不同 session 執行工作；不限制為 Claude、Codex、G8毛、Local 各一個固定欄位。
- Agent 可獨立聊天或工作，也可加入多人協作；新增視窗本身不表示啟動協作。使用者可按需要增添協作者，包含自己的 Local LLM。
- 整組協作成員可以全部使用 Claude；多人協作不得要求不同 provider，也不得強制加入 Codex 或 Local LLM。同類 Agent 以獨立 instance／session 區別，分工依任務決定。

### 現況與目標的差距

操作邏輯已整理為跟隨目前 Agent 的單頁側欄。日常只選目前 Agent 的 Project／Session；舊任務管理留在「工作紀錄…」對話框，不控制 Agent。初次載入會固定舊共用選取，新對話使用獨立歷史容器，恢復 session 回到原容器。協作沿用各參與者的不同綁定，只鎖定參與者，其他 Agent 可繼續工作。標題、工作詳情、筆記、匯出與 Git 檢視使用目前操作範圍；傳送失敗保留文字與附件，關閉前先停止派工。

目前選取的 Agent 另行保存，不隨本機紀錄切換而改變；各歷史容器仍保存自己的詳情頁與紀錄選取狀態。

2026-10-10 側欄再精簡：Agent 切換只使用主畫面分頁／成員卡片；側欄顯示選取 Agent 名稱、一組 Project／Session 及新對話／開啟對話。重新命名、ID、原生探索與工作目錄／Git 資訊移到 Session 的「⋯」；檢視模式移到右上「⋯ → 檢視」。Local Agent 的 Session 選單可直接開啟自身設定分頁。保留原操作的能力與核准限制，不因精簡畫面而放寬。

目前主畫面已成為可操作的「Monitor 工作台」，重用既有 AgentPanel，提供專注對話＋Agent 側欄、並排與自動布局；另保留「協作總覽（唯讀）」和 legacy transcript 模式。協作仍由明確對話框啟動，尚不會從一般聊天自動推定派工。Claude 原生探索涵蓋 Code session，一般 Chat 尚未整合；歷史同步仍是定時更新，部分重新命名與封存只作用於本工作區，並非完整 Desktop 雙向即時同步。

Core 與 UI 已完成第一階段的 provider／Agent instance 分離，支援手動新增 Claude／Codex／Local Agent，各有獨立 adapter、設定、session、草稿、核准與執行狀態。新增視窗與 Monitor 工作台已連動；兩個 Claude 的直接派工／驗收有離線驗證。現有 Local adapter 仍透過 Claude 或 Codex CLI harness 連線，可為各 instance 設定 endpoint。原生一般 Chat、完整雙向同步、多實作者平行排程、自動新增協作者、Agent 移除／封存與 worktree 管理尚未實作。

### 視覺方向：駭客工作台（2026-10-09，歷史）

當時採用以下 terminal／資安控制台方向；2026-10-15 起預設改為 desktop，hacker 留作可選主題：

- 近黑背景 `#080d0c`、深綠灰面板 `#101816`、細邊框與小圓角，維持清楚的資訊層級。
- 磷光綠 `#a3e635` 用於重點與鍵盤焦點；執行中為青色、已連線為綠色、等待為琥珀色、錯誤為粉紅紅色。狀態同時保留文字，不只靠顏色。
- 英文狀態、數字及事件流使用本機 Cascadia Code／Consolas，中文內容保留正黑體 fallback；不新增字型下載或依賴。
- 無裝飾性假 log、隨機數據、閃爍或掃描線；真實事件、工作狀態與選取焦點形成視覺節奏。
- 保留專注／並排模式的產品目標。窄視窗需重排內容並保留可讀字級，切換布局不應影響工作。

首次只套用於總覽，使用者回報主 UI 未變後，本輪已把控制台主題套用到主視窗、側欄、對話、輸入框及選單。初次布局預設專注，後續保存使用者選擇；重開來源程式才會載入新版，不熱更新正在執行的視窗。右側 AgentRail 顯示每個 instance 的 project／session／狀態，切換保持相同元件、草稿和執行狀態，不送出工作。總覽仍可單獨開啟且保持唯讀。`tests/render_workbench.py` 產生 1500×1000 專注、1800×1000 並排、650×900 窄版的合成 Qt 畫面，位置為 `evidence/monitor/workbench-*.png`；不能作為真實後端驗收證據。

驗證：`test_collaboration_monitor` 28 項離線測試通過；修改的 Python 檔案通過 `py_compile`。已實際渲染並檢視 1500×1060 與 650×960 的 Qt 畫面，Monitor 在窄內容區會改為單欄。截圖位置為 `evidence/monitor/wide.png` 與 `evidence/monitor/narrow.png`。

### 參考與適用範圍

- [Claude UI Mod](https://gitlab.com/blockshooter/claude-ui-mod/-/raw/main/README.md)：可借鏡協作者進度、任務列、訊息佇列、各 session 狀態與用量呈現。README 的功能宣稱尚未在本機驗證；其原生 app patch 方式不直接適用於本專案的 PySide6 架構。在 Claude harness 內路由其他模型也不等於操控獨立 Codex app session。
- [官方 Claude Code Mods](https://code.claude.com/docs/en/plugins/mods/overview)：可研究事件、工具狀態及對話旁面板的擴充介面；文件範圍涵蓋 CLI 與 Desktop Code 分頁，不構成一般 Chat 整合的證據。

### GitHub 調研與架構建議（2026-10-09）

本次只查閱公開文件與部分來源碼，未安裝或執行外部專案，也未驗證其功能在本機成立。

| 來源 | 已查到的做法 | 本專案可借鏡之處 |
| --- | --- | --- |
| [Agent Deck](https://github.com/asheshgoplani/agent-deck) | 多工具 session 清單、分組、狀態、fork 與 conductor；README 的 Windows 支援標示為 WSL | 將 session 登錄與分組獨立於 provider，讓多個 Claude 也可同時存在；以待處理狀態引導 Monitor 注意力 |
| [Claude Squad](https://github.com/smtg-ai/claude-squad)／[Instance 來源碼](https://github.com/smtg-ai/claude-squad/blob/main/session/instance.go) | 每個 instance 保存 program、path、branch、status、worktree；來源碼對 tmux session 消失有 Paused 恢復路徑 | 分離 Agent 生命週期與視窗生命週期，記錄實際工作目錄；平行改碼可用各自 worktree，整合時仍需解決衝突 |
| [Claude Team Orchestration](https://github.com/zircote-plugins/claude-team-orchestration) | 基於 Claude Code Teams 的共享任務、訊息及不同協作流程 | 流程可依任務選擇，例如平行調查、實作後審查，而非綁死 provider 順序 |
| [官方 Agent Teams](https://code.claude.com/docs/en/agent-teams) | 多個 Claude Code 共同任務與傳訊；文件仍列實驗性、固定 lead、in-process 隊員無法隨 resume 還原等限制 | 可作為後端能力之一；Monitor 的自由組隊、身分與恢復設計不能完全依賴原生 team |
| [官方 Cross-session Messaging](https://code.claude.com/docs/en/cross-session-messaging) | 獨立 session 間傳文字訊息，有 Windows named pipe 路徑及各 session 的接收控制；訊息不是自動分享全部歷史 | 同類獨立 session 互通有原生整合線索，須先驗證本機版本、能力與 adapter 模式；仍需任務關聯、回執與派工紀錄 |

以下是架構方向；已完成範圍以上方「現況與目標的差距」為準，尚未完成部分不代表已核准的自動化政策：

1. **Provider profile**：後端類型、模型及 endpoint 設定；同一 profile 可建立多個 Agent。Local 憑證只保存環境變數名稱。
2. **Agent instance**：唯一 ID、自訂名稱、固定 project／session、連線、草稿、核准與執行狀態。視窗僅呈現 instance，收合或換布局不應停止工作。
3. **Collaboration run**：獨立的任務、參與 instance、依賴、當次分工及規則。可全 Claude 或混合 provider；單獨工作的 instance 不必加入任何 run。
4. **Dispatch records**：每次派工保存來源、目的、run／task／request ID、交付範圍與回執。沿用現有不確定傳送不重送的原則；能力不足要明確呈現。
5. **並行與恢復**：執行上限與 Agent 視窗數分開；以實際後端能力排程。重啟先核對仍在執行的工作與 session，不能直接重播任務。平行寫入採隔離工作目錄或明確協調寫入，worktree 並不消除最終 merge 衝突。

`acw/orchestrator.py` 已改為 instance 路由，可選同 provider 的不同 instance 派工與實作。Qt 架構保留，研究到的 tmux／WSL 執行方式沒有成為新依賴。以上 Code 專案也不能證明一般 Claude Chat 或完整 Desktop 同步已可用。

### 下一個待確認決策

兩種布局及各視窗固定 session 均已確認。下一步釐清 Agent 能否自行新增協作者，以及相關資源與參與範圍；後續仍需確認雙邊操作同一 session 的衝突處理、派工時的上下文分享、完成判定與中斷恢復。

此完整來源包是供開發與審查的候選版，不代表 Final 驗收、Windows 啟動、EXE 或真實後端已通過。主要設計與截圖以 100% 縮放為準；沒有改動任何人的 Windows 顯示設定。

## 原始碼基準

- 主程式基準：`40bd6ba8c3265e85fe28237176b995b7915a62f5`
- 完整輸入清單：`b58c1760a56a003cd78e627541137dc135d671a0`
- 後兩次上傳只新增工具來源與 ZIP，未修改原有主程式
- 取得並核對 105 個合格文字檔；排除舊版監看、診斷資料、位元組碼、ZIP、日誌、資料與秘密檔
- GitHub 文字連接器無法提供 5.4 MB `tests.zip` 的有效位元組。未繞道使用含權杖的下載網址，也未把舊測試判定為通過

## 介面改動

1. 可收合側欄只顯示目前 Agent 的綁定與可接續對話；舊任務及狀態移至「⋯ → 工作紀錄…」
2. 專注顯示 AgentRail、並排顯示角色分頁；窄視窗改用分頁，每次只顯示一個 Agent 選取器，不重建聊天元件
3. 模型與思考強度放在各輸入框下方；G8毛顯示「由 ChatGPT 管理」，完整能力與限制可由角色選單查看
4. 設定、診斷及低頻操作放在次要選單／對話框
5. 工作詳情預設收合，提供工具、命令、變更、測試、時間線與交接。短視窗使用非模態詳情對話框，避免擠掉聊天區
6. 草稿、附件、原生對話選取、模型／強度選取、文字選取、捲動位置、展開事件與詳情選取依專案、任務和原生對話映射保留於本次應用程式記憶體。切換不傳送或丟棄草稿
7. 隱藏角色有待核准要求時，角色分頁顯示「待核准」。按該分頁才切換角色；不搶焦點或自動核准
8. Ctrl+Enter 僅在輸入法已結束組字後傳送；Enter 仍換行
9. 模型更換後若先前強度不支援，必須明確選擇支援值才能傳送，不靜默降級。未偵測、偵測失敗、選項不可用與不支援分開顯示

## 既有功能位置對照

| 原有功能 | 現在位置與行為 |
| --- | --- |
| 專案建立／選取 | 左側「專案與對話」；＋建立專案 |
| 任務建立／選取／狀態 | 左側任務選單、＋和「任務狀態」 |
| 同步工作目錄 | 右上工作區選單「同步專案至角色」 |
| 三角色獨立連線／中斷連線 | 各聊天標頭「連線／中斷連線」 |
| 原生對話建立／恢復／重新命名／ID | 側欄角色分頁「新增／恢復／重新命名／詳細」 |
| 本機對話搜尋／原生探索 | 側欄搜尋與「探索原生對話」；探索仍需明確操作 |
| 原生歷史預覽／匯入 | 原有探索對話框，能力與輔助程式需求不變 |
| G8毛 選擇／重新整理／較早訊息 | 側欄 G8毛 分頁；原有每次手動同意仍保留 |
| 模型／思考強度 | 各輸入框下方，真實後端選項；能力在角色 ⋯ 選單 |
| 傳送／停止／附件／清除附件 | 各聊天輸入區；附件僅於後端支援時可用 |
| 訊息複製／中繼資料／原始事件／轉交 | 每則訊息選單與轉交按鈕 |
| Claude → G8毛 → Codex 交接 | 工作詳情「交接」中的流程選單；每一步需手動操作 |
| 預覽後傳送／手動直接傳送 | 工作詳情「交接」；既有設定值不變 |
| 待核准的工具要求 | 聊天區上方固定「等待核准 · 檢視」與角色分頁提醒；核准仍需人類確認 |
| 工具／命令／檔案／測試事件 | 聊天內可收合事件；工作詳情相應分頁 |
| 原始事件／日誌／專案檔案／本機歷史 | 角色 ⋯ 選單 |
| 差異／測試／附件／截圖預覽與匯出 | 工作區 ⋯「差異／測試／附件」與工作詳情變更／測試入口；原安全檢查不變 |
| 完整時間線／跨任務歷史搜尋 | 右上「⋯ → 檢視」；工作詳情時間線可開啟完整頁 |
| 舊版唯讀監看 | 側欄「檢視 → 監看（唯讀）」；未加入任何控制原程序的功能 |
| 任務筆記／回覆比較／匯出 | 工作區 ⋯ 選單 |
| 設定／診斷／停止目前任務 | 工作區 ⋯ 選單；側欄也有設定 |
| 視窗位置／最上層／全螢幕 | 原設定保留；F11 |

原介面 16 個類別、119 個方法全部保留。Core、Store、Security、Inspection、Presentation 及三個 adapter 的來源未修改。這是程式結構檢查，不能代替 Windows 真實後端驗收。

## 界限

- 不連線、不重新連線、不恢復對話、不重送提示、不自動交接、不自動批准
- 現有本機事件佇列與唯讀 Git／舊監看處理保持原行為；未新增私有 API 輪詢
- 本次不呼叫 Claude、Codex 或 G8毛 真實後端，也不讀取認證
- 不改動角色預設：Claude 主審，G8毛 轉接／複核，Codex 實作
- 保留原安全過濾；不顯示、重建或要求隱藏思維鏈，只有原系統允許的明確摘要可顯示
- 未增添 Web server、框架遷移、EXE、部署或防毒繞過
- 草稿只保證本次應用程式內導航保留，尚未新增跨重啟草稿保存
- 工具來源已取得，但輔助工具依賴未在雲端安裝／執行；這不等於原生歷史或 Dot 連線已驗證
- Windows 實體螢幕、Narrator、真實中文輸入法、啟動與後端需在 Ryan-PC 可執行後另行驗證

## 原始碼啟動

此候選包已包含 run.py、requirements.txt、acw、所需工具來源與新測試，不需手動組裝補丁；仍需既有相容的 Python／PySide6 執行環境。請勿覆蓋既有資料目錄。

1. 解壓縮後確認根目錄包含 run.py、requirements.txt、acw/
2. 使用原有相容的 Python 3.12 與 PySide6 6.11.2 執行環境
3. 標準開發入口為 `python run.py --data-dir <新的隔離資料夾>`
4. 此入口尚未在 Windows 驗證；不是避開 Windows 安全限制的承諾
5. 若 Windows 攔截，請停止並保留錯誤訊息，不需關閉或變更安全設定

使用者回報 Windows Smart App Control 攔截 BAT，本完整來源包因此不包含 BAT／CMD／PS1 替代啟動器。既有 Python 開發入口仍未在 Windows 驗證；本包未附帶 Python 或 PySide6。不要為執行本包更改安全設定，也不建議重新命名、解除封鎖或移除來源標記。

## 離線測試

使用獨立資料夾、記憶體替身及 offscreen Qt，沒有真實認證／網路／代理程序。

`QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v`

測試替身不證明真實後端或 Windows 啟動。截圖是實際 Qt 空白／離線畫面，沒有填入假訊息、工具事件或成功結果。

## 獨立審查後的狀態修正

- 不相容的思考強度會保留「需明確選擇」狀態，能力更新、重新整理和任務切換不會自動改成第一個可用值
- 新任務採用一致的真實預設／支援選項，不沿用另一任務的待選擇提示
- 即使目前顯示另一任務，已取消或已回覆的核准要求也會從原任務快取移除；還原前另以本機持久紀錄核對
- 還原的固定核准提醒使用確切後端 request_id，不把事件紀錄 ID 當成核准識別碼
- 審查後新增八個回歸測試；最新測試紀錄為 85 個離線測試通過，仍不代表真實後端或 Windows 驗收

## 金屬風格主題（2026-10-06）

- 樣式集中在 `acw/theme.py`：深槍灰機殼、拉絲鋼板面板、鍍鉻按鍵、內凹黑色顯示窗、狀態指示燈
- `acw/assets/` 的拉絲紋理與箭頭圖由 `theme.py` 以固定種子在本機繪製，缺檔時會自動重建
- `run.py` 固定使用 Qt 的 Fusion 樣式，避免 Windows 11 原生樣式讓彈出選單變成黑底
- 修正：舊樣式的 `QFrame#panel QWidget { background: transparent; }` 會套到彈出選單與下拉清單，造成黑底深色字
- 修正：過長且無法斷行的工作目錄路徑不再把側欄撐寬
- 介面結構、控制項、物件名稱與行為均未改動；`tests/test_ui_refresh.py` 67 項維持通過

上方「原始碼啟動」一節提到本包不含啟動器；現在可自行建立指向 `pythonw.exe "<repo>\run.py"` 的 Windows 捷徑（`*.lnk` 不進版控）。

## Desktop 風格主題（2026-10-06，目前預設）

- 預設主題改為仿桌面 app 的扁平深色：暖灰底、細邊框、圓角、橘色強調色；金屬主題仍保留，設定鍵 `ui.theme` 設為 `metal` 即可切回
- 輸入區改為單一圓角方框，內含輸入欄、模型、思考強度、附件、核准方式、停止與傳送
- 對話區不再有外框與內凹底色；側欄清單為無邊框列表
