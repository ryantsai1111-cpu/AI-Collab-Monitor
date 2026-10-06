# 第三輪 — 受控串行複測報告

- 測試時間：2026-10-04 23:59:05 → 23:59:35 (+08:00)，只啟動一次
- 條件：Ryan-PC，`ryan-pc\ryant`，一般權限（elevated: False），開機時間 2026-10-04 23:12:28
- 指令：`codex exec --sandbox read-only --json "<prompt.txt 內容>"`，於既有 `test-repo`
- 未修改任何設定、服務、ACL、runtime；未啟動 / 停止任何服務

## §1 seclogon 狀態

| 時點 | State | StartMode | PID |
|---|---|---|---|
| 測前 23:59:06 | Running | Manual | 28528 |
| 測後 23:59:36 | Running | Manual | 28528 |

→ `conditions-before.txt`、`seclogon-after.txt`

## §2 兩個命令的執行證據

| # | 命令 | 事件 | 沙箱 log START | 輸出 | exit_code |
|---|---|---|---|---|---|
| 1 | `git rev-parse --show-toplevel` | item_1 started → completed | 23:59:19.839 | `C:/Users/ryant/Desktop/codex-env-diag-20261004/test-repo` | 0 |
| 2 | `git status --short` | item_2 started → completed | 23:59:25.137 | `warning: unable to access 'C:\Users\ryant/.config/git/ignore': Permission denied` + `?? README.md` | 0 |

- 串行：JSONL 中 item_1 completed 之後才出現 item_2 started；兩筆 START 相隔約 5.3 秒，無重疊。
- 兩個命令是各自獨立的 shell 呼叫，未合併。
- 第一個命令回傳的路徑即既有 test-repo。
- 第二個命令是「成功執行且有輸出」：`?? README.md` 與我直接執行的結果一致（未追蹤的 README.md 是建 repo 時就有的）。

→ `codex-exec-events.jsonl`、`codex-exec-stderr.txt`（僅 `Reading additional input from stdin...`）、`codex-exec-exitcode.txt`（0）

## §3 沙箱日誌（本輪新增）

- 兩次 `setup refresh … errors=[]` → `setup binary completed`
- **沒有 1056**、沒有 `CreateProcessWithLogonW` 錯誤、沒有 `setup refresh had errors`、沒有 `81ea…`
- `setup_error.json` 不存在
- 仍有非致命警告（每個命令一次）：
  `hide users: failed to hide current user profile dir (C:\Users\Default): SetFileAttributesW failed … 5`

→ `sandbox-log-new-lines.txt`

## §4 驗收

**Codex CLI 在本次一般權限、唯讀沙箱、串行命令測試下通過；冷啟動與並行穩定性尚未驗證。**

dot：**待驗收**（尚未實測）。

## §5 仍未確認 / 觀察項

1. 1056 的成因：上一輪「兩命令同時啟動 + seclogon 開機後首次按需啟動」的競態仍只是假設；
   本輪只證明 seclogon 已在執行且串行時正常，並行情境未測。
2. 舊 runtime `node_repl.exe` 刪除擱置的持有者始終未知；下次 Codex App 更新可能再發生。
3. `C:\Users\Default` 的 hide-users 警告與沙箱帳號讀不到 `~/.config/git/ignore` 的 git 警告：
   皆非致命，本輪未處理。
