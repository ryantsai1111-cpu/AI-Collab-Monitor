# 交付規格書 — 關閉前確認進行中的 Hermes run，與三項衛生修正

> 對象：Codex。**本文件自足。** 技術棧：Python 3.12 + PySide6 桌面協作站，`python run.py` 啟動，離線測試 `python scripts/run_tests.py`（UI 集合加 `--ui`）。
> 本任務在新 branch `codex/close-guard-hygiene`（從 `ui/desktop-workspace-100pct-20261006` 切，它等於 `main` 加這份規格）進行，用 `git worktree add ../AI-Collab-Workspace-close-guard codex/close-guard-hygiene` 在另一個目錄工作。**不得 push main**；完成後開 PR 到 `main`，合併由審查者決定。
> **worktree 裡不得用 junction／symlink 把主 checkout 的 `vendor/`、`node_modules/` 等被忽略的目錄連進來**；需要 PySide6 就 `python -m pip install --target vendor "PySide6==6.11.2"`。

---

## 0. 背景與決策

2026-10-15 起，hermes-delegation skill 的 `run.sh` 在 GUI 開著時把一步 Hermes 工作寫成 `data_dir/requests/<label>.json`，由 `acw/requests.py` 的 `RequestDispatcher` 用協作站自己的 `HermesAdapter` 執行（設計：`docs/DESIGN-hermes-single-entry.md` §3.2，操作：`docs/HERMES.md`「請求檔派工」）。`RequestDispatcher.close()` 在 `core.close()` 時會停掉進行中的 run 並寫 `interrupted` 結果檔。

2026-10-15 20:26 使用者為了載入新版面關掉 GUI，當時 `me3-run1` 正在跑，被中止後留下 5 個未提交檔。`MainWindow.closeEvent` 其實有跳確認框，但訊息是通用英文「Backend work is active…」，沒說會中止哪一個 skill 派來的步驟、會留下什麼。

決策：
1. 關閉確認要**點名**進行中的請求（label、worktree）並用中文說明後果；右側 AgentRail 與協作總覽的 Hermes 卡片要看得出「執行中 · <label>」。
2. 資料庫 WAL 要有週期性 checkpoint，不能只靠關閉時那一次。
3. 兩個因環境而永遠失敗的測試改成有理由的 skip，讓套件回到可信的全綠。

## 1. 不變量

1. 只動 `acw/ui.py`、`acw/monitor.py`、`acw/requests.py`、`acw/store.py`、`acw/core.py`（只加 checkpoint 排程那幾行）、`tests/*.py`、`scripts/run_tests.py`（只為了 skip 的呈現）、`docs/HERMES.md`。其他檔案不碰。
2. 不過度工程：不加新的狀態層、不重構 closeEvent 以外的關閉流程、不改 adapter。
3. `python scripts/run_tests.py --ui` 全綠；全套 `python scripts/run_tests.py` 最終 **0 FAIL**。
4. 不要啟動 `run.py`（使用者的 GUI 正從主 checkout 執行）。
5. 每個 Task 一個 commit，訊息英文。

## 2. 現況與整合點

- `acw/ui.py:4491-4512`：`closeEvent`。`self.workers` 或任一 `panel.connection_state == "Busy"` 時跳 `QMessageBox.question(self, "Active backend work", "Backend work is active. …")`，Yes 才設 `_close_pending = True`、停 orchestrator、等 adapter 取消後再關。dispatcher 的 run 會讓 Hermes 面板變 Busy，所以目前的確會問，只是訊息不具體。
- `acw/requests.py`：`RequestDispatcher._run` 是進行中的 run（dict，含 `label`、`task_id`、`started`、`adapter`，`:432` 設定、`:466` 清除）；`poll()` `:254`；`_heartbeat(busy)` `:269-285` 寫 `requests/.dispatcher.json`；`close()` `:545` 會 `_stop` 再寫 `interrupted`。請求檔裡有 `worktree` 欄位，但 `run` dict 目前沒存，要加。
- `acw/monitor.py:20-39`：`collect_snapshot(core, panels, run=None)` 逐 agent 組 `roles`（`state`、`approvals`、`project`、`task`、`session`…）；`AgentRail.refresh` `:284-324` 與 `RoleCard.update_data` 用 `row['state']` 決定顏色與文字（`STATES` 對照表在 `:12`）。
- `acw/store.py:48-52`：開庫時 `PRAGMA journal_mode=WAL`；`close()` `:393-400` 已做 `PRAGMA wal_checkpoint(TRUNCATE)`，但例外被 `finally` 吞掉，而且只在關閉時做一次。2026-10-16 觀察：主檔 `workspace.sqlite3` mtime 仍是 10-06，WAL 1.5 MB。
- `acw/core.py:1546` `poll_requests()`，`:1623` `close()`；UI 每 100 ms 的 `poll_events`（`acw/ui.py:3201` 附近）每 10 tick 用 `self.run(self.core.poll_requests, …)` 丟背景執行緒，可以在同一處加 checkpoint 排程。
- `tests/test_codex_adapter.py:20` `SCHEMA_ROOT = …/evidence/codex-schema/v2`（`evidence/` 被 .gitignore），`:108` `setUpClass` 讀夾具時 `FileNotFoundError`。
- `tests/test_exe_source_hardening.py:115-125`：`test_powershell_parser_and_exact_csharp_regex_with_windows_argv_oracle` 的 `files` 清單含根目錄 `install.ps1`，該檔已不存在。
- `scripts/run_tests.py:82-95`：每個模組以子程序 exit code 判 PASS／FAIL，沒有 skip 概念；整個模組被 `SkipTest` 時 unittest 仍回 0，所以會算 PASS。

