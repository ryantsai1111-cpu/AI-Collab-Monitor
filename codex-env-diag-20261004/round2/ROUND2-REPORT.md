# 第二輪報告 — 提權唯讀查詢結果（狀態改變前）

- 本輪開始：2026-10-04 20:57:49 (+08:00)；機器 Ryan-PC，使用者 `ryan-pc\ryant`
- 故障目標（與最新日誌一致，未改變）：
  `C:\Users\ryant\AppData\Local\OpenAI\Codex\runtimes\cua_node\81ea4d5168ddd0a3\bin\node_repl.exe`

## §1 持有者與證據

| 查詢 | 權限 | 結果 | 證據檔 |
|---|---|---|---|
| NTSTATUS 探測（只要求 FILE_READ_ATTRIBUTES / READ_CONTROL / 零存取） | 一般 | win32=5，**ntstatus=0xC0000056 STATUS_DELETE_PENDING** | `ntstatus-before-user.txt` |
| 同上 | 提升 | 相同：0xC0000056 | `elevated-query-output.txt` §1 |
| 對照：現用 runtime `45309…\node_repl.exe` | 一般 | OPEN_OK | （第二輪對話輸出） |
| handle64 v5.0 `-a -u 81ea4d5168ddd0a3`（僅搜尋） | 提升 | `No matching handles found.`（exit 1） | `elevated-query-output.txt` §2 |
| 全部程序的已載入模組 / 映像路徑掃描 | 提升 | 無符合 | `elevated-query-output.txt` §3 |

**結論**
- **已確認**：檔案處於刪除擱置。這是核心直接回的狀態碼，不是由「找到持有者」推論而來；
  上一輪的 H2（ACL / 擁有者損壞）可排除為本次存取被拒的原因。
- **持有者：未知**。程序名稱、PID、執行檔位置、使用者、父程序、啟動時間 —— 全部未知。
  沒有任何使用者模式程序以該檔為映像或載入模組。

**查詢工具的可信度（如實標示）**
- 模組掃描：有對照驗證 —— 對現用的 node_repl（PID 7104、21384）能正確找到 `45309…` 模組。
- handle64 搜尋：對照**未成立**。一般權限下搜尋 `45309…` 也回 `No matching handles found`
  （執行檔映像是 section 對映、不一定有具名 file handle，此對照本身不具鑑別力）；
  第二個對照（搜尋 `logs_2.sqlite`）執行超過 120 秒未結束，已由我中止（只中止我自己啟動的 handle64，無殘留程序）。
  因此「handle64 查不到」只能算弱證據，不能證明沒有任何 handle。

## §2 實際做過的動作

1. 新建 `round2\`，未覆寫上一輪檔案。
2. 從 `https://download.sysinternals.com/files/Handle.zip` 下載 Handle 到 `round2\sysinternals-handle\`；
   handle64.exe 簽章 Valid / Microsoft Corporation，
   SHA256 `24BAFCC570CC9BBB6B6E6652A57A519E0464E3996891AABA6F55299CCE20B04F`。
   經你確認後以 `-accepteula` 執行（HKCU\Software\Sysinternals 有一筆 EULA 已接受紀錄）。
3. 一次 UAC 提權，只跑 `elevated-query.ps1`（唯讀），跑完即結束；Claude 工作階段本身維持一般權限。
4. **沒有**關閉任何應用程式、handle 或程序（除了我自己卡住的對照查詢）；沒有修改設定、ACL、runtime。

## §3 方案 A 的影響評估

- 建議正常退出的具體應用程式與 PID：**無**。查詢沒有指出任何與故障目標有關的應用程式，
  所以沒有依據要求你關閉 Codex App 或其他程式。
- 依約定（持有者不明 / 可能在系統側 → 不強制處理）：改為由你**自行重新開機**。
  已寫好 `RESUME.md`。
- 重新開機會中斷：Codex 桌面 App 的進行中任務、dot 的工作、Claude 的工作階段、所有未存檔內容。

## §4 檔案狀態

| 時點 | 狀態 |
|---|---|
| 狀態改變前（20:58 一般 / 21:05 提升） | 目錄列舉可見（34,047,944 bytes），開啟一律 0xC0000056 → 仍然存取被拒（刪除擱置） |
| 狀態改變後 | **尚未測** |

## §5 驗收

| 項目 | 結果 |
|---|---|
| Codex CLI（本輪） | **尚未重測**（狀態未改變，依指示不重複測試）。上一輪結果：失敗 |
| dot | **待測**，Claude 無法代測。交辦文字見 `DOT-TEST-HANDOFF.md` |

## §6 仍未確認

1. 誰持有該檔的引用（核心 section、受保護程序如 Defender、或 handle64 看不到的程序）。
2. 重新開機是否能讓擱置的刪除完成（10/02 的 `be2aaea…` 案例只是旁證）。
3. 檔案消失後 sandbox setup 是否就不再報錯 —— 為何它還去驗證舊 runtime 路徑仍不明
   （`chrome-native-hosts-v2.json` 的過期項目是候選，未證實，本輪未動）。
4. 為何每次 App 更新後舊 `node_repl.exe` 會卡在刪除擱置（10/02、10/03 連續兩次不同 runtime）——
   若重開機後修好，下次更新可能再發生。

## §7 下一個需要批准的最小動作

你自行儲存工作並重新開機 → 回到對話告知 → 我依 `RESUME.md` §4 做檔案狀態確認與一次 CLI 測試。
若仍失敗：保存證據後停止，不進方案 B。
