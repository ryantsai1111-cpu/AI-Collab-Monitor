# Claude 與 Hermes（Qwen）的協作方式

> 2026-10-11 由 Claude 依實際操作整理。來源專案：KPR 訂單管理系統的「取代千奧」工作（分支 `feat/inventory-costing`）。
> 這份記錄的是「Claude 當規格與審查者、Hermes 上的 Qwen 當執行者」時，兩邊實際怎麼傳話、怎麼交接、怎麼驗收。
> 本檔只描述做法，不含任何帳密、金鑰或公司帳務數字。

## §1 角色

| 角色 | 誰 | 做什麼 |
| --- | --- | --- |
| 規格與審查 | Claude（Claude Code 桌面版） | 驗出規則、寫任務卡、啟動執行者、獨立複核、寫審查紀錄、決定放行或返工 |
| 執行 | Qwen `qwen3.8-flash-next`，經 Hermes Agent（provider `strata`） | 照任務卡寫程式與測試、跑驗收指令、寫報告、commit 與 push |
| 決策 | Ryan | 商業規則、部署、切換日、放寬安全設定 |

執行者的限制：context 128K、跨對話不保留記憶。所有做法都是繞著這兩點設計的。

## §2 傳話的管道：Hermes 的單次模式

> 2026-10-15 起現行腳本是 `~/.claude/skills/hermes-delegation/scripts/run.sh`（`-Q --format stream-json`，見 §9）；本節與 §2.1、§8 的 `C:\tools\cao\hermes\run.sh` 是 2026-10-11 當時的做法，保留作歷史。

Claude 不透過聊天視窗跟 Hermes 對話，而是用命令列啟動一次性的 Hermes 工作，結束後讀它的輸出與 git 紀錄。

```bash
H="/c/Users/ryant/AppData/Local/hermes/hermes-agent/.hermes/bin/hermes.exe"
"$H" chat --query-file '<提示檔的 Windows 路徑>' -Q \
  --in '<工作目錄的 Windows 路徑>' \
  --run-budget 3000 --max-turns 150 --source tool
```

| 參數 | 用途 |
| --- | --- |
| `--query-file` | 從檔案讀提示。不要用 `-q "…"`：中文、引號、反引號會被 shell 弄壞 |
| `-Q` | 安靜模式，只輸出最後的回覆與 session id |
| `--in` | 執行者的工作目錄（git worktree） |
| `--run-budget` | 每次執行的秒數上限；到 80% 時 Hermes 會提醒執行者收尾 |
| `--max-turns` | 工具呼叫次數上限 |
| `--source tool` | 這些 session 不出現在使用者的對話清單裡 |

- **沒有使用 `--yolo`**。不開它，執行者也能跑 git、測試、lint、push。
- 不要加 `-t` 限制工具組：曾經只給 `computer_use,vision`，結果執行者沒有檔案與終端機工具，存不了截圖。
- PowerShell 裡要呼叫這支程式，寫法是 `& "C:\…\hermes.exe" <參數>`；Bash 的寫法在 PowerShell 會解析失敗。

### §2.1 Claude 這邊的包裝腳本

`C:\tools\cao\hermes\run.sh <標籤>`：啟動一次 Hermes、把輸出寫到 `<標籤>.log`、結束後附上 `git log` 與 `git status`。
Claude 用背景工作執行它；背景工作結束時 Claude 會自動被叫起來，不需要輪詢。

```bash
#!/bin/bash
H="/c/Users/ryant/AppData/Local/hermes/hermes-agent/.hermes/bin/hermes.exe"
label=$1; prompt=${2:-'C:\tools\cao\hermes\start.txt'}
log="/c/tools/cao/hermes/$label.log"
date > "$log"
"$H" chat --query-file "$prompt" -Q --in 'C:\Users\ryant\Desktop\kpr-inventory-costing' \
  --run-budget 3000 --max-turns 150 --source tool >> "$log" 2>&1
echo "hermes_exit=$?" >> "$log"; date >> "$log"
cd /c/Users/ryant/Desktop/kpr-inventory-costing && { echo "--- git"; git log --oneline -6; git status --porcelain; } >> "$log" 2>&1
tail -c 2500 "$log"
```

**啟動前先確認沒有另一個 Hermes 工作在跑。** 曾經因為指令串接（前半段失敗、後半段仍執行）而把同一步啟動兩次。

## §3 每次都一樣的啟動句

執行者不記得上一次做了什麼，所以提示永遠是同一句，進度由檔案決定：

> 到 `C:\Users\ryant\Desktop\kpr-inventory-costing`，讀 `docs/briefs/kpr-inventory-costing/PROGRESS.md`，照它指的任務卡執行。只做進度檔指的那一步，做完該步的收尾（含 commit 與 push）後就結束並回報。

