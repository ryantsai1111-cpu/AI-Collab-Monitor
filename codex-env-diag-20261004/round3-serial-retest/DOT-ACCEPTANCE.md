# dot 驗收紀錄

- 來源：使用者轉交的 dot 回覆截圖（2026-10-05）；Claude 未代測，只核對本機沙箱日誌。

## dot 回報的原始輸出

```
Computer : RYAN-PC
User     : ryan-pc\codexsandboxoffline
Time     : 2026-10-05T00:02:13.4675328+08:00
程序結束碼：0
```

## 本機沙箱日誌對照（`~/.codex/.sandbox/sandbox.2026-10-04.log` 尾段；跨午夜仍寫入同一檔）

```
[2026-10-04T16:02:11.691354300+00:00] setup refresh: processed 2 write roots (read roots delegated); errors=[]
[2026-10-05 00:02:11.691 codex-windows-sandbox-setup.exe] setup binary completed
[2026-10-05 00:02:11.826 codex.exe] helper launch resolution: using copied command-runner path ...\codex-command-runner-0.160.0.exe
[2026-10-05 00:02:12.603 codex-command-runner-0.160.0.exe] hide users: failed to hide current user profile dir (C:\Users\Default): ... 5
```

- 走的是 Codex App 內建的 codex（`bin\8aaf1547b825b104`，command-runner 0.160.0），不是 npm CLI 0.156.0。
- 沒有 `setup refresh had errors`、沒有 1056；`setup_error.json` 不存在。
- 時間吻合：setup 00:02:11 → 命令輸出 00:02:13。

## 判定

| 標準 | 結果 |
|---|---|
| 命令實際啟動並完成，結束碼 0 | 符合 |
| Computer = RYAN-PC | 符合 |
| Time 為執行當下 | 符合 |
| 無 `helper_unknown_error` / 無新的 setup 錯誤 | 符合 |
| User = `ryan-pc\ryant` | **不符 —— 但這是我在 DOT-TEST-HANDOFF.md 寫錯的標準** |

User 標準更正：沙箱（config `sandbox = "elevated"`）是用沙箱帳號建立程序的，
所以沙箱內的 `whoami` 本來就會是 `ryan-pc\codexsandboxoffline`，不會是 `ryant`。
這個值反而證明命令確實在沙箱內執行。原交辦文字不覆寫，以本檔更正。

**結論：dot 經 Ryan-PC 通道的唯讀命令執行已恢復（單次、單一命令）。**
未驗證：並行多命令、開機後首次使用（1056 情境）、下次 Codex App 更新後是否再出現刪除擱置。
