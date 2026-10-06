# RESUME — 重新開機後的續接步驟

- 撰寫時間：2026-10-04 約 21:15 (+08:00)
- 機器 / 使用者：Ryan-PC，`ryan-pc\ryant`
- 故障目標：`C:\Users\ryant\AppData\Local\OpenAI\Codex\runtimes\cua_node\81ea4d5168ddd0a3\bin\node_repl.exe`
- 診斷目錄：`C:\Users\ryant\Desktop\codex-env-diag-20261004\`（第一輪報告 `DIAGNOSIS-REPORT.md`；本輪在 `round2\`）

## §1 已完成

1. 最新日誌目標未變（`sandbox.2026-10-04.log`，最後一筆 20:48:55，仍是上述 `81ea…\node_repl.exe`）。
2. 一般權限與提升權限的 NTSTATUS 探測結果相同：開檔失敗 win32=5，**ntstatus=0xC0000056 (STATUS_DELETE_PENDING)**。
   → `ntstatus-before-user.txt`、`elevated-query-output.txt`
3. 提權唯讀查詢（Sysinternals handle64 v5.0，簽章有效，只用搜尋模式）：
   `No matching handles found`；所有程序的已載入模組 / 映像路徑也無符合項。
   → 使用者模式下**找不到持有者**。
4. 未關閉任何程式、未修改任何設定 / ACL / runtime。

## §2 為什麼需要重新開機

檔案確定在刪除擱置狀態，但沒有任何可見的使用者模式程序持有它，
所以沒有「可以正常退出的指定應用程式」。剩下的引用只可能在核心 / 受保護程序一側，
依約定不強制關閉 handle、不停止系統或防毒程序 → 只剩由你自行重新開機。

## §3 重新開機前請先儲存

- Codex 桌面 App（ChatGPT.exe）內進行中的對話與任務
- dot 的進行中工作
- Claude 桌面 App 的其他工作階段、編輯器未存檔內容
- 其他一般應用程式

重新開機請你自己做；Claude 不會執行，也沒有建立任何開機排程。

## §4 重新開機後的驗證（回到這個對話說「已重新開機」，或照下面手動做）

**4.1 檔案狀態（一般權限 PowerShell）**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\ryant\Desktop\codex-env-diag-20261004\round2\ntstatus-probe.ps1" -Target "C:\Users\ryant\AppData\Local\OpenAI\Codex\runtimes\cua_node\81ea4d5168ddd0a3\bin\node_repl.exe"
```

判讀（三選一，如實記錄，查詢本身失敗不算「不存在」）：
- 父目錄列舉成功且沒有 `node_repl.exe`，探測回 `0xC0000034` 或路徑不存在 → **已消失**
- `OPEN_OK` → **仍存在但可讀**
- `ntstatus=0xC0000056` 或 `0xC0000022` → **仍然存取被拒**

**4.2 Codex CLI 測試（一般權限，只跑一次，在既有 `test-repo`）**

```
codex exec --sandbox read-only --json "請使用 shell 工具實際執行 git rev-parse --show-toplevel 與 git status --short，回報真實輸出與結束碼。禁止修改檔案、安裝套件或呼叫其他 MCP 工具。失敗就明確回報，不自行重試。"
```

事件、stderr、結束碼、測試期間新增的 sandbox log 存到 `round2\after-reboot\`。
通過標準：JSON 事件中有兩個 git 指令的 command execution 項目、各自的輸出與 exit code 0，
且 sandbox log 該時段沒有 `setup refresh had errors`。只有主程序 exit 0 或最終文字不算通過。

**4.3 dot 驗收（Claude 無法代測）** → 見 `DOT-TEST-HANDOFF.md`

## §5 停止條件

重新開機後若仍失敗：保存新證據後停止。**不自動進入方案 B**
（不改 `chrome-native-hosts-v2.json`、`config.toml`、ACL、runtime）。
