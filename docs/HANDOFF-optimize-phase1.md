# 交付規格書 — ACW 優化第一期（低風險：效能、穩定、整理）

> 對象：Codex。**本文件自足。** Repo：`C:\Users\ryant\Desktop\AI-Collab-Workspace`。
> 分支：從 `ui/desktop-workspace-100pct-20261006` 切出 **`perf/optimize-phase1`**，**直接在這個 checkout 工作，不開 worktree、不建 junction**。
> 基準：`python scripts/run_tests.py` 目前 53 個模組全 PASS（報告寫在 `evidence/test-runs/<ts>/result.json`）。完成後必須仍全 PASS。
> 原則：**不改使用者看得到的行為**（除非下文明說）。一個 Task 一個 commit，英文祈使句訊息。不 push、不開 PR（Claude 審查後處理）。

---

## Task 1：Work Details 樹改成合併刷新

- 現況：`acw/ui.py` 約 3438 行，事件批次處理中 `if self.details_toggle.isChecked(): self.refresh_work_details()`；`refresh_work_details`（約 3102-3140）每次重查 500 筆事件與 handoffs，並清空重建 6 個 `QTreeWidget`。串流時每秒最多 10 次。
- 改法：加 `self._details_dirty` 旗標與一個 single-shot `QTimer`（500 ms）。事件批次只「標記 dirty 並啟動 timer（若未啟動）」；timer 觸發時才真正刷新。批次內若**全部**是 `message_delta` 事件就不標記。打開 Details toggle 時仍立即刷新一次。
- 驗收：新增測試 — 連續餵 20 批事件，`refresh_work_details` 只被呼叫 ≤2 次（用 patch 計數，處理 Qt 事件迴圈讓 timer 觸發）；只有 `message_delta` 的批次不觸發。

## Task 2：`history_stamp` 快取「找不到」

- 現況：`acw/desktop_sessions.py:314-331`，GUI 每 3 秒（`acw/ui.py` `sync_local_conversations`，約 3469-3487）對每個 agent 呼叫；找不到檔時每次都對所有 Codex root 做 `sessions/*/*/*/rollout-*<id>.jsonl` 的 glob。
- 改法：加模組層 `_HISTORY_MISSES: dict[key, float]`（`time.monotonic()`）；30 秒內同一 key 已 miss 就直接回 `None`，不 glob。找到後清掉 miss。提供 `_HISTORY_MISSES.clear()` 可供測試重設（或沿用既有的快取清除點）。
- 驗收：新增測試 — patch `Path.glob` 計數，同一個不存在的 id 在 30 秒內呼叫 5 次只 glob 1 輪；把 monotonic patch 前進 31 秒後會再 glob。

## Task 3：Codex reader 執行緒綁定自己的 process

- 現況：`acw/adapters/codex.py` `_read_loop`（約 110-133）與 `_read_stderr`（約 135-149）讀 `self._process`，`finally` 無條件設 `Disconnected` 並讓 pending 請求失敗。`disconnect()` 只 `join(timeout=2)`，舊 reader 可能在重連後才結束，把新連線打成 Disconnected。
- 改法：照 `acw/adapters/claude.py:259-285` 的做法 — 啟動執行緒時把 `process` 當參數傳入，迴圈讀 `process.stdout`／`process.stderr`；`finally` 內**只有** `process is self._process` 時才清 `_session_ready`、設 `_turn_done`、清 pending、改狀態。
- 驗收：新增測試 — 建 adapter，用假 process A 啟動 reader，換成 process B（模擬重連）後讓 A 的 stdout 結束；斷言狀態未變 Disconnected、B 的 pending 未被清。既有 `tests/test_codex_adapter.py`、`test_codex.py`、`test_adapter_cancel_ownership.py`、`test_recovery_process.py` 全過。

## Task 4：共用 adapter 子行程 helper