## §4 交接物：任務卡與進度檔

都放在執行者的 repo 裡（`docs/briefs/<feature>/`），所以它「能讀 repo」就夠了。

### §4.1 進度檔 `PROGRESS.md`（執行者的記憶）

- 「現在該做哪一步」：指向一張任務卡。
- 「如果你不記得做到哪裡」：用 `git log --oneline -8` 與 `git status --porcelain` 找回進度；有未 commit 的修改就接著做完，不要丟掉重來。
- 步驟狀態表：每步的狀態、commit、備註。
- 每一步都適用的規則：固定工作目錄與分支、不切分支、用 npm、不 `git add -A`、不 amend／rebase／force push、不推 main、不跑會清資料庫的指令、不加相依套件、**不要讀的大檔清單**、**長輸出一律導到檔案再 `tail`**、任務卡沒寫的事不要做、需要決定的事寫 `[DECISION NEEDED]` 後停下。

### §4.2 任務卡（一步一張，自成一體）

每張卡的固定章節：

1. **前置條件**：進度檔寫明上一步已核准才可開始。
2. **目的**：兩三句話，說明這一步在做什麼、為什麼。
3. **要動的檔案**：逐一列出，其他檔案一律不可動。
4. **介面**：型別與函式簽章寫死（下一步可能是全新對話，要靠這裡銜接）。
5. **規則表**：每條規則一個編號。
6. **必須有的測試**：逐案例給輸入與預期輸出，數字由 Claude 事先算好。
7. **驗收指令**：可直接貼上執行，輸出導到 `tmp/*.log`，只看結尾。
8. **變異測試**：指定要怎麼把程式改錯、預期哪個測試轉紅；先 commit 再做，做完還原。
9. **收尾**：`git add` 的確切路徑、commit 訊息、報告檔名與章節、更新進度檔、push、最後回報的那一句話。

寫卡片的原則：

- 卡片自己帶齊資訊，**不要叫執行者去讀別的文件**（第一版要求先讀 60 KB 文件，不適合 128K context）。
- 未驗證的規則不讓執行者自己決定：引擎遇到就丟明確錯誤。
- 一步的大小以「8–20 分鐘做得完」為準；卡片提醒它 context 用掉一半就結束對話，下次用同一句啟動句接著做。
- 測試資料一律自編，repo 裡不放真實單價、成本、客戶名稱。

## §5 Claude 的審查（每一步結束後）

不採信執行者的回報，以下每一項都自己做：

1. 讀 log 結尾與 `git diff --stat <上一個核准點>..HEAD`：只動了任務卡列出的檔案嗎？
2. 重跑該步的測試與 eslint。
3. 自己做變異測試（不只做卡片指定的那幾個）。
4. **把真實資料全量送進執行者的實作重播**，和原系統存的數字比對。這一步抓得到單元測試抓不到的問題，也同時驗證任務卡裡的規則本身。
5. 寫審查紀錄 `deliverables/reports/<feature>-review-<步驟>.md`：複核做法與結果、任務卡的錯誤、執行者的調整、未解決事項。
6. 核准：更新進度檔指向下一張卡（`approve.mjs`），commit、push，再啟動下一次。
   不核准：寫返工卡，說明哪裡錯、證據是什麼、要怎麼改。

實際結果（2026-10-10 至 10-11，8 步）：每步 5–20 分鐘，沒有一步需要返工。
執行者回報的異常全部是 Claude 任務卡寫錯（等價變異、比對基準用了落後的本機 `main`、找失敗測試的指令格式不對），它都照規定回報而沒有自行繞過。

## §6 讓 Hermes 操作畫面（computer use）

用途：查資料與靜態分析回答不了的事，例如畫面上的選項文字、選單位置、查詢結果的樣子。

### §6.1 前提

- Hermes 的 `computer_use` 與 `vision` 工具組要啟用（`hermes tools list` 可查）。
- 單次模式下，所有滑鼠鍵盤動作預設會被擋：
  `BLOCKED: computer_use click requires approval but single-query mode (-q) runs without a user present`。
  要讓它在沒有人當場核准時也能動作，必須把 Hermes 設定 `approvals.single_query_mode` 設為 `approve`。
  **這是放寬安全設定，由 Ryan 本人執行**（2026-10-11 已設）：

  ```powershell
  & "C:\Users\ryant\AppData\Local\hermes\hermes-agent\.hermes\bin\hermes.exe" config set approvals.single_query_mode approve
  ```

  收回：`config unset approvals.single_query_mode`。
