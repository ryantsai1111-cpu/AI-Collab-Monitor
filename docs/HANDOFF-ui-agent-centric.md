# 交付規格書 — 以 agent 為中心的工作台版面（方案 A）

> 對象：接手的 AI agent（Codex）。**本文件自足，不需先前對話脈絡。**
> 先讀 `docs/ARCHITECTURE.md`、`docs/UI-REFRESH.md` §介面改動、`docs/USER_GUIDE.md` §Project、Session 與獨立 Agent 了解現況
> （技術棧：Python 3.12 + PySide6 桌面程式，`python run.py` 啟動，離線測試 `python scripts/run_tests.py`）。
> 本任務在新 branch `codex/ui-agent-centric`（從 `main` 切）進行，**完成並通過驗收前不得 push main**（合併由審查者 Claude／Ryan 決定）。
> **這個 checkout 正被使用者開著的 GUI 使用。請用 `git worktree add ../AI-Collab-Workspace-ui codex/ui-agent-centric` 在另一個目錄工作，不要在本目錄改檔。**

---

## 0. 背景與決策（照做，不要自行改方向）

使用者（Ryan）對目前主視窗的評價：「整個 UI 很醜；左側欄位跟右邊整個好像完全沒關聯。」審查者（Claude）診斷後的結論與已定決策：

1. **同一組 agent 在三個地方各自選取**：左側欄的 Claude／Codex 來源分頁、中央的 `role_tabs` 分頁列、右側 `AgentRail` 卡片。三者只靠 `MainWindow._preferred_agent` 間接同步，使用者看不出它們是同一件事。
2. **左側欄「對話」清單不是這個 app 的資料**：它列的是 Claude Desktop／Codex 存在本機的歷史對話（`acw/desktop_sessions.py` 掃 transcript 目錄），右側 agent 面板綁的是 app 自己的 project › task › session。兩者只在「接續對話」（雙擊）時才接上。
3. **視覺沒有層級**：全部用同一種螢光綠（hacker 主題）框線與文字，標題、分頁、按鈕、卡片權重一樣。`docs/UI-REFRESH.md:181` 寫預設是 desktop 主題，程式實際套的是 hacker（`acw/ui.py:2280`）。

**決策（方案 A，已排除方案 B「Projects → Agents → 對話」的三欄式，因為它要改 project 的資料模型）**：

- 右側 `AgentRail` 是**唯一可見的 agent 選取器**（專注模式）。並排模式下所有面板都看得到，此時用 `role_tabs` 當選取器；兩者永遠只有一個顯示。
- 左側欄**永遠顯示「目前選到的 agent」的脈絡**：上半是它的綁定（project / task / session，就是現在藏在「Agent」分頁裡的 `session_controls`），下半是「可接續的對話」（本機歷史，只列這個 agent 的 provider，預設只列它綁定的那個專案資料夾）。換 agent，左欄整個跟著換。
- 麵包屑只留頂列一處；「專注」下拉改名「版面」；工作台／協作總覽改成頂列可見的切換。
- 預設主題改為 desktop（文件早就這麼寫），強調色只用在「選取中」與主要按鈕，統一間距常數。
- **不改任何後端行為**：`acw/core.py`、`acw/adapters/*`、`acw/requests.py`、`acw/orchestrator.py`、`acw/store.py` 本任務一行都不動。

## 1. 不變量（沒有明確同意不得違反）

