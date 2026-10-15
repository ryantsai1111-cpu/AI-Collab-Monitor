# 交付規格書 — 工作台版面打磨 01（承接 HANDOFF-ui-agent-centric）

> 對象：Codex。**本文件自足。** 先讀 `docs/HANDOFF-ui-agent-centric.md` 了解已完成的版面（方案 A），該規格的 §1 不變量與 §4 不做清單全部沿用。
> 前一份規格的成果已由審查者核准並合併進 `main`（2026-10-15）。本任務在新 branch `codex/ui-polish-01`（從 `main` 切）進行，用 `git worktree` 在另一個目錄工作，**不得 push main**。

## 0. 背景

審查者對 `codex/ui-agent-centric` 的獨立驗收：規格全數達成，另列出下列打磨項。這份規格只處理它們，不做新功能。

## Task A：效能與測試衛生

1. **`SessionNavigator.fill()` 的路徑正規化只算一次**（`acw/ui.py` 約 2125 行）：`normalize(directory)` 目前在每一列重算；改成在迴圈外算一次，並把 `normalize` 提成模組層級函式 `_same_dir(a, b)` 供測試使用。加一個測試：`cwd` 為大小寫不同、`/` 與 `\` 混用、結尾多一個斜線的三種寫法，都會被視為同一個專案。
2. **補 stub**：`tests/test_approvals.py`、`tests/test_dot_conversation.py` 建立 `MainWindow` 的 fixture 沒有 `core.desktop_sessions = lambda agent: []`，測試會真的掃使用者本機的 Claude／Codex 對話目錄。比照其他 UI 測試補上。
3. **清掉死碼**：`acw/theme.py` 三個主題裡的 `QTabBar#sidebar_pages`／`#nav_source` 選擇器；`acw/ui.py:1969` 附近 `SessionNavigator` 的 docstring 改成描述新的載入時機（側欄顯示或 `set_agent` 時背景載入）；`ui.sidebar_page` 設定若還有讀寫處一併移除。

**驗收**：`python scripts/run_tests.py --ui` 全綠；新測試存在且通過；`grep -rn "sidebar_pages\|nav_source\|ui.sidebar_page" acw tests` 無結果。

## Task B：視覺微調（只改 `DESKTOP_STYLE` 與對應的 inline 樣式）

1. `primary` 按鈕文字改回 `#ffffff`，hover 用稍深的 `#c4663f`，按下 `#b05a37`；`:focus` 邊框用強調色 `#d97757`（鍵盤焦點要看得到）。
2. 狀態文字恢復語意色，但只在這兩種情況：`待核准` 用 `#e3b341`，`Error`／`Interrupted`／`Blocked` 用 `#f27d6b`；其餘狀態維持 MUTED。`AgentPanel.state`（`ui.py` 約 1098）、`AgentRail` 卡片與 `RoleCard`（`monitor.py` 約 341）三處一致。
3. 側欄 agent 標頭的名稱那一行改用標題層級（15px、`#ececea`），角色與狀態維持輔助色；不要再共用 `console_section`。
4. `#5a5953` 兩處（checkbox 外框、`QPushButton:hover` 邊框）統一成 `#3a3a3a` 或 `#4a4944`，擇一並全檔一致。
5. `SPACE` 算式：把 `(SPACE['sm'] + SPACE['md']) // 2` 這類湊 10 的寫法改成直接用 scale 上的值（`sm`=8 或 `md`=12，依視覺就近取），不要再出現除法。
6. `workspace_views`：在時間線／歷史模式下兩格都不選取（`QTabBar.setCurrentIndex(-1)` 不可用時，用一個第三格隱藏的作法或改成兩個 `QToolButton` checkable 互斥）。

**驗收**：`--ui` 全綠；`tests/render_workbench.py --stage b --output evidence/ui-polish/` 出 focus／panes／monitor 三張截圖；`grep -c "// 2" acw/ui.py acw/monitor.py` 對 `SPACE` 的算式為 0。

## 回報格式

同前一份規格 §3：改了哪些檔（路徑:行號）、驗收逐條 PASS/FAIL 附執行輸出原文、截圖路徑、`git log --oneline main..HEAD`。
