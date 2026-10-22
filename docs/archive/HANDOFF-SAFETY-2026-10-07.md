# 自動協作交接安全修正（2026-10-07）

## 基準與範圍

基於 Ryan-PC 未提交工作副本：`ui/desktop-workspace-100pct-20261006`、HEAD `f9bbe8802aa208bdb26d0591b9754ccfcfd6e3c0`。2026-10-07 09:05:56 UTC 擷取的 12 檔來源經前後 SHA256 與 metadata 核對一致；09:20:13 UTC 再核對仍一致。保留 Codex 的角色獨立 project/task/session 與執行檔偵測變更。

## 本輪修改

1. `acw/orchestrator.py`：只接受第一個非空行的完整 VERDICT 控制行；允許整行粗體與中／英文冒號，拒絕前言後的判定、程式碼區塊、引用、部分 token、同一行附加說明。只移除控制行，保留交接正文中的示例。
2. 同檔：上一階段正文超過 12,000 字元時暫停，不截斷、不 refresh 或 send；Local 第二意見合併後同樣檢查。來源回覆仍保留在對話紀錄。此限制不含固定信封與原始任務，不是所有輸入的統一上限。
3. `acw/ui.py`：自動協作 active 期間不套用面板自動核准模式或 always-allow 規則，必須人工核准；不變更任何保存的模式，非執行中維持原行為。
4. `tests/test_orchestrator.py`：修正原本允許前言的測試，與既有設計契約一致；保留合法粗體測試。
5. 新增 12 個測試方法，含多個參數化邊界；更新設計文件。沒有更動資料庫、Agent 設定、官方 CLI 設定、認證、MCP、權限或防毒。

## 離線驗證

Python 3.12.14、PySide6 6.11.2、Linux Qt offscreen。沒有連線真實 Agent。

- 新增交接安全 10 方法：未修正來源重現 17 個失敗（包含 subtest）；修正後全通過。
- 新增核准邊界 2 方法：未修正來源重現 3 個 subtest 失敗；修正後全通過。
- orchestrator + 新交接測試 + 原核准測試 + 新核准測試：47 tests，OK。
- 全部目前頂層模組共 25 個：Ran 388 tests；358 passed、26 skipped、4 failures，另 1 個 setUpClass error。新增 12 方法全過。不能把此結果標為完整全綠。
- 與同份未提交來源逐模組比較，既有結果未退步；原 67 UI tests 與 19 個角色隔離 tests 通過。
- 獨立唯讀審查通過，未操作 Ryan-PC 或真實後端。

## 既有／環境限制（本輪不造資料掩蓋）

- `test_codex_adapter`：缺既有 `evidence/codex-schema/v2/ItemStartedNotification.json`，setUpClass error。
- `test_exe_source_hardening`：本 Linux 環境缺可信 PowerShell，2 failures；EXE 工作不在本輪範圍。
- `test_dot_ui`：期待舊英文 Unofficial，而現介面為中文，1 failure。
- `test_first_run`：仍斷言呼叫共用 require_task，最新角色獨立介面改用該角色的對話側欄，1 failure；在修正前的同份本機來源已重現。
- 26 skipped 包含 Windows 專用檢查及 opt-in live 測試，不等於通過。

## 尚未完成

本文件記錄雲端離線結果；本機套用及 Windows 測試結果須另附回報，不能預先視為成功。尚未驗證最新三 Agent 真實一輪、自動退回重做、非官方 Dot 的回覆完成辨識，以及原生工具核准端到端；不宣稱 Final acceptance。

真實試跑須用獨立測試專案與本次明確的 Dot 執行授權。維持必要的人為工具核准；不自動推送或操作正式專案。執行中的 Workspace 不會因檔案更新即時重新載入修正，需要安全重開後才生效。