1. 只動 `acw/ui.py`、`acw/monitor.py`（`AgentRail` 部分）、`acw/theme.py`、`acw/presentation.py`（若需要）、`tests/*.py`、`docs/UI-REFRESH.md`、`docs/USER_GUIDE.md`。其他檔案不碰；若判斷必須碰，先停下回報。
2. **不過度工程、只做本規格範圍**。不要重寫 `AgentPanel`、不要引入新的狀態管理層或 signal bus、不要新增套件。能用既有 widget 重新排列就重新排列。
3. 既有功能一個都不能少：接續對話、只載入紀錄、在此專案開新對話、重新命名／封存、+ Agent、並排檢視、自動協作、工作詳情、協作總覽、時間線、歷史、Settings、各面板的連線／停止／核准。只是搬位置，不是刪。
4. `python scripts/run_tests.py --ui` 必須全綠；`python scripts/run_tests.py`（全套）相對基準不能新增失敗。基準（2026-10-15，main）：39/43 PASS；已知不過的是 `test_codex_adapter`（缺 `evidence/codex-schema` 夾具）、`test_exe_source_hardening`（找 root `install.ps1`）、`test_dot_ui` 與 `test_session_labels`（逾時，`--timeout 900` 會過）。
5. 既有測試引用的屬性名（`window.role_tabs`、`window.layout_mode`、`window.navigator`、`window.session_tabs`、`window.agent_rail`、`window.sidebar`、`window.toggle_monitor`）**保留**；測試要跟著新結構改的（例如 `sidebar_pages` 的分頁索引），改測試並在回報裡逐一列出改了哪個斷言、為什麼。
6. 每個邏輯任務一個 commit，訊息英文。secrets 不進 repo。
7. 用 `tests/render_workbench.py` 產生截圖當視覺證據（它已經會依 `layout_mode` 切版面），輸出到 `evidence/ui-redesign/`（此目錄被 .gitignore 忽略，回報時附路徑並把 PNG 另外交給審查者）。

## 2. 現況與整合點（動手前必讀）

### 2.1 頂層版面（`acw/ui.py`）

- `2281-2286`：根 `QVBoxLayout`：頂部標題列 → `run_bar`（預設隱藏）→ `workspace_splitter` → `footer`。
- `2287-2334`：頂部標題列：☰ 側欄鈕（2287）、`console_mark`「ACW / CONTROL ROOM」（2293）、`context_title` 麵包屑「角色 · 專案 › 標題」（2297，`update_context_title` 在 2712-2723）、`layout_mode` 下拉（2303-2307，選項「自動布局／並排／專注」，資料值 `Auto`／`Three panes`／`Focus`，顯示文字目前就是「專注」那一格）、「協作總覽」鈕（2315 → `toggle_monitor` 3687）、「⋯」工作區選單（2321-2333，含「檢視」子選單 2434-2441）。
- `2313`「自動協作…」、`2318`「工作詳情」，放在第二列（2481-2482）。
- `2353-2358`：`workspace_splitter`（水平）左側 `sidebar`（最小 230、最大 310）；`2575-2577` 初始尺寸 `[260, 1230]`。
- `2458-2471`：`role_tabs`（`QTabBar`，文字來自 `ROLE_NAMES`／`ROLE_LABELS` `ui.py:39-40`）與「+ Agent」「並排檢視」同一列；`2468` `currentChanged → select_role`（2766）。
- `2484-2519`：`stack`（`QStackedWidget`）：chat_workspace／時間線／歷史／`monitor_dashboard`（index 3）。
- `2486-2489`：中央 `splitter` 承載各 `AgentPanel`（最小寬 300，`ui.py:499`）。
- `2502-2505`：`AgentRail` 加進 `chat_workspace` 的 `QHBoxLayout`（固定寬 244，`acw/monitor.py:260`），**不在** `workspace_splitter` 內。
- `2790-2819`：`update_workspace_layout`：`focused = layout_mode == 'Focus' or narrow`；`agent_rail.setVisible(focused and available >= 760 and mode == 'Workspace')`（2806）；非 focus 時 `unfocus_button` 隱藏（2813）。
- `2426-2433`：`self.mode`（Workspace／Monitor／Timeline／History）是**隱藏**的 `QComboBox`，只能從「⋯ → 檢視」切。`change_mode` 在 3667；Monitor 時「協作總覽」鈕文字變「返回工作台」（3674）。

### 2.2 左側欄（`acw/ui.py:2353-2452`）

