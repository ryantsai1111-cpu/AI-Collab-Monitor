# 交付規格書 — ACW 優化第二期（對話卡片上限、拆 `acw/ui.py`）

> 對象：實作代理（Sonnet）。**本文件自足。** Repo：`C:\Users\ryant\Desktop\AI-Collab-Workspace`。
> 分支：從 `ui/desktop-workspace-100pct-20261006`（目前 `efb4d8d`，已含第一期）切出 **`perf/optimize-phase2`**，直接在這個 checkout 工作，**不開 worktree、不建 junction／symlink**。
> 基準：`python scripts/run_tests.py` 46 個模組全 PASS（這個 runner 會把 `vendor/` 放進 PYTHONPATH；直接跑 pytest 會找不到 PySide6）。每個 commit 之後都要仍全 PASS。
> 原則：Task A 是唯一允許的使用者可見變化；Task B 是**純搬移**，不改任何邏輯。英文祈使句 commit 訊息，結尾加 `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`。不 push、不開 PR。

---

## Task A：對話卡片與 Timeline 設上限（一個 commit）

### 現況
- `AgentPanel`（`acw/ui.py` 約 612-1684）：`add_message`（約 1613）與 `add_event`（約 1626）把 `MessageCard`／`EventCard`／`ActivityGroup` 插進 `self.transcript_layout`，永不修剪；只有 `clear_conversation`（約 1597）會清。
- `MainWindow` 重建對話時（約 3287-3307）把 `core.messages(agent)` **全部**訊息加最近 400 筆事件排序後逐一加入，長對話會產生上千個 widget。
- `add_timeline_event`（約 4130）在 Timeline 模式無限 append。
- Dot（G8毛）面板已有自己的 `dot_visible_limit`（200）與「載入更早訊息」，**不要動 Dot 的行為**。

### 要求
1. `AgentPanel` 加 `self.visible_limit = 300`（非 Dot 面板適用；Dot 面板維持原狀）。
2. **重建時**：`MainWindow` 排序好 `history` 後，非 Dot 面板只渲染**最後 `panel.visible_limit` 筆**；若有被略過的，呼叫 `panel.set_hidden_count(n)`。
3. **即時新增時**：非 Dot 面板在 `add_message`／`add_event` 插入後，若 transcript 頂層 widget 數（不含 `self.empty` 與最後的 stretch）超過 `visible_limit`，從最舊的開始移除，直到不超過；**跳過**仍待核准的卡片（`request_id in self.pending_approval_events`）與含有待核准卡片的 `ActivityGroup`。移除時同步從 `self.cards`、`self.approvals` 刪掉對應項目，widget `hide()` + `deleteLater()`（照 `clear_conversation` 的寫法）。每移除一個就把隱藏計數加一。
4. 隱藏計數 > 0 時，transcript 最上方顯示一列（`QPushButton`，objectName `older_messages`）：「已收合較早的 N 則 · 顯示更多」。按下：`visible_limit += 300`，並請 `MainWindow` 只重建這個面板（若現有重建邏輯只能整批重建，抽出一個 `rebuild_panel(agent)` 給兩處共用，不要複製程式碼）。`clear_conversation` 會把計數歸零並隱藏這列。
5. Timeline：`add_timeline_event` 後若 `topLevelItemCount() > 2000`，移除最舊的項目直到 2000。
6. 捲動行為不變：即時新增仍 `scroll_bottom()`；按「顯示更多」後維持使用者原本看的位置（可用既有的 `capture_view_state`／`restore_view_state`）。

### 驗收（新增測試，放 `tests/test_ui_refresh.py` 或新檔 `tests/test_transcript_limit.py`，並加進 `scripts/run_tests.py` 的 `UI_MODULES` 若是新檔）
- 對一個非 Dot 面板連續 `add_message` 350 則 → 頂層卡片數 = 300、`older_messages` 可見且文字含 50。
- 第 1 則是待核准事件、接著 350 則訊息 → 那張待核准卡片仍在。
- 歷史有 500 則時重建 → 只渲染 300 則、按鈕顯示 200；按一次「顯示更多」→ 渲染 500 則、按鈕隱藏。
- Dot 面板加 350 則 → 不受影響（沿用原本行為）。
- Timeline 加 2100 筆 → `topLevelItemCount() == 2000`，且留下的是最新的。

## Task B：把 `acw/ui.py` 拆成 `acw/ui/` 套件（純搬移，一個模組一個 commit）

