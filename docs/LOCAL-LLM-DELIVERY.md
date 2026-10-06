# Local LLM 第四角色交付驗收

驗證日期：2026-10-06（Asia/Taipei）。分支：`codex/local-llm-panel`；起點：`ui/desktop-workspace-100pct-20261006`。

Task A、B、C 的必要離線驗收已通過；全部既有測試結果等於基準，沒有新增失敗。新測試共 24 個通過。未連線真實模型伺服器，未 push。實作、測試與證據是一個完整 Local LLM 功能提交；最終 commit 與 diff 統計附於交付訊息。

## Task A：資料層與核心

**變更摘要**

- `acw/store.py`：新資料庫加入 `projects.local_cwd`、`tasks.local_session`；舊資料庫以 `PRAGMA table_info` 檢查後補欄位，兩欄皆為 `TEXT DEFAULT ''`。Local 的 raw 日誌及保留規則使用獨立角色名稱。
- `acw/core.py`：固定 tuple 的第四角色為 `local`；專案工作目錄、session mapping、手動連線／建立／恢復及交接沿用既有路徑。重新連線載入 `agent.local` 最新設定。session metadata 記錄 harness，避免把 Codex 對話交給 Claude 恢復。
- `tests/test_local_core.py`：舊結構逐欄位資料保留、重開冪等、新資料庫、Local session 隔離、設定重載及不同 harness 恢復拒絕。

**驗證結果**

| 驗收條件 | 結果 | 證據 |
| --- | --- | --- |
| 舊 SQLite 寫入 project/task 後升級，所有舊欄位不變 | PASS | `test_old_schema_upgrade_preserves_every_column_and_is_idempotent` |
| 重複開啟不出錯，欄位只有一份且預設空字串 | PASS | 同上，連續開啟兩次 |
| Local create/resume 更新 `local_session`，其餘三欄不變 | PASS | `test_local_session_create_resume_only_updates_local_column` |
| Local cwd 為專案 repo | PASS | 同上 |
| `test_core`、`test_offline_contracts` 不劣於基準 | PASS | 44 個 OK；18 個、2 個已知 WinError 1314，與基準一致 |

**根因說明**：第一次新 migration 測試的 SQLite fixture 沒有關閉 connection，Windows 清理暫存檔時出現 WinError 32。測試改為 `contextlib.closing` 明確關閉後通過，未變更產品 migration 來掩蓋錯誤。

**未盡事項與風險**：未開啟或升級實際使用者資料庫；既有資料庫首次以新版程式啟動時才補欄位。切換 harness 後，原對話仍保留，需切回原 harness 恢復，或明確建立新對話。

## Task B：兩種官方 CLI harness

**變更摘要**

- `acw/adapters/codex.py`、`acw/adapters/claude.py`：只新增額外 argv／child env 的小型擴充點。預設額外參數為空、env 為 None，既有 argv 不變，也不傳 `env` keyword。
- `acw/adapters/local.py`：兩個薄子類別與 factory；預設 Codex，依設定切換 Claude Code。Codex 用 `-c` 注入自訂 provider `acw_local`、模型及必要的環境變數名稱；Claude 使用複製後的 child env 與原有 `--model=`。
- Local 的模型清單只使用設定中的模型名稱，略過官方模型目錄的限制；沒有新增 `/models` 查詢（規格允許的可選項目）。Codex 未知影像能力不宣告可用。
- 只在明確連線時驗證 URL 並讀取指定金鑰環境變數。URL 僅接受 HTTP(S)，不接受內嵌認證／query；未填設定、無效 URL 或缺少環境變數均不啟動 child process。
- 金鑰值只存在 child env 與記憶體遮罩資料；診斷、事件與後端回傳的例外文字會遮罩。沒有寫入官方設定檔，也沒有修改目前程序的 `os.environ`。
- `run.py`：註冊第四個角色，依 harness 使用對應 CLI 自動偵測。Windows npm Codex wrapper 會解析到已安裝的原生 `codex.exe`，不增加 shell launcher 或依賴。
- `tests/test_local_llm.py`：所有 Popen 均 mock；包含 argv、TOML、env 隔離、啟動拒絕、金鑰遮罩、HOME 無寫入、Local model 送出、原 adapter 預設行為等測試。