- `2362-2369`：`sidebar_pages`（`QTabBar`：對話／Agent／紀錄）→ `sidebar_stack`。
- 「對話」頁 = `SessionNavigator`（`1968-2170`）：`SOURCES = (Claude, Codex)` 來源分頁 `nav_source`（1983-1989）、搜尋框、`QTreeWidget` 兩欄、狀態列、「接續對話」主按鈕與「⋯」選單（只載入紀錄／在此專案開新對話／重新命名／封存／顯示已封存／重新整理）。資料：`window.core.desktop_sessions(agent)`（`core.py:642`）→ `acw/desktop_sessions.py:106`（Claude）／`:131`（Codex），每筆有 `agent, session_id, cwd, title, last_activity, created, model, archived, turns`，`group_by_project`（`:171`）按 `cwd` 分組，`repo_label(cwd)`（`:70`）給組名。
- 點選只更新按鈕（`selection_changed` 2151）；雙擊／Enter 或「接續對話」→ `open_selected(True)`（2162）→ `window.open_desktop_session(record, independent=True)`（3279-3315）→ `core.open_desktop_session` 後 `focus_role(agent)` 並 `reload_context`。
- 「Agent」頁 = `session_tabs`（`QTabWidget`，tab bar 隱藏，2445-2450）：每個 agent 的 `panel.session_controls`（Project／Task／Session 下拉，定義在 `AgentPanel` 569-680）由 `2490-2494` 放入；`select_role` 會 `session_tabs.setCurrentIndex(index)`。
- 「紀錄」頁 = 全域 `project_combo`／`task_combo`／`task_status`（2380-2425，`project_changed` 3604、`task_changed` 3614）。
- `select_role`（2766-2780）：設 `_preferred_agent`、存 `ui.active_agent`、若側欄在「紀錄」頁就切回「Agent」頁、同步 `session_tabs`、更新麵包屑與工作詳情、重算版面、刷新 monitor。

### 2.3 右側 `AgentRail`（`acw/monitor.py:249-324`）

- 卡片資料來自 `collect_snapshot`（`monitor.py:19-39`，逐 agent 讀 `core.agent_task`／`core.agent_project`／adapter state／待核准數）。
- 卡片的按鈕 `open_role.emit(agent)` → `ui.py:2503` 連到 `open_monitor_role`（3699）：切到 Workspace、切側欄到「Agent」頁、`select_role`、設 Focus。
- 選取狀態：`card.setProperty('selected', agent == selected)`（`monitor.py:318-321`）。
- `refresh` 由 `refresh_monitor`（`ui.py:3708`）每秒最多一次呼叫。

### 2.4 主題（`acw/theme.py`）

- 色票常數 `17-23`；`METAL_STYLE` 37、`DESKTOP_STYLE` 124（主色 `#d97757`，156）、`HACKER_STYLE` 220（主色 `#a3e635`，249）；字型 `'Segoe UI', 'Microsoft JhengHei UI', 'Noto Sans CJK TC'`；`build_style(name)` 368。
- `ui.py:2280` 固定套 `build_style("hacker")`。`ui.py` 另有 4 處元件層級 `setStyleSheet`（278、382、472、1096），`monitor.py` 4 處（92、103、166、320）。
- 沒有統一的 spacing／radius 常數；各處 `setContentsMargins`／`setSpacing` 手寫。

### 2.5 測試（`tests/`）

- `scripts/run_tests.py --ui` 跑 `UI_MODULES`（`scripts/run_tests.py:14`）。會受影響的：`tests/test_ui_refresh.py`（`role_tabs` 288-325、504-536、929-977、1299-1307；`layout_mode` 文字與資料 288-290）、`tests/test_local_ui.py`（74-75、93、107）、`tests/test_desktop_sessions.py`（`navigator`、`sidebar_pages` 160-219）、`tests/test_collaboration_monitor.py:376`（`toggle_monitor`）、`tests/render_workbench.py:53`（`layout_mode`）。

---

## Task A：單一 agent 選取器，左側欄跟著選到的 agent

**目標**：使用者在任何地方選 agent，左側欄、中央面板、右側卡片、頂列麵包屑同時反映同一個 agent；左側欄的內容明確屬於這個 agent。

**要求**：