### 目標結構
| 新模組 | 內容（以 Task A 完成後的檔案為準，行號會移動，用類別名稱找） |
|---|---|
| `acw/ui/widgets.py` | 模組層 helpers（`label`、`button`、`identifier` 等）、`Worker`、`FocusLabel`、`PromptEdit`、`chat_markdown`、`MessageBody`、`MessageCard`、`EventCard`、`ActivityGroup` 與它們用到的常數 |
| `acw/ui/dialogs.py` | `PlaybookDialog`、`DetailDialog`、`ScreenshotReviewDialog`、`native_transcript`、Session／Native 相關 dialog、`HandoffDialog` |
| `acw/ui/artifacts.py` | `ArtifactPanel` |
| `acw/ui/navigator.py` | `SessionNavigator` |
| `acw/ui/agent_panel.py` | `AgentPanel` |
| `acw/ui/main_window.py` | `MainWindow` 與只有它用的函式 |
| `acw/ui/__init__.py` | re-export：所有原本 `acw.ui` 的公開與被外部 import 的名稱，以及測試會 patch 屬性的 Qt 類別（`QMessageBox`、`QFileDialog`、`QDialog`、`QDesktopServices`、`QInputDialog`）與 `approvals` 模組 |

### 規則
1. 順序：先 `git mv acw/ui.py acw/ui/main_window.py` 並建 `__init__.py`（`from .main_window import *` 加明確名單），確認全 PASS 後 commit；之後每搬出一個模組一個 commit（widgets → dialogs → artifacts → navigator → agent_panel），每步都全 PASS。這樣 `git log --follow` 保留 `MainWindow` 的歷史。
2. 模組之間只准單向依賴：`widgets` ← `dialogs`／`artifacts`／`navigator` ← `agent_panel` ← `main_window`。不准循環 import；遇到循環就把共用的小函式往 `widgets.py` 放。
3. **不改任何邏輯、命名或字串**。只允許：import 調整、把 module-level 常數放到使用它的最低層模組。
4. 測試裡 `patch('acw.ui.<名稱>')` 替換**模組全域名稱**的（目前有 `acw.ui.MainWindow`、`acw.ui._normalize_dir`、`acw.ui.NativeHistoryDialog`、`acw.ui.NativeSessionDialog`、`acw.ui.SessionDetailsDialog`、`acw.ui.HandoffDialog`、`acw.ui.approvals.decide`；用 `grep -rn "acw\.ui\." tests` 找全），改成指向**實際查找該名稱的模組**（例如 `acw.ui.main_window.NativeHistoryDialog`）。只改 patch 目標字串，不改斷言。patch Qt 類別屬性（`acw.ui.QMessageBox.exec` 這類）的不用改。
5. `scripts/installer_policy.py:85` 與 `tests/test_exe_source_hardening.py:13` 的必要檔清單把 `acw/ui.py` 換成 `acw/ui/__init__.py` 與新增的六個模組（`tests/test_maintenance.py` 裡寫的 `acw/ui.py` 是假資料，不用動）。也 grep `scripts/package_source.py`、`scripts/sync_installed_source.ps1`、`tools/` 是否有寫死 `acw/ui.py`，有就同步改。
6. `run.py` 與其他 `from acw.ui import ...`／`from .ui import ...` 呼叫端必須不用改就能用（靠 `__init__.py` re-export）。

### 驗收
- `acw/ui.py` 不存在；`acw/ui/` 有上表 7 個檔；最大的 `main_window.py` 應明顯小於原本 4700 行（回報各檔行數）。
- `python -c "import sys; sys.path[:0]=['vendor']; import acw.ui, acw.ui.main_window"` 成功。
- 每個 commit 後 `python scripts/run_tests.py` 全 PASS（回報最後一次的 tail 與 `result.json` status；中間各次至少回報 PASS 數）。
- `git log --follow --oneline acw/ui/main_window.py | head -3` 能追到搬移前的 commit。

---

## 回報格式

Task A：改了哪些檔（路徑:行號）、新增測試名稱、PASS/FAIL 附輸出原文、和本規格不同之處與原因。
Task B：每個 commit 搬了哪些類別、各檔行數、改了哪些 patch 目標。
最後附 `python scripts/run_tests.py` 結尾輸出、`result.json` status、`git log --oneline ui/desktop-workspace-100pct-20261006..HEAD`。過不了的明講卡在哪；若既有測試和規格衝突，停下該項並回報，不要改測試斷言。

## 不做

- 不改 Dot 面板的分頁行為、不改外觀與樣式、不改 `core.py`（拆 core 是之後的事）。
- 不動 `vendor/`、`evidence/`（除了 runner 寫的報告）、`AI-Collab-Monitor/`、`~/.claude`。
- 不 push、不開 PR。
