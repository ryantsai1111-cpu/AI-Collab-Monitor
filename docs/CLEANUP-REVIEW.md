# 資料夾清理紀錄

完成日期：2026-10-09。使用者授權自行判斷，以不影響運作為前提。**下列項目已移出原使用目錄，保留可復原備份，未永久刪除。**

批次永久刪除被工具自動核准檢查拒絕，只回覆 `blocked by policy`。實際採用同磁碟內的可復原搬移；先核對全部 26 個目標、134 個檔案的 SHA-256、完整絕對路徑與目錄內容，拒絕任何 reparse point、保護目錄或新變動。

備份位置：`evidence/cleanup/removed-20261009T0915409010Z/`，保持原相對路徑。共移出約 4.80 MiB；因保留備份，沒有釋放這些磁碟空間。啟動入口、原始碼、捷徑、本機設定與 helper 等 28 個檔案的搬移前後 hash 相同。結果見 [本機操作紀錄](../evidence/cleanup/result-20261009.json)。

## 已更新

- 目前啟動、獨立 Agent、協作與 Local LLM 說明；舊安裝及交接文檔標註為歷史。
- 測試 runner 每模組獨立執行；UI runner 改用現有測試。
- 原始碼打包改成目前檔案清單，包含資產／license，排除機器設定、資料與 runtime。

## 已移出的範圍

| 分類／目標 | 檔案數 | 影響 |
| --- | ---: | --- |
| `COMPLETE-MANIFEST.json` | 1 | 舊 ZIP hash／解壓說明已失效；目前以 run.py 啟動，新的來源包內有獨立 manifest。 |
| `PARTS-MANIFEST.json` | 1 | 舊 ZIP hash／解壓說明已失效；目前以 run.py 啟動，新的來源包內有獨立 manifest。 |
| `請先讀_需要全部3份.txt` | 1 | 舊 ZIP hash／解壓說明已失效；目前以 run.py 啟動，新的來源包內有獨立 manifest。 |
| `scripts/acceptance_summary.py` | 1 | 只用於重寫歷史程式／報告；已搜尋目前 app 與 tests，沒有依賴。這組腳本內部互相引用，整組移除。 |
| `scripts/current_acceptance_report.py` | 1 | 只用於重寫歷史程式／報告；已搜尋目前 app 與 tests，沒有依賴。這組腳本內部互相引用，整組移除。 |
| `scripts/exact_ui_rejection.py` | 1 | 只用於重寫歷史程式／報告；已搜尋目前 app 與 tests，沒有依賴。這組腳本內部互相引用，整組移除。 |
| `scripts/final_entry_fixes.py` | 1 | 只用於重寫歷史程式／報告；已搜尋目前 app 與 tests，沒有依賴。這組腳本內部互相引用，整組移除。 |
| `scripts/final_report_details.py` | 1 | 只用於重寫歷史程式／報告；已搜尋目前 app 與 tests，沒有依賴。這組腳本內部互相引用，整組移除。 |
| `scripts/finalize_documents.py` | 1 | 只用於重寫歷史程式／報告；已搜尋目前 app 與 tests，沒有依賴。這組腳本內部互相引用，整組移除。 |
| `scripts/finalize_mcp_acceptance.py` | 1 | 只用於重寫歷史程式／報告；已搜尋目前 app 與 tests，沒有依賴。這組腳本內部互相引用，整組移除。 |
| `scripts/fix_ui_driver.py` | 1 | 只用於重寫歷史程式／報告；已搜尋目前 app 與 tests，沒有依賴。這組腳本內部互相引用，整組移除。 |
| `scripts/harden_diff.py` | 1 | 只用於重寫歷史程式／報告；已搜尋目前 app 與 tests，沒有依賴。這組腳本內部互相引用，整組移除。 |
| `scripts/harden_inspection.py` | 1 | 只用於重寫歷史程式／報告；已搜尋目前 app 與 tests，沒有依賴。這組腳本內部互相引用，整組移除。 |
| `scripts/precise_blocker.py` | 1 | 只用於重寫歷史程式／報告；已搜尋目前 app 與 tests，沒有依賴。這組腳本內部互相引用，整組移除。 |
| `scripts/reconcile_acceptance.py` | 1 | 只用於重寫歷史程式／報告；已搜尋目前 app 與 tests，沒有依賴。這組腳本內部互相引用，整組移除。 |
| `scripts/reconcile_authorized_followup.py` | 1 | 只用於重寫歷史程式／報告；已搜尋目前 app 與 tests，沒有依賴。這組腳本內部互相引用，整組移除。 |
| `scripts/refresh_followup_documents.py` | 1 | 只用於重寫歷史程式／報告；已搜尋目前 app 與 tests，沒有依賴。這組腳本內部互相引用，整組移除。 |
| `scripts/report_counts.py` | 1 | 只用於重寫歷史程式／報告；已搜尋目前 app 與 tests，沒有依賴。這組腳本內部互相引用，整組移除。 |
| `scripts/save_continuation_checkpoint.py` | 1 | 只用於重寫歷史程式／報告；已搜尋目前 app 與 tests，沒有依賴。這組腳本內部互相引用，整組移除。 |
| `scripts/update_acceptance_report.py` | 1 | 只用於重寫歷史程式／報告；已搜尋目前 app 與 tests，沒有依賴。這組腳本內部互相引用，整組移除。 |
| `codex-env-diag-20261004` | 40 | 移除當時的日誌、測試小 repo 及報告；不改 Windows／Codex 設定。該目錄檔案已受 Git 追蹤，可從歷史取回。 |
| `__pycache__` | 1 | 只移除指定 cache 目錄，Python 下次執行會重建。 |
| `acw/__pycache__` | 19 | 只移除指定 cache 目錄，Python 下次執行會重建。 |
| `acw/adapters/__pycache__` | 11 | 只移除指定 cache 目錄，Python 下次執行會重建。 |
| `scripts/__pycache__` | 8 | 只移除指定 cache 目錄，Python 下次執行會重建。 |
| `tests/__pycache__` | 35 | 只移除指定 cache 目錄，Python 下次執行會重建。 |