- 需要登入的程式由 Ryan 先登入。Claude 與 Hermes 都不輸入帳密。

### §6.2 任務檔的寫法

範例：`C:\tools\bwerp\task-trial-balance.txt`。

- 開頭寫明這是正式系統、只能看不能改。
- **禁止清單**：逐字列出不可以按的按鈕（新增、保存、修改、刪除、審核、過帳、結帳、導出、列印）、不可在儲存格輸入、遇到「是否保存」一律按否或取消、不關閉程式、不登出、不碰其他視窗、不輸入帳密。
- **步驟**：每步一個動作、一張指定檔名的截圖。用畫面上的確切文字（先確認介面語言；BWERP 是英文介面）。
- **停止條件**：畫面和步驟對不上就截圖停下回報。
- **回報格式**：要它抄的是欄位名稱與選單文字，**不要抄金額**；數字留在截圖裡。
- 截圖存在 repo 之外的本機資料夾，不進 git。

### §6.3 這次學到的

- 執行者卡住時不會乖乖停：期間查找視窗的清單是空的，它自己寫了十幾支偵測腳本繼續試，把時間用完也沒有結論。任務檔要寫死「同一個障礙嘗試兩次不成就停下回報」，並把 `--run-budget` 設短（畫面任務 10 分鐘內）。
- 畫面任務比程式任務不穩定得多。能用資料或反編譯結果回答的問題，不要用畫面操作。
- 遇到「清單是空的」這類情況，請人看一眼比再跑一次便宜。
- Claude 自己也有電腦操作工具，但每一步都要傳整張截圖，token 成本高；Ryan 指示畫面操作交給 Hermes。
- Hermes 的電腦操作驅動（`cua-driver`）有新版可更新；目前版本截圖正常，點擊穩定性未充分驗證。

## §7 不交給這個循環的事

- 合併到 `main`（等於部署）、動正式資料庫、裝到公司內網主機。
- 需要 Ryan 決定的商業規則（任務卡與報告裡標 `[DECISION NEEDED]`）。
- 放寬任一邊的安全設定。
- 在正式的 ERP 或會計系統上做任何會存檔的操作。

## §8 檔案位置一覽

