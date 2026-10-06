# AI Collaboration Workspace — 使用指南

本指南對應 Windows／PySide6 驗收候選版。**Final 尚未通過**：真實 Qt UI 50 項及最後 widget 回歸 25 項通過；官方 Claude／Codex 雙向 handoff、串流、resume、Stop 的 16 項，以及官方唯讀 history UI 5 項通過。Dot 官方橋接仍不可用；桌面 EXE 曾被安全軟體拒絕啟動，installed EXE 現已不存在，未還原或重試。Claude 隔離 Edit 請求因視窗關閉而取消，未批准，不會自行重開。完整狀態見 [需求追蹤](REQUIREMENTS.md) 與 [Final Acceptance Report](../evidence/FINAL-ACCEPTANCE-REPORT.md)。

## 1. 開啟與資料位置

程式入口是 `AI Collaboration Workspace.exe`；launcher 已編譯，installer 已備妥，但尚未完成 per-user 安裝、建立桌面／Start menu 捷徑或雙擊 EXE 驗收。可見 Qt 測試已實際執行，並非從未啟動 UI；目前結果與執行限制見 [UI 驗收紀錄](../evidence/UI-EXECUTION-BLOCKERS.md)。啟動器使用 `python-path.txt` 指定的既有 Python 與程式內的 `vendor` 相依套件。

預設資料目錄是 `%LOCALAPPDATA%\AI-Collaboration-Workspace\data`；安裝程式位置是 `%LOCALAPPDATA%\AI-Collaboration-Workspace\app`。原本的 `C:\Users\ryant\Desktop\AI-Collab-Monitor` 保持獨立。

需要獨立測試資料時，可在程式目錄以既有 Python 執行：

```powershell
python run.py --data-dir C:\path\to\isolated-data
```

請指定新建的測試目錄與測試 repo。相同資料目錄一次只能開啟一個 Workspace 視窗。

啟動會還原本機選取的 Project、Task、對話與 session 對應；不會自動連線 Agent、不會自動 resume，也不會重送 prompt。

## 2. 建立 Project 與 Task

1. 按上方 **+ Project**。
2. 填入 **Name**、**Repository / directory**；可使用 **Browse** 選擇目錄。
3. 視需要填入 **Default branch** 與 **Notes**，按 **Save**。
4. 按 **+ Task**，輸入任務名稱。
5. 使用 **Project**、**Task** 選單切換；右側狀態選單可記錄 NEW、PLANNING、IMPLEMENTING 等固定狀態。

**Sync to agents** 會將目前 Project 的目錄交給 Claude／Codex adapter；Dot 只記錄專案、repo 名稱、branch、task 等本機 metadata，不代表 Dot 已能存取檔案或已接收訊息。

若有尚未送出的文字或附件，切換 Project／Task 會詢問是否清除。選 **No** 留在原上下文；選 **Yes** 才清除草稿並繼續。Agent 忙碌時應先等待或 Stop，不能切換上下文。

Workspace 不自行將工作標記 APPROVED，也不會因你選取 DONE 而推論 Agent 已完成驗證。

## 3. 連線 Agent

三欄各有獨立 **Connect Claude**、**Connect Dot**、**Connect Codex** 控制與狀態。正式 backend 的通訊握手完成後才會顯示 Connected；單純找到 executable 不算連線成功。

| Panel | 目前行為與限制 |
|---|---|
| Claude | 使用官方 Claude Code programmatic streaming；隔離真實測試已證明 message、streaming、cwd、tool、resume、model／effort 與 stop。先前 OAuth 過期屬歷史錯誤，使用者官方登入後的新實測已成功；不要將憑證貼入 Workspace。 |
| Dot | 顯示 Blocked 與 `Managed by ChatGPT / dot`，不提供假的可選 model／effort。沒有已批准的官方 transport，因此 Send、session 與 Stop 不可用。 |
| Codex | 使用官方 app-server，連線後取得實際 model／effort。既有登入與 sandbox／approval 政策仍由官方 backend 管理。 |

連線成功且閒置時，Connect 會變成 **Disconnect**。錯誤／離線狀態可按 **Reconnect**。重新連線不等於恢復原 session；請明確選取 session 並按 **Resume**。

如果 backend 回傳錯誤，欄位提示與下方狀態列會保留經安全過濾後的具體錯誤。完整狀態可在 **Diagnostics** 查看。

## 4. Session、Model、Effort

每欄的 **Session** 選單顯示 Workspace 已記錄的 sessions。選定 Project 並連線、閒置後，可按 **Discover…** 查詢後端支援的 session index。Claude 使用官方 SDK，範圍限於目前 cwd，不展開其他 worktree，也不會在啟動或 Connect 時自行掃描。