合計 134 個檔案，約 4.80 MiB。原始逐檔大小、SHA-256 與 Git 追蹤狀態保存於 [本機清理 manifest](../evidence/cleanup/plan-20261009.json)；該檔保留盤點當時的待確認狀態，執行結果以上方操作紀錄為準。範圍僅限此 repo，未追蹤 junction／symlink。

## 還原與後續

- 從備份按原相對路徑取回需要的項目；還原前確認目的檔不存在，避免覆寫後續修改。
- Git 追蹤的舊來源也可從版本歷史取回，這次沒有 commit 或 push。
- Python cache 下次正常啟動會自動重建；重新出現不代表清理失敗。
- 歷史交付文檔保留原始文字；其中指向舊診斷目錄或分包 manifest 的路徑已不在根目錄，請依本紀錄取回。

## 清理後驗證

- 八個獨立程序共 149 項離線測試通過：維護工具、首次啟動引導、Agent instance、Local UI、主 UI、session 標籤、Dot fixture 與 Monitor。完整紀錄見 [測試結果](../evidence/test-runs/20261009T091631247114Z/result.json)。
- `run.py --help` 正常；本機捷徑的 Python 目標存在，參數仍指向本 checkout 的 `run.py`。
- 134 個備份檔 hash 與盤點一致，28 個保留檔 hash 不變；目前文件連結與 `git diff --check` 通過。
- 清理後來源 ZIP 產生成功；已確認不包含移出的腳本、本機設定、資料、runtime 或備份，必要入口與 helper 仍在。
- 此驗證未啟動真實 Agent 推論，也不代表 Desktop 後端連線驗收。

## 保留

- `run.py`、`acw/` 原始碼與 assets、`requirements.txt`、本機啟動捷徑。
- `vendor/`、所有 `node_modules/`、`.venv/`、`.git/`、`.claude/`。
- `config/local-llm.json` 與範例；不讀出或覆寫機器 endpoint／credential 設定。
- `test-data/` 與所有 SQLite、WAL、raw、artifact；資料夾名稱含 test 不代表沒有重要對話。
- `evidence/`、`docs/evidence/` 與目前 Monitor 截圖、測試報告。
- `tools/`、`scripts/dot_cli_entry.py`：仍被 adapter 使用。
- `AI-Collab-Monitor/`：可獨立使用的舊工具及紀錄，不因新版 Monitor 存在就推定可刪。
- 舊 EXE 審查來源、live 驗收腳本及 `tests/legacy_ui/`：保留追溯，維護索引已標明不屬目前預設入口。

這次不更新第三方版本、不部署舊安裝位置、不修改使用者資料庫、不執行真實 Agent 任務。