- 現況：`getattr(subprocess, 'CREATE_NO_WINDOW', 0)` 加 `**({'env': env} if env else {})` 的寫法約重複 12 次（`acw/adapters/claude.py`、`codex.py`、`hermes.py`、`dot.py`、`acw/requests.py`、`acw/inspection.py`；用 grep `CREATE_NO_WINDOW` 找全）。`_CancellationOwnershipChanged` 在 `claude.py` 與 `codex.py` 各定義一次。
- 改法：新增 `acw/adapters/_proc.py`：`hidden_flags()`、`popen_hidden(argv, env=None, **kw)`、`run_hidden(argv, env=None, **kw)`、`class CancellationOwnershipChanged(Exception)`。逐一機械替換呼叫點；兩個 adapter 從 `_proc` import 例外（保留原名別名 `_CancellationOwnershipChanged = CancellationOwnershipChanged`，讓既有測試不需改）。**不動** stderr 處理邏輯與 redaction（各家不同，留到之後）。
- 驗收：`grep -rn CREATE_NO_WINDOW acw` 只剩 `_proc.py`；`tests/test_exe_source_hardening.py`、`test_adapter_stream_safety.py`、`test_claude.py`、`test_codex*.py`、`test_hermes_adapter.py`、`test_dot.py` 全過。若 `test_exe_source_hardening.py` 有掃描原始碼的規則與新檔衝突，回報並說明，不要放寬該測試。

## Task 5：Monitor 每秒快取 playbooks

- 現況：`acw/monitor.py` `collect_snapshot`（約 21-43）在 Workspace／Monitor 模式每秒於 GUI 執行緒跑，每個 agent 呼叫一次 `playbooks.load`（讀設定＋驗證）。
- 改法：在 `acw/playbooks.py` 加以「設定內容／檔案 mtime」為鍵的快取（或在 monitor 端以設定值字串為鍵快取），設定改變時自動失效；PlaybookDialog 存檔後必須立即生效。
- 驗收：新增測試 — 連續 `collect_snapshot` 10 次，底層讀取只發生 1 次；改設定後下一次快照拿到新值。`tests/test_playbooks.py`、`test_collaboration_monitor.py` 全過。

## Task 6：封存過期文件與一次性腳本

- `git mv` 到 `scripts/archive/`（先 grep 確認除了自己與 `evidence/`、`vendor/` 之外**沒有任何引用**；有引用就不搬並回報）：
  `capture_public_docs_evidence.py`、`close_test_dialog.py`、`inventory_existing_capabilities.py`、`probe_repl.py`、`run_exe_change_review_ui.py`、`run_exe_claude_review_ui.py`、`run_live_claude_tools_ui.py`、`run_live_codex_ui.py`、`run_live_collaboration_ui.py`、`verify_live_diff_ui.py`、`verify_mcp_saved_raw_ui.py`、`verify_multi_monitor_ui.py`、`verify_native_history_idle_ui.py`。
- `git mv` 到 `docs/archive/`：所有 `docs/HANDOFF-*.md`（**本文件除外**）、`BACKEND-RELIABILITY-2026-10-07.md`、`CONTINUATION-NOTES.md`、`CANDIDATE-PACKAGE-README.md`。
- **不要搬**：`scripts/dispatch_request.py`、`dot_cli_entry.py`、`Launcher.cs`、`launcher.manifest`、`run_tests.py`、`run_ui_tests.py`，以及 `scripts/installer_policy.py` 引用的任何檔（`docs/USER_GUIDE.md`、`TROUBLESHOOTING.md`、`SECURITY.md`）。
- 修正 `README.md`、`docs/README.md`、`docs/HERMES.md`、repo 內所有指向被搬檔案的連結（grep 檔名）。`docs/archive/README.md` 一句話說明這裡是歷史交付紀錄。
- 驗收：`tests/test_exe_source_hardening.py`、`test_maintenance.py` 全過；grep 不到斷掉的相對連結。

---

## 回報格式

每個 Task 一節：改了哪些檔（路徑:行號）、新增測試名稱、驗收 PASS/FAIL 附輸出原文。最後附 `python scripts/run_tests.py` 的結尾輸出與 `result.json` 的 `status`、`git log --oneline ui/desktop-workspace-100pct-20261006..HEAD`。過不了的明講卡在哪。

## 不做

- 不拆 `acw/ui.py`、不限制對話卡片數量（第二期）。
- 不改 redaction、不改 UI 外觀、不動 `vendor/`、`evidence/`、`AI-Collab-Monitor/`。
- 不 push、不開 PR、不改 `~/.claude` 底下任何東西。