- **Import selected (no resume)**：將選定原生 session 的 metadata 加入本機選單；不改變目前 Task 對應、不讀取整段 transcript，也不會 resume。
- **New**：為目前 Task 建立新的 backend session。
- **Resume**：明確接續選中的 session，並建立 Task 對應。重新連線後仍需選擇正確 session。
- **Rename**：修改 Workspace 本機顯示名稱，不同步修改官方 Desktop 名稱。
- **History**：開啟 Workspace 已保存的歷史並套用 Agent 篩選；匯入原生 metadata 不會自動匯入原生 transcript。

在 Discover 視窗選中一個 session 後，可按 **View native history** 開啟唯讀預覽，分為 **Conversation / activity** 和 **Sanitized structured records**。只有實際 helper capability 可用時才啟用；否則顯示 **Native history unavailable** 並附原因。讀取在背景 worker 執行，只預覽選中的 session，不保存訊息、不改變 Task 對應、不 resume，也不發送 prompt。原生 SDK backend 讀取已在隔離測試通過，新 UI 控制尚待重測。若中途切換 project，結果會被丟棄並要求重新查詢。不能假設列出了所有官方 Desktop 私有對話。

**Model** 與 **Effort** 選項只來自連線 backend 的回報，可能依版本、帳號和模型改變。沒有可查詢的 model catalog 時顯示 **Default backend model**；沒有 effort 支援時顯示 **Unsupported / backend default**。這些文字不是可切換的模型。

## 5. 發送、串流與停止

選取 Project、Task，連線 Agent，建立或 resume 正確 session 後，在該欄底部輸入訊息，按 **Send** 或 **Ctrl+Enter**。

回覆會在串流到達時更新。對話、tool、command、file、error 會以不同種類記錄；可展開活動卡片查看其內容。來源沒有提供的欄位不代表零或成功。

各欄 **Stop** 只在該 Agent 忙碌且 adapter 確認支援取消時啟用。它要求官方 backend 中斷目前 turn，不會使用 taskkill 或殺掉 process tree。上方 **Stop current task** 需要確認，然後向忙碌中的 adapter 發出取消要求。

若出現 tool approval 卡片，先檢查請求，再按 **Deny** 或 **Approve**；Approve 另有確認。Workspace 不會自動允許工具，也不會替 Agent 放寬 sandbox。

**Attach** 與拖放只在 adapter 宣告支援時啟用，檔案必須位於允許的 project／artifact 範圍。Claude 支援有大小限制的 UTF-8 文字及 PNG／JPEG／GIF／WebP 圖片；文字與 PNG 已有獨立真實測試通過證據，其他格式不因此自動算通過。文字會套用秘密過濾；圖片像素不會自動遮罩。選擇附件後仍須按 Send 才會送出。附件發送與下方的 artifact 保存／匯出是不同操作。

## 6. Copy 與 Raw Events

訊息右上方的動作選單提供：

- **Copy**：只複製該訊息內容。
- **Copy with metadata**：包含訊息 metadata。
- **Open raw event**：開啟該訊息連結的安全過濾後 raw event；如果 raw 已不存在，改顯示已保存的訊息 metadata 及原因。

各欄 **Raw** 左側列出 event index，選取項目後右側顯示其安全過濾後 raw record；過期／缺少的 record 會顯示 metadata 和原因。**Logs** 在檔案總管開啟本機 raw log 目錄；**Files** 開啟目前 Project 目錄。

Raw event 盡量保留 backend 原始結構，但秘密與隱藏 reasoning 不會保存；相關刪除／遮蔽會留下記錄。不要把 raw 等同於可取得隱藏 chain-of-thought 的介面。

## 7. Forward／Handoff

上方 **Handoff** 模式選單提供 **Assisted**（預設）與 **Manual**。在已完成的 assistant response 上按 **Forward**，選擇另一個 Agent，或從訊息動作選單選 **Send to …**。

- **Assisted**：先開啟預覽，可加入 Additional note，按 Confirm and send 才送出。
- **Manual**：你點選 Forward 的目標即是明確發送動作；不另開預覽，直接送原始內容與 metadata。目標未連線時不會送出。

Assisted 預覽包含：來源與目標 Agent、Task、Project、Branch、時間、來源 session，以及原始訊息。**Original source message** 為唯讀；**Additional note** 可增加說明，會分開保存；**Outgoing handoff** 顯示實際將送出的 envelope。

在 Assisted 模式按 **Confirm and send** 才會送出。目標尚未 Connected 時此按鈕停用；關閉或取消預覽不會送出。目標必須在正確 Task 上有可用的新 session 或已 resume 的對應 session。