1. **選取器只剩一個可見**。`update_workspace_layout`（2790-2819）改成：專注模式 → `agent_rail` 顯示（維持寬度 ≥ 760 且 Workspace 的條件）、`role_tabs` 隱藏；並排模式 → `role_tabs` 顯示、`agent_rail` 隱藏。`role_tabs` 物件保留（它仍是 `select_role` 的來源之一，測試也引用它）。「+ Agent」與「並排檢視」兩個按鈕移到 `AgentRail` 底部（`+ 新增 Agent` 已在那裡，`monitor.py:275-278`；把 `unfocus_button` 也放過去，並排模式時它本來就隱藏）。
2. **左側欄改成單頁、跟著 agent**。移除 `sidebar_pages` 的三分頁與 `sidebar_stack` 的切換，改成一個 `QVBoxLayout`，由上到下：
   - **agent 標頭**：`sidebar_agent_title`（已存在，2442）加上角色（`ROLE_LABELS`）與狀態文字（沿用 `panel.state.text()`），用 `console_section` 樣式。
   - **「目前綁定」區**：就是 `session_tabs`（2445-2450），維持 `select_role` 同步 index 的做法。
   - **「可接續的對話」區**：`SessionNavigator`，但 **移除 `nav_source` 來源分頁**；改為由 `window.select_role` 呼叫新方法 `navigator.set_agent(agent)`：provider 是 `claude`／`codex` 的 agent 才載入對應來源，`dot`／`local` 顯示一行說明「此 agent 沒有本機歷史對話」並隱藏樹與按鈕。`SessionNavigator.agent` 屬性改成回傳 `set_agent` 設定的值（provider 由 `window.core.provider(agent)` 決定）。
   - **預設只列綁定的專案**：`fill()` 時若該 agent 有綁定 project（`window.core.agent_project(agent)` 的 `repo_path`），只顯示 `cwd` 正規化後等於它的分組；新增一個 `QCheckBox`「顯示全部專案」（`nav_all_projects`，預設不勾）可看全部。沒有綁定 project 時列全部並停用該勾選框。
   - 「紀錄」頁的全域 `project_combo`／`task_combo`／`task_status`（2380-2425）移進「⋯」選單的一個對話框「工作紀錄…」（`QDialog`，直接把那個 `records_page` widget 放進去），行為不變。
3. **`select_role` 是唯一入口**：`role_tabs.currentChanged`、`AgentRail.open_role`、`focus_role`、`open_desktop_session` 之後的 `focus_role`，最後都走 `select_role`；它要再多做兩件事：`navigator.set_agent(agent)`、更新左側 agent 標頭。移除 `select_role` 裡「側欄在紀錄頁就切回 Agent 頁」那段（2770），因為分頁不存在了。
4. **頂列**：`layout_mode` 下拉前面加一個小標「版面」（或把它的 accessibleName 與 tooltip 改成「版面」，選項文字維持「自動布局／並排／專注」，**資料值不變**）；「協作總覽」鈕改成兩段式切換「工作台 │ 協作總覽」（兩個 `QToolButton` 互斥，或一個 `QTabBar` 兩格），行為仍是 `toggle_monitor`／`change_mode`；`self.mode` 仍保留為資料來源（時間線／歷史仍只在「⋯ → 檢視」）。
5. 側欄最小寬 230、最大 310 維持；`workspace_splitter` 初始尺寸不變。

**驗收條件（全部要過，附執行輸出原文）**：

- `python scripts/run_tests.py --ui` 全部 PASS（貼完整的 RUN／PASS 清單）。
- 新增測試（放 `tests/test_ui_refresh.py` 或新檔 `tests/test_ui_agent_centric.py`，並加進 `scripts/run_tests.py` 的 `UI_MODULES`）：
  1. 專注模式：`agent_rail.isVisible()` 為真且 `role_tabs.isVisible()` 為假；並排模式反之。
  2. 按右側卡片（`agent_rail.open_role.emit('codex')`）後：`window._preferred_agent == 'codex'`、`window.navigator.agent == 'codex'`、`window.session_tabs.currentIndex() == agents.index('codex')`、`context_title` 文字以 `Codex` 開頭。
  3. 選到 provider 為 `local` 的 agent 時，`navigator` 顯示「沒有本機歷史對話」的說明且樹隱藏；切回 `claude` 時樹恢復。
  4. 給 navigator 塞兩個 project 的假 session（照 `tests/test_desktop_sessions.py:182` 的做法），agent 綁定其中一個 project 時只顯示該組；勾 `nav_all_projects` 後顯示兩組。
  5. 「工作紀錄…」對話框打開時含 `project_combo` 與 `task_combo`，改 `project_combo` 仍觸發 `project_changed`。
- `tests/test_desktop_sessions.py` 中引用 `sidebar_pages` 的斷言改成新結構（列出改了哪幾行）。
- `python tests/render_workbench.py`（看它的用法）對 `Focus` 與 `Three panes` 各出一張截圖到 `evidence/ui-redesign/task-a-focus.png`、`task-a-panes.png`。
- 全套 `python scripts/run_tests.py` 相對基準無新增失敗。

