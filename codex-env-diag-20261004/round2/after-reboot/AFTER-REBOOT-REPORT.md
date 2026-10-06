# 重啟後驗收報告

- 時間：2026-10-04 23:15–23:17 (+08:00)；一般權限，未提權
- 續接檔：`round2\RESUME.md`、`round2\ROUND2-REPORT.md` 位置與內容和記錄相符

## §1 重啟確認

| 項目 | 值 |
|---|---|
| hostname / 使用者 | `Ryan-PC` / `ryan-pc\ryant`（elevated: False） |
| 本次開機 | **2026-10-04 23:12:28**（System log：23:12:15 EventLog 6006 關閉 → 23:12:28 Kernel-General 12 啟動） |
| 上次開機 | 2026-10-02 23:54:19 |

→ `identity-and-boot.txt`

## §2 故障檔案狀態：**已不存在**

`…\runtimes\cua_node\81ea4d5168ddd0a3\bin\node_repl.exe`

- NTSTATUS 探測：win32=2，**ntstatus=0xC0000034 (OBJECT_NAME_NOT_FOUND)**（重啟前為 0xC0000056）
- 父目錄 `…\81ea4d5168ddd0a3\bin` 可正常列舉，內容 0 項 → 不是「查詢遭拒」
- 我沒有刪除、替換或重建它

→ `ntstatus-after-reboot.txt`

## §3 Codex CLI 測試：**未通過（1/2 完成）**，只跑一次

測試時間 23:15:42 → 23:16:15，於既有 `test-repo`，主程序 exit 0（不作為判定依據）。

| 命令 | command_execution 事件 | 輸出 | 結束碼 |
|---|---|---|---|
| `git rev-parse --show-toplevel` | 有（item_1，status=completed） | `C:/Users/ryant/Desktop/codex-env-diag-20261004/test-repo` | **0** |
| `git status --short` | **無**（程序未建立） | 無 | 無 |

第二個命令的原始錯誤（stderr 15:16:04.530Z 與 Codex 回報一致）：

```
exec_command failed: CreateProcess { message: "Rejected(\"Failed to create unified exec process: CreateProcessWithLogonW failed: 1056\")" }
```

Windows 錯誤 1056 = ERROR_SERVICE_ALREADY_RUNNING（An instance of the service is already running）。

→ `codex-exec-events.jsonl`、`codex-exec-stderr.txt`、`codex-exec-exitcode.txt`

## §4 本次新增的沙箱日誌

→ `sandbox-log-new-lines.txt`（`sandbox.2026-10-04.log` 自 byte 6668 起）

- `setup refresh: processed 0 write roots (read roots delegated); **errors=[]**` → `setup binary completed`
- 沒有 `setup refresh had errors`，沒有任何 `81ea…` 字樣
- `setup_error.json` **已不存在**（重啟前內容為 helper_unknown_error）
- 兩個命令的 START 記錄時間相同（23:16:02.032）→ Codex 是同時發出兩個命令
- 另有一行非致命警告：
  `hide users: failed to hide current user profile dir (C:\Users\Default): SetFileAttributesW failed … 5 (存取被拒。)`

## §5 失敗分類

- 仍是原檔案的 STATUS_DELETE_PENDING？**否**
- 舊檔已消失、但沙箱仍因引用同一路徑失敗？**否**（setup refresh errors=[]）
- **已變成其他錯誤：是** —— `CreateProcessWithLogonW failed: 1056`

原故障（`helper_unknown_error: setup refresh had errors`）在本次測試中未再出現。

## §6 新錯誤的已知與未知

已確認：
- 錯誤發生在 setup 成功之後、以沙箱帳號建立程序的階段（CreateProcessWithLogonW）。
- 同一批次的另一個命令在同一秒內成功建立並完成。
- Secondary Logon 服務（seclogon）StartMode=Manual，測試後檢查為 Running。

未確認（假設）：
- 兩個同時發出的 CreateProcessWithLogonW 在開機後首次使用時，競相啟動按需啟動的 seclogon 服務，
  其中一個得到 1056。若屬實，這是一次性競態，服務已啟動後不會再發生。
- 只測一次，無法區分「一次性」與「會重現」。依指示未重測。

## §7 驗收結論

| 項目 | 結果 |
|---|---|
| 重啟 | 已確認 |
| 故障檔案 | 已不存在 |
| 原 setup refresh 錯誤 | 本次未出現 |
| Codex CLI | **未通過**（不能標示「CLI 命令執行已恢復」） |
| dot | **仍待測**（`round2\DOT-TEST-HANDOFF.md`） |

## §8 下一個需要批准的最小動作

再跑**一次**相同的 CLI 測試（不改任何設定）。理由：seclogon 現在已在執行，
可直接檢驗 1056 是否為開機後首次使用的一次性競態。
風險：無設定變更，只多一次 Codex 請求與 sandbox log 記錄。
若再失敗：保存證據後停止；仍不進方案 B。