原始來源內容不會被註解覆寫。準備預覽、嘗試發送与成功收到回覆是不同階段；請以目標回覆／事件確認實際結果。重新啟動不會自動重試 handoff。Dot 目前可顯示預覽，但實際接收仍受官方橋接阻礙。

**Flow** 選單提供兩個獨立步驟：最新 Claude 回覆 → Dot、最新 Dot 回覆 → Codex。每個步驟都需要使用者點選，並遵守目前 Manual／Assisted 模式；缺少來源回覆或目標未連線時會停用。它不會自動串接下一步。Automatic orchestration 固定為 OFF。

## 8. 視圖、比較與筆記

上方視圖選單提供：

| 視圖 | 用途 |
|---|---|
| Workspace | 個別操作三欄 Agent。 |
| Monitor | 以三欄唯讀方式檢視 Workspace 與設定的 legacy logs；不能輸入或送訊息。 |
| Timeline | 按時間查看 prompt、response、tool、command、file、handoff、session、project、error、stop 等事件；雙擊看細節。 |
| History | 找回 Task、查詢本機對話與事件。 |

原 v0.1 Monitor 仍可獨立運作。Settings → Paths 的 **Legacy Monitor root** 指向舊 Monitor 根目錄；Monitor 模式會增量讀取既定四個 log，不改寫原檔案、不重啟 readers、不操作舊 session。現有四個 log 為空白時，沒有舊內容可顯示是正常狀態。reader 隔離測試及合成 UI 的唯讀切換測試已通過；正式四個 reader／pane 的端到端驗收另列於報告。

雙擊 Agent 標題可放大單欄；再次雙擊、按 **Three panels** 或 **Esc** 返回三欄。**F11** 切換全螢幕。Settings → Appearance 的 **Always on top** 可保持最上層。

**Compare** 至少需要目前 Task 有兩個 assistant responses；各側選擇一則回覆並排查看，不會自動判定對錯。**Task notes** 儲存本機任務筆記，不會自動送給 Agent；要分享時，明確複製到 handoff 的 Additional note。

## 9. History 與搜尋

進入 **History**：

1. 不輸入查詢字串時會列出 tasks。
2. 輸入字串後按 **Search** 或 Enter，查詢對話、command、file、response、error、task、project 等已保存內容。
3. 可設定 Agent、Status、**Current project**、branch、date、**Errors only** 篩選；日期使用 `YYYY-MM-DD`。
4. 雙擊 Task 還原其 Project／session 對應，然後仍需明確 Connect／Resume 才能接續 backend 工作。
5. 雙擊搜尋結果可查看保存內容。

backend Offline 時，本機歷史仍可查看。Date 欄位為日期範圍；branch 為精確字串篩選。Core 篩選測試及最近一次合成 UI 的 History／Search 操作已通過，不代表外部 Agent 的原生 transcript 已自動匯入。

## 10. Diff、Command、Tests 與 Artifacts

按 **Diff / Tests** 可查看 Unified diff、Side by side、Changed files、Tests、Branch / log 和 Artifacts。Git 查詢保留命令、stderr、exit code；沒有 upstream 時 ahead／behind 是未知，不等於 0。尚無第一個 commit 的 repo 會提示 unborn HEAD，分別列出 staged additions 與 unstaged tracked edits；untracked 檔案不會被偽造成 Git patch。

**Copy diff** 複製目前 diff；**Save patch** 另存 patch；**Open selected file** 開啟允許範圍內的檔案。Diff viewer 不編輯原始碼，也沒有 commit、push、merge。

Codex 官方 `commandExecution` 提供 **combined stdout/stderr**。空白 stderr 不表示命令沒有錯誤輸出；嚴格的 stdout／stderr 分流仍是 UNSUPPORTED。Tests 顯示已觀察到的 command、framework、passed／failed／skipped、duration 與 exit code；開啟檢視不會自行執行測試，也不補造未知結果。

在 **Artifacts** 分頁：

1. 按 **Import file…**，選擇目前 project 範圍內的 UTF-8 report、test log、diff、patch、JSONL、Markdown，或 PNG／JPEG screenshot。
2. 文字經安全過濾後保存為 Task 的受管理副本；JSONL 必須能逐行解析。Screenshot 先確認明確匯入，並驗證圖片結構。
3. 選取一筆後可按 **Open selected**、**Metadata** 或 **Export selected…**。Screenshot 在程式內預覽；文字副本交由 Windows 預設程式開啟。
4. 匯出 screenshot 時需逐張開啟預覽，可用 **Actual size** 檢查小字，再勾選已檢查並確認。圖片像素不會自動遮罩；取消檢查不會匯出。