---

## Task A：關閉前點名進行中的請求，卡片顯示執行中

**要求**：
1. `RequestDispatcher` 加 public 方法 `active()`：有 run 時回傳 `{'label', 'worktree', 'task_id', 'started'}`，否則 `None`。`_launch` 把請求的 `worktree` 存進 `run` dict。
2. `closeEvent`：先查 `self.core.requests.active()`。有的話訊息改為中文並點名：
   「Hermes 仍在執行 skill 派來的步驟 <label>（<worktree>）。關閉會中止它，工作目錄可能留下未提交的修改。仍要關閉？」按鈕 Yes／No，預設 No。沒有 dispatcher run 但有其他 Busy 時，沿用原本的確認但把文字改成中文：「仍有 Agent 在執行。關閉會要求取消，歷史會保留，重啟不會自動重送。仍要關閉？」
3. `collect_snapshot` 的每個 role 多帶 `request_label`（只有 `local` provider 且 `core.requests.active()` 存在時有值），`AgentRail.refresh` 與 `RoleCard.update_data` 在有值時狀態文字顯示「執行中 · <label>」並用 `running` 色。
4. `docs/HERMES.md`「請求檔派工」一節補一段：關閉 GUI 會中止進行中的請求並回 `interrupted`，關閉前會點名確認。

**驗收（附執行輸出原文）**：
- `tests/test_hermes_requests.py` 新增：`active()` 在 launch 後回傳含 `label`／`worktree` 的 dict，結束後為 `None`。
- `tests/test_ui_refresh.py`（或新檔，加進 `UI_MODULES`）新增：用 `unittest.mock.patch('acw.ui.QMessageBox.question')` 模擬 (a) dispatcher 有 run、回 No → `closeEvent` 的 event 被 ignore、`_close_pending` 仍 False、訊息含 label 與 worktree；(b) 回 Yes → `_close_pending` 變 True。另一個測試：snapshot 有 `request_label` 時 rail 卡片文字含「執行中 · <label>」。
- `python scripts/run_tests.py --ui` 全綠。

## Task B：週期性 WAL checkpoint

**要求**：
1. `acw/store.py` 加 `checkpoint(mode='PASSIVE')`：執行 `PRAGMA wal_checkpoint(<mode>)`，回傳 `(busy, log, checkpointed)` 三元組；`close()` 改呼叫 `checkpoint('TRUNCATE')`，失敗時用 `logging.getLogger('acw.store').warning(...)` 記下，不再無聲吞掉。
2. `acw/core.py` 加 `maybe_checkpoint()`：所有 adapter 的 `state` 都不是 `Busy`、且距上次成功 checkpoint 超過 300 秒時呼叫 `store.checkpoint('PASSIVE')`；`poll_requests()` 結尾順手呼叫它（這樣不用再加 timer）。
3. 不改 journal mode，不改其他 store 行為。

**驗收**：
- `tests/test_core.py` 新增：寫入一批 messages 後 `maybe_checkpoint()`（用可注入的 clock 讓它認為已超過 300 秒），`-wal` 檔大小下降或主檔 mtime 更新；有 adapter Busy 時不 checkpoint。
- `python scripts/run_tests.py test_core test_hermes_requests` 全綠。

## Task C：環境相關測試改成 skip

**要求**：
1. `tests/test_codex_adapter.py` 的 `setUpClass`：`SCHEMA_ROOT` 不存在時 `raise unittest.SkipTest('需要 evidence/codex-schema/v2 夾具（被 .gitignore，請向 Ryan 取得）')`。
2. `tests/test_exe_source_hardening.py` 那個測試：`files` 清單過濾掉不存在的檔案；若 `install.ps1` 不存在就 `self.skipTest('根目錄 install.ps1 已移除，PowerShell 解析 oracle 只對現存檔案執行')`，或只對現存檔案跑並在輸出說明。兩種擇一，不要刪測試。
3. `scripts/run_tests.py`：若容易做，從子程序輸出抓 `skipped=N` 或 `OK (skipped=…)` 字樣，在報告的 row 加 `'skipped': True`，列表印成 `PASS (skipped) <module>`；不容易就不做，回報說明。

**驗收**：
- 全套 `python scripts/run_tests.py` 0 FAIL，貼完整 PASS／FAIL 清單。
- 單獨跑 `python -m unittest tests.test_codex_adapter` 顯示 skipped。

---

## 3. 交付總回報格式

每個 Task 一節：改/增哪些檔（路徑:行號）、驗收逐條 PASS/FAIL 附執行輸出原文、未盡事項。最後附 `--ui` 與全套的輸出、`git log --oneline main..HEAD`、PR 連結。過不了的明講卡在哪，不要寫「大致完成」。

## 4. 不做

- 不改 `RequestDispatcher` 的派工邏輯、不改 adapter、不改 run.sh。
- 不把 Hermes 子程序改成可在 GUI 關閉後存活。
- 不要 push main。