**回報格式**：改/增哪些檔（路徑:行號範圍）、驗收逐條 PASS/FAIL 附**執行輸出原文節錄**、改掉的既有斷言清單、未盡事項。過不了的驗收明講卡在哪，不要標「大致完成」。

---

## Task B：視覺整理（在 Task A 之後，獨立 commit）

**目標**：同一個版面，看起來有層級、安靜、一致。不改任何行為。

**要求**：

1. `acw/theme.py` 新增常數：`SPACE = {'xs': 4, 'sm': 8, 'md': 12, 'lg': 16, 'xl': 24}`、`RADIUS = 6`，並把 `ui.py`／`monitor.py` 裡版面層級的 `setContentsMargins`／`setSpacing` 改用這些常數（只改值來源，不改版面結構）。
2. 預設主題改為 `desktop`：`ui.py:2280` 讀設定 `ui.theme`（預設 `'desktop'`），`build_style(theme)`；Settings 對話框加一個「主題」下拉（desktop／hacker／metal），改了立刻重套樣式並存設定。hacker 仍可選，但不再是預設。
3. 在 `DESKTOP_STYLE` 內：
   - 強調色 `#d97757` 只用在：選取中的 agent 卡片左框、主要按鈕（`primary`、「連線」）、目前分頁底線。其他框線一律中性灰（`#3a3a3a` 深色底或 `#d9d4cc` 淺色底，依該主題現有底色決定）。
   - 文字三級：標題（面板名、agent 名）、內文、輔助（時間、狀態、說明），輔助用 `MUTED_COLOR`；不再有第四種字色。
   - 卡片與面板：1px 中性邊框、`RADIUS` 圓角、無陰影與發光；選取中的卡片用左側 3px 強調色條，而不是整圈框。
   - `console_mark`「ACW / CONTROL ROOM」與 `workspace_hint`「MONITOR / 專注對話」改成輔助色小字，不再是螢光標題。
4. `monitor.py` 裡 `MonitorDashboard` 的 inline 樣式（`monitor.py:166`）同步成 desktop 的色票，但**只在 theme 為 desktop 時**；hacker 維持原樣（可用 `theme.current_name()` 之類的小函式判斷，或讓 `build_style` 回傳的樣式覆蓋它）。
5. 更新 `docs/UI-REFRESH.md`（預設主題、側欄結構、選取器規則）與 `docs/USER_GUIDE.md` §Project、Session 與獨立 Agent、§Monitor 與工作紀錄，對齊新版面。

**驗收條件（全部要過，附執行輸出原文）**：

- `python scripts/run_tests.py --ui` 全部 PASS。
- 新增測試：`ui.theme` 未設時 `MainWindow` 套的是 desktop 樣式（檢查 `window.styleSheet()` 含 `#d97757` 且不含 `#a3e635`）；設定 `ui.theme='hacker'` 後重建視窗含 `#a3e635`。
- `evidence/ui-redesign/task-b-focus.png`、`task-b-panes.png`、`task-b-monitor.png`（協作總覽）三張截圖。
- `git diff main --stat` 只列第 1 節允許的檔案。

**回報格式**：同 Task A。

---

## 3. 交付總回報格式

每個任務一節：改/增哪些檔、驗收逐條 PASS/FAIL 附**執行輸出原文**、改掉的既有斷言與原因、未盡事項與風險。最後附 `python scripts/run_tests.py --ui` 完整輸出、全套 `python scripts/run_tests.py` 的 PASS/FAIL 清單（與基準比較）、`git log --oneline main..HEAD`、截圖路徑清單。過不了的明講卡在哪。

## 4. 不做（避免範圍擴張）

- 不改 project／session 的資料模型，不做方案 B 的「專案為中心」三欄。
- 不重寫 `AgentPanel`、不動對話串的卡片呈現、不動輸入列。
- 不動 `acw/core.py`、`acw/adapters/*`、`acw/requests.py`、`acw/orchestrator.py`、`acw/store.py`、`AI-Collab-Monitor/`。
- 不新增依賴、不加 signal bus 或狀態管理層。
- 不要 push main。

## 5. 審查者後續（非 Codex 範圍）

Claude 會在 worktree 上重跑測試、看截圖、比對 `git diff main --stat` 是否超出第 1 節範圍，然後決定合併或寫 `docs/HANDOFF-REWORK-01.md`。合併後 Ryan 重開 GUI 即生效。