輸入檔案有 16 MiB 上限，credential 類檔名與範圍外路徑會被拒絕。匯出不能覆寫 Workspace 的 DB、raw 或 artifact 儲存區。新 artifact 與 screenshot 控制仍需完整 UI 重測，不能以程式存在代替驗收。

## 11. Export、Diagnostics 與 Settings

選取 Task 後按 **Export**，選擇 Markdown、JSON、ZIP 或 HTML 與目的檔案。內容包含已保存的 Task／Project metadata、sessions、conversations、events、handoffs、artifacts；diff／test 資料必須先已記錄。Markdown／JSON／HTML 包含 screenshot metadata，不嵌入像素。ZIP 遇到已匯入的 screenshot 會先開啟逐張檢視與確認，確認後才包含圖片和安全說明；取消會取消此次匯出。這不是自動影像遮罩，分享前仍應確認可見內容。

**Diagnostics** 顯示 executable、version、backend、session、cwd、最後事件、最後錯誤及 capability。**Export diagnostics** 產生 `workspace-diagnostics.zip`，只收錄允許的執行狀態與安全過濾後 events，不收集 agent credential/config 檔案。

**Settings** 包含：

| 頁面 | 目前內容 |
|---|---|
| Agents | Enabled、Backend、Executable、Timeout、Default model、Default effort、Default project。模型與 effort 選單只使用目前 backend discovery；Streaming 和 Raw log 為唯讀的必要政策。 |
| Projects | Project 與唯讀 Git 使用說明。 |
| Paths | App data 位置與 Legacy Monitor root。 |
| Logs | Raw 保存及安全過濾說明。 |
| Permissions | 官方權限與明確 tool approval 邊界。 |
| Appearance | Always on top；視窗與快捷鍵說明。 |
| Retention | Retention days、Maximum raw log size (MB)、Archive rotated logs。 |
| Advanced | Automation OFF、啟動與 diagnostics 說明。 |

Settings 中的說明頁不是完整可編輯設定表。Agent 設定會在下次明確連線時套用；Default project 只在尚未選取全域 Project 時使用，不覆寫當前專案。Streaming 在 backend 支援時啟用；安全過濾後 raw audit 必須保存，沒有假造的關閉切換。

Retention 會輪替 raw segments、依 Archive 選項壓縮非使用中區段、刪除超過保留天數的自有 raw 檔案；過期 reference 會標示 expired，壓縮 reference 仍可讀。只影響新 Workspace 自己的 raw 目錄，不清理舊 Monitor。Core 設定及保留機制已有隔離測試，完整 Settings UI 重測仍依最新報告。

## 12. 結束與恢復

一般關閉會保存視窗大小與位置。若仍有 backend 工作，程式會詢問是否要求取消並關閉；可選擇不關閉繼續等待。

再次啟動會讀取本機持久化資料，恢復 Project、Task、history 與 session mapping。中斷中的內容可能標記 interrupted，狀態不明的 handoff 不會自動重送。為避免跨 streaming 片段秘密殘留，尚未完成的最後一行暫存於記憶體，崩潰時可能遺失；已完成的安全行、完整訊息與 session／Task 對應會持久化。請先檢查歷史與 Diagnostics，再自行 Connect／Resume。

若出現啟動、登入、bridge 或恢復問題，參閱 [TROUBLESHOOTING](TROUBLESHOOTING.md)、[ADAPTERS](ADAPTERS.md) 與 [SECURITY](SECURITY.md)。

## 指南與驗收的區別

本指南描述實際程式控制項，功能證據依各測試的原生／Core／UI 範圍分別記錄。589 PASS、0 FAIL、60 BLOCKED、4 UNSUPPORTED、0 PENDING；這不是653個原生端到端測試。Python source 的 UI 通過不能替代 EXE 啟動或三 Agent 真實同時運作驗收。現有 shortcut 指向的 EXE 仍缺失；不可自行還原、重建、重試或變更安全設定。請以 [Final Acceptance Report](../evidence/FINAL-ACCEPTANCE-REPORT.md) 為準。

## Smaller high-DPI screens

The workspace can scroll vertically and horizontally when the three panels exceed the available logical screen area. Scroll to reach input/actions; reopening restores the selected screen and bounds the window to available space. Diagnostics shows Claude MCP server/tool names as an observed snapshot only, with current agent connection state; it does not execute or authorize tools.


## Current approved Dot integration update

The earlier official-bridge blocker remains historical context. An explicitly approved, pinned unofficial Dot adapter and manual UI are now implemented and offline-tested. See [Dot activation and boundaries](DOT-UNOFFICIAL.md). Only the human may trigger live credential-bearing list/connect/read/send. No live Dot PASS or Final acceptance is claimed. EXE work remains deferred.