| 東西 | 位置 |
| --- | --- |
| Hermes 命令列 | `C:\Users\ryant\AppData\Local\hermes\hermes-agent\.hermes\bin\hermes.exe` |
| Claude 的包裝腳本、啟動句、各次執行的 log | `C:\tools\cao\hermes\`（`run.sh`、`start.txt`、`approve.mjs`、`hold.mjs`、`<標籤>.log`） |
| 任務卡與進度檔 | `Desktop\kpr-inventory-costing\docs\briefs\kpr-inventory-costing\` |
| 執行者的報告、Claude 的審查紀錄 | `Desktop\kpr-inventory-costing\deliverables\reports\kpr-inventory-costing-{report,review}-<步驟>.md` |
| 畫面任務檔與截圖 | `C:\tools\bwerp\`（不進 git） |

## §9 與本監看器的關係

`run.sh`（`~/.claude/skills/hermes-delegation/scripts/run.sh`）已經接上本監看器，Hermes 的執行會即時出現在 HERMES pane 與 TIMELINE pane（2026-10-15 實作）。監看器本身仍只讀 `logs\*.log`，不啟動也不協調 Agent。

- 環境變數 `HERMES_MONITOR_ROOT`：監看器根目錄，預設 `C:/Users/ryant/Desktop/AI-Collab-Workspace/AI-Collab-Monitor`。目錄不存在時 `run.sh` 印 `monitor: off (<path> not found)` 並照常執行，不報錯。
- Hermes 以 `-Q --format stream-json` 執行，stdout 與 stderr（`2>&1`）都經 `scripts/hermes_stream_filter.py`，它是 `<label>.log` 唯一的寫入者（原生 exe 拿到 `2>> file` 控制代碼時不會 append，會蓋掉過濾器寫的行）；stderr 行對過濾器而言是「非 JSON 行」。
- 完整紀錄：`C:/tools/hermes/runs/<label>.log`（每一行原始 JSON 與 stderr，**未遮罩**，不在監看器目錄）。
- 人看的摘要：`<監看器>\logs\hermes.log`（UTF-8 無 BOM、附加、CRLF 結尾）。內容是回覆文字、`[TOOL] <name> <input 摘要 ≤120 字>`、`[TOOL DONE] <name> <ms> error=<bool>`、`[RESULT exit=N] <最後回覆>`。不印工具輸出；`sk-…`、`ghp_…`、`AKIA…`、`Bearer …`、`password=`／`token=`／`api_key=` 後面的值換成 `***`。
- 狀態事件：`<監看器>\logs\timeline.log`，格式 `<ISO8601 含時區> | <label> | HERMES | <EVENT> | <訊息>`。`RUN_STARTED`、`RUN_ENDED`（`exit=`、`result_exit=`、`dirty=<n> files`）由 `run.sh` 寫；`DECISION_NEEDED`（輸出含 `[DECISION NEEDED]`）、`REPETITION_DETECTED`（含 `Repetition Detected`，stdout 或 stderr 都算）由過濾器寫。
- 互斥鎖：`C:/tools/hermes/runs/hermes.lock`（`HERMES_LOG_DIR` 可改位置），一行 JSON `{pid, label, worktree, hermes_exe, started}`，pid 是 run.sh 這個 bash 行程（它活著的時間就是整個 run 的時間）；鎖在啟動 hermes 前以 noclobber 原子建立。鎖存在且 pid 活著 → `REFUSED: hermes run <label> (pid N) still running`、exit 3；pid 已死 → 印 `stale lock removed` 後繼續。run.sh 正常結束或被 Ctrl-C／TERM 會刪鎖（只刪自己的）；被硬殺（taskkill）時鎖會殘留，下次啟動發現 pid 已死會自動清掉。
- 離線測試：`bash ~/.claude/skills/hermes-delegation/scripts/tests/run-offline.sh`，用替身 `fake-hermes.sh`，不會啟動真的 hermes.exe。
- Claude 的審查決策：`progress.mjs approve／hold／point` 會把 `APPROVE`／`HOLD`／`REWORK` 寫進 `logs\claude.log` 與 timeline，CLAUDE pane 因此不再是空的。

## §10 補充：Claude 串接 Codex（2026-10-12 實測）

### §10.1 一定要用桌面版附帶的 codex.exe

這台電腦有兩個 Codex 命令列：

| 位置 | 版本 | 狀況 |
| --- | --- | --- |
| PATH 上的 `codex`（npm 全域安裝，`C:\nvm4w\nodejs\codex`） | 0.156.0 | 太舊：模型清單沒有設定檔指定的 `gpt-6.1-sol`，一啟動就回 400；電腦操作環境也起不來（`helper_unknown_error: setup refresh had errors`） |
| 桌面版附帶的 `%LOCALAPPDATA%\OpenAI\Codex\bin\<雜湊>\codex.exe` | 0.162.0-alpha.2 | 可用：`gpt-6.1-sol` 在清單內，環境裡有 `computer-use` 技能與 `mcp__cua_repl` 工具 |

`bin` 底下有多個雜湊資料夾，取最新的那個（AI-Collab-Workspace 的 `acw/adapters/codex.py` 也是這樣挑）。

### §10.2 三種串接方式

1. **單次模式（和 Hermes 的做法對等，最簡單）**

   ```bash
   M="$LOCALAPPDATA/OpenAI/Codex/bin/<最新雜湊>/codex.exe"
   "$M" exec -C '<專案資料夾>' --skip-git-repo-check -s read-only \
     -o '<最後回覆的輸出檔>' - < <提示檔>
   ```

   - 提示從 stdin 讀（結尾的 `-`），避免中文與引號被 shell 弄壞。
   - `-o` 只存最後一則回覆；完整過程在 stdout。
   - 預設沿用使用者設定檔的模型與推理強度；要省額度可加 `-c 'model_reasoning_effort="low"'`。
   - 實測：純文字問答 10 秒、約 6,000 token。
   - **尚未實測**：在這個模式下真的執行電腦操作（Ryan 當時已暫停電腦操作）。唯讀沙箱可能擋住電腦操作所需的輔助程式。

2. **app-server（AI-Collab-Workspace 的做法）**：`codex.exe app-server --listen stdio://`，以 JSON-RPC 送 `thread/start`、`turn/start`，同一個 thread 可以連續對話、即時收到事件與核准請求。適合要長時間互動或要把事件接進監看器的情況；Claude 這邊要自己寫一個小的客戶端。

3. **把訊息排進桌面版既有的對話**：`codex.exe queue --thread <對話的 UUID 或確切名稱> --message <文字>`。訊息會進到使用者在桌面版看得到的那個對話，沿用該對話的專案與權限（例如「完整存取權」），使用者可以當場看著、隨時暫停。**畫面操作建議走這條**，因為桌面版的電腦操作環境是完整的，而且人看得到。尚未實測。

### §10.3 不做的事

不替使用者把 Codex 的沙箱改成完整存取、不加 `--dangerously-bypass-approvals-and-sandbox`。需要更大權限的工作，由使用者在桌面版的對話裡授權。