**驗證結果**

| 驗收條件 | 結果 | 證據 |
| --- | --- | --- |
| 實際傳給 mock Popen 的 Codex argv 基底與 provider/model | PASS | `test_codex_popen_base_argv_and_toml_provider_overrides`；TOML 由 `tomllib` 解析檢查 |
| Claude child env 的 URL/token/model 正確，parent env 完全不變 | PASS | `test_claude_child_environment_and_model_do_not_mutate_parent` |
| 未設定 endpoint/model → Offline，Popen/run 皆 0 次 | PASS | `test_missing_endpoint_or_model_is_offline_without_any_process` |
| file/ftp 及無效 URL 被拒絕，Popen/run 皆 0 次 | PASS | `test_invalid_schemes_and_malformed_urls_never_launch` |
| 缺少 key 環境變數被拒絕 | PASS | `test_missing_key_environment_never_launches` |
| 假金鑰不出現在 argv/diagnostics/events/errors | PASS | `test_key_not_in_argv_diagnostics_events_or_errors`、`test_backend_exception_echo_is_redacted_before_propagation` |
| 測試未寫入 HOME 或官方 config | PASS | 兩種 connect 期間攔截 open/Path.open/Path.write_text；另比對暫存 HOME 前後內容 |
| Local 模型可送出，不依賴官方 model/list | PASS | `test_configured_codex_model_can_be_sent_without_official_catalog` |
| 原 adapter argv 相同、沒有 env keyword | PASS | `test_official_adapters_preserve_argv_and_omit_env_keyword` |
| `test_claude`、`test_codex`、`test_codex_adapter` 不劣於基準 | PASS | 18 OK（1 skip）、24 OK（2 skip）、6 tests/1 已知缺 schema error |
| 指定禁止修改的檔案 diff 為空 | PASS | 見末尾範圍檢查原始輸出 |

**CLI 與文件確認依據**

實際已安裝原生 CLI：`codex-cli 0.156.0`，與原架構文件的 0.160.0 不同。執行的是 `--version` 與 `app-server --help`，沒有啟動 app-server 連線或讀取登入認證。完整 help：[local-llm-codex-help.txt](evidence/local-llm-codex-help.txt)。

`app-server --help` 顯示 `-c, --config <key=value>` 支援 dotted path 與 TOML value，來源參照的是 `~/.codex/config.toml`，覆寫以命令列提供，程式不寫該檔案。

[官方 Advanced Configuration](https://developers.openai.com/codex/config-advanced) 的 Custom model providers 段落說明 provider 的 base URL、wire API、認證與 header，以及由 `model_provider` 選取自訂 provider；本功能使用自訂 ID `acw_local`，沒有覆寫保留的內建 provider。文件同時說明命令列 dotted override 與 TOML 解析。

[官方 Configuration Reference](https://developers.openai.com/codex/config-reference) 的 `model_providers.<id>.wire_api` 原文片段：

> `responses` is the only supported value

本實作因此使用 `wire_api="responses"`。本機 help 沒有列出 wire_api enum；合法值的依據為上述官方 reference，而不是宣稱 help 本身提供 enum。尚未以真實 endpoint 握手驗證此已安裝版本的 provider 相容性。

[Claude Code 官方部署文件](https://code.claude.com/docs/en/third-party-integrations) 說明以 `ANTHROPIC_BASE_URL` 路由至 gateway；Local Claude harness 沿用原 Messages 協定與模型參數。

**未盡事項與風險**：沒有本地模型伺服器，真實工具呼叫、approval 與端點握手由 Ryan／審查者依交接文件 §5 驗證。Codex endpoint 必須支援 Responses API；僅有 OpenAI Chat Completions 相容介面不足。Claude endpoint 必須支援 Anthropic Messages。模型清單查詢與模型管理未加入。

## Task C：介面與設定

**變更摘要**

- `acw/ui.py`：Local 面板、角色分頁、側欄對話分頁、Ctrl+4、歷史篩選、分支標籤與每則訊息的轉交選單。固定四角色順序；原交接流程仍只有 Claude → G8毛 → Codex。
- 自動布局依四欄 × 300 加 splitter handles 判斷；窄視窗沿用單一角色。沒有新布局、配色或 QSS。
- 現有設定頁實際是集中角色表單，與 handoff 的逐角色分頁描述不同；保留原三角色表單，新增 Local LLM 獨立分頁，包含原欄位及 harness／URL／模型／key env name。執行檔留空時自動偵測。儲存的 default_model 與新模型名稱同步。
- 未設定 endpoint/model 時顯示指定訊息並停用連線；設定完成後提示手動連線，儲存不呼叫 adapter。
- `tests/test_ui_refresh.py`：分頁數 3→4，新增第四個標題斷言；轉交選單斷言新增 Local LLM（Ryan 已在本次對話明確同意此規格例外）。其餘斷言不變。
- `tests/test_session_labels.py`：fixture 的角色 tuple 補 local，使既有所有面板檢查有對應的兩組專案／對話；沒有修改任何斷言。
- `tests/test_local_ui.py`：沿用 OfflineAdapter／OfflineWindow；新增 UI 驗收與 opt-in 原生 Windows 截圖 helper。

**驗證結果**

| 驗收條件 | 結果 | 證據 |
| --- | --- | --- |
| 第四角色分頁／側欄分頁標題 | PASS | 現有 67 UI tests 與新 startup test |
| 啟動及 poll_events 後 local adapter 無任何 calls | PASS | `test_startup_and_event_poll_never_call_local_adapter` |
| 1900×950 四面板可見、每欄至少 300，標題與輸入區可見 | PASS | `test_auto_layout_four_visible_wide_one_visible_narrow_without_scroll` |
| 760×720 單面板、水平 scroll 最大值 0；可選 Local | PASS | 同上 |
| Claude 轉交有 Local LLM；流程仍 2 steps，含 separator／說明共 4 actions | PASS | `test_forward_menu_contains_local_and_flow_still_has_two_steps` |
| 設定儲存 agent.local 正確，且未連線 | PASS | `test_settings_save_local_harness_endpoint_model_and_env_name` |
| Local 歷史篩選 ID／名稱與分支標籤 | PASS | `test_local_history_filter_uses_local_id_and_branch_label_updates` |
| 原生 Windows 字型、非 offscreen 的 1900×950 截圖 | PASS | [local-llm-panel.png](evidence/local-llm-panel.png) |
| 原 67 UI tests 通過 | PASS | 最終結果見下方原始輸出 |

**根因說明**：既有轉交測試寫死兩個目標，與新增 Local 目標的要求矛盾。Ryan 明確允許修改該斷言後通過。另一個 session labels 測試遍歷所有面板，但 fixture 只建立三個角色；補第四角色 fixture 後 11 tests 全數通過。新的 branch test fixture 原先宣告 `is_git=False`，所以產品正確顯示「非 Git repo」；測試改用具 branch 的 Git fixture 後通過。

原生螢幕為 1920×1200、Windows 縮放 125%；第一次原生視窗受 Qt／Windows 可用大小限制。截圖子程序用 `QT_SCALE_FACTOR=0.8` 抵銷系統 1.25 倍，得到 100% Qt 畫面；沒有改 Windows 顯示設定。截圖使用真實 Windows Qt 平台與 `QScreen.grabWindow`。畫面明確標為 offline fixture，不代表真實後端連線。

原生截圖執行輸出：

```text
PASS native Windows screenshot: 1900x950, platform=windows, font=Microsoft JhengHei UI, four panels visible, no adapter calls
```

**未盡事項與風險**：尚未進行真實模型回覆／工具核准驗收；所有 UI／adapter 測試皆離線。截圖中沒有假造訊息或工具成功結果。

## 原始測試輸出與範圍檢查

完整逐測試紀錄（包含初次 session-labels fixture 失敗與 FINAL RERUN）：[local-llm-tests.txt](evidence/local-llm-tests.txt)。以下使用每個模組的最後一次執行結果。

### Task A 新測試原文

```text
python -m unittest tests.test_local_core -v
test_local_session_cannot_resume_through_different_harness (tests.test_local_core.LocalCoreTests.test_local_session_cannot_resume_through_different_harness) ... ok
test_local_session_create_resume_only_updates_local_column (tests.test_local_core.LocalCoreTests.test_local_session_create_resume_only_updates_local_column) ... ok
test_reconnect_applies_saved_local_settings_and_harness (tests.test_local_core.LocalCoreTests.test_reconnect_applies_saved_local_settings_and_harness) ... ok
test_fresh_database_and_local_audit_are_supported (tests.test_local_core.LocalStoreTests.test_fresh_database_and_local_audit_are_supported) ... ok
test_old_schema_upgrade_preserves_every_column_and_is_idempotent (tests.test_local_core.LocalStoreTests.test_old_schema_upgrade_preserves_every_column_and_is_idempotent) ... ok

----------------------------------------------------------------------
Ran 5 tests in 0.206s

OK
```

### Task B 新測試原文

```text
python -m unittest tests.test_local_llm -v
test_backend_exception_echo_is_redacted_before_propagation (tests.test_local_llm.LocalAdapterTests.test_backend_exception_echo_is_redacted_before_propagation) ... ok
test_claude_child_environment_and_model_do_not_mutate_parent (tests.test_local_llm.LocalAdapterTests.test_claude_child_environment_and_model_do_not_mutate_parent) ... ok
test_claude_handshake_catalog_does_not_replace_local_model (tests.test_local_llm.LocalAdapterTests.test_claude_handshake_catalog_does_not_replace_local_model) ... ok
test_codex_popen_base_argv_and_toml_provider_overrides (tests.test_local_llm.LocalAdapterTests.test_codex_popen_base_argv_and_toml_provider_overrides) ... ok
test_configured_codex_model_can_be_sent_without_official_catalog (tests.test_local_llm.LocalAdapterTests.test_configured_codex_model_can_be_sent_without_official_catalog) ... ok
test_construction_does_not_read_credentials_or_launch (tests.test_local_llm.LocalAdapterTests.test_construction_does_not_read_credentials_or_launch) ... ok
test_factory_defaults_and_explicit_harness_executable (tests.test_local_llm.LocalAdapterTests.test_factory_defaults_and_explicit_harness_executable) ... ok
test_invalid_schemes_and_malformed_urls_never_launch (tests.test_local_llm.LocalAdapterTests.test_invalid_schemes_and_malformed_urls_never_launch) ... ok
test_key_not_in_argv_diagnostics_events_or_errors (tests.test_local_llm.LocalAdapterTests.test_key_not_in_argv_diagnostics_events_or_errors) ... ok
test_missing_endpoint_or_model_is_offline_without_any_process (tests.test_local_llm.LocalAdapterTests.test_missing_endpoint_or_model_is_offline_without_any_process) ... ok
test_missing_key_environment_never_launches (tests.test_local_llm.LocalAdapterTests.test_missing_key_environment_never_launches) ... ok
test_no_home_files_are_written_on_either_connect (tests.test_local_llm.LocalAdapterTests.test_no_home_files_are_written_on_either_connect) ... ok
test_official_adapters_preserve_argv_and_omit_env_keyword (tests.test_local_llm.LocalAdapterTests.test_official_adapters_preserve_argv_and_omit_env_keyword) ... ok
test_windows_npm_wrapper_resolves_installed_official_binary (tests.test_local_llm.LocalAdapterTests.test_windows_npm_wrapper_resolves_installed_official_binary) ... ok

----------------------------------------------------------------------
Ran 14 tests in 0.072s

OK
```

### Task C 新測試原文

```text
python -m unittest tests.test_local_ui -v
test_auto_layout_four_visible_wide_one_visible_narrow_without_scroll (tests.test_local_ui.LocalUiTests.test_auto_layout_four_visible_wide_one_visible_narrow_without_scroll) ... ok
test_forward_menu_contains_local_and_flow_still_has_two_steps (tests.test_local_ui.LocalUiTests.test_forward_menu_contains_local_and_flow_still_has_two_steps) ... ok
test_local_history_filter_uses_local_id_and_branch_label_updates (tests.test_local_ui.LocalUiTests.test_local_history_filter_uses_local_id_and_branch_label_updates) ... ok
test_settings_save_local_harness_endpoint_model_and_env_name (tests.test_local_ui.LocalUiTests.test_settings_save_local_harness_endpoint_model_and_env_name) ... ok
test_startup_and_event_poll_never_call_local_adapter (tests.test_local_ui.LocalUiTests.test_startup_and_event_poll_never_call_local_adapter) ... ok

----------------------------------------------------------------------
Ran 5 tests in 0.916s

OK
```

### 全部基準測試結果行原文

```text
python -m unittest tests.test_ui_refresh -v
Ran 67 tests in 15.052s
OK

python -m unittest tests.test_offline_contracts -v
Ran 18 tests in 1.188s
FAILED (errors=2)

python -m unittest tests.test_core -v
Ran 44 tests in 3.070s
OK

python -m unittest tests.test_dot -v
Ran 14 tests in 11.406s
OK

python -m unittest tests.test_security_review -v
Ran 11 tests in 0.210s
OK

python -m unittest tests.test_inspection -v
Ran 16 tests in 6.172s
OK

python -m unittest tests.test_claude -v
Ran 18 tests in 0.025s
OK (skipped=1)

python -m unittest tests.test_codex -v
Ran 24 tests in 0.031s
OK (skipped=2)

python -m unittest tests.test_recovery_process -v
Ran 2 tests in 2.904s
OK

python -m unittest tests.test_session_labels -v
Ran 11 tests in 19.963s
OK

python -m unittest tests.test_codex_adapter -v
Ran 6 tests in 0.030s
FAILED (errors=1)

python -m unittest tests.test_exe_source_hardening -v
Ran 23 tests in 1.593s
FAILED (failures=1)

python -m unittest tests.test_dot_ui -v
Ran 12 tests in 10.513s
FAILED (failures=1, skipped=1)

```

### 基準已知失敗

- `test_offline_contracts`：2 個 WinError 1314，Windows 目前沒有建立 symlink 的權限。
- `test_codex_adapter`：缺少既有 `evidence/codex-schema/v2/ItemStartedNotification.json`。
- `test_exe_source_hardening`：缺少既有 `install.ps1`。
- `test_dot_ui`：原測試期待英文 `Unofficial`，現有介面已是繁體中文。

以上各項的錯誤數量、skip 與根因皆與 `tests/README.md` 基準相同，沒有為本任務修改這些測試或補造缺檔。完整 traceback 保留於原始 log。

### Codex app-server help 原文片段

```text
codex-cli 0.156.0
Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`
```

### 範圍與語法檢查原始輸出

```text
git diff ui/desktop-workspace-100pct-20261006 -- acw/adapters/dot.py acw/security.py acw/theme.py acw/assets AI-Collab-Monitor tools requirements.txt

PASS syntax and imports

git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --cached --check -- acw run.py tests
```

範圍 diff 與程式碼／測試的 whitespace 檢查沒有輸出，代表通過。CLI help 與測試 log 保留原始空白及空行，沒有為了 whitespace 檢查改寫證據。`run.py` 保留原有 CRLF，所以檢查採 `cr-at-eol`，未改 Git 的持久設定。syntax 檢查涵蓋 `acw/*.py`、`acw/adapters/*.py`、`run.py` 與全部新 Local 測試；import 檢查涵蓋 `acw.adapters.local`、`acw.ui` 與 `run`。
