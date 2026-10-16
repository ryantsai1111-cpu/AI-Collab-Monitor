# 交付規格書 — 每個 Agent 的角色腳本（playbook）與標準化派工流程

> 對象：Codex。**本文件自足。** 技術棧：Python 3.12 + PySide6 桌面協作站（ACW），`python run.py` 啟動，離線測試 `python scripts/run_tests.py`（UI 集合加 `--ui`）。
> 先讀 `docs/DESIGN-hermes-single-entry.md` §3.2 與 `docs/HERMES.md`「請求檔派工」一節，了解既有的請求檔機制（Hermes 已在用）。
> 本任務在新 branch `codex/playbooks-dispatch`（從 `ui/desktop-workspace-100pct-20261006` 切，它等於 `main` 加這份規格）進行，用 `git worktree add ../AI-Collab-Workspace-playbooks codex/playbooks-dispatch` 在另一個目錄工作。**不得 push main**；完成後開 PR 到 `main`。
> **worktree 裡不得用 junction／symlink 連主 checkout 的 `vendor/`**；需要 PySide6 就 `python -m pip install --target vendor "PySide6==6.11.2"`。不要啟動 `run.py`（使用者的 GUI 正從主 checkout 執行）。

---

## 0. 背景與決策（照做，不要自行改方向）

使用者（Ryan）的目標是一個「大型 AI 協作站」：每個 agent 各自綁 project／session，派工、核准、審查都在協作站裡完成。現況：

- Claude（Claude Code 桌面版）當架構與審查者，Hermes（本機 Qwen）與 Codex 當實作者。Claude 派工給 Hermes 的路徑已經自動化：skill 的 `run.sh` 寫 `data_dir/requests/<label>.json`，GUI 的 `acw/requests.py` `RequestDispatcher` 用協作站自己的 adapter 跑，回 `<label>.result.json`。
- 派給 Codex 仍是手動：Claude 寫 `docs/HANDOFF-x.md`，Ryan 把「照 docs/HANDOFF-x.md 執行」貼進 Codex 桌面版，做完再手動回報。
- 每個 agent 的「角色」散在程式碼裡：`acw/ui.py:41` `ROLE_LABELS`、`acw/monitor.py:11` `ROLES`、`acw/orchestrator.py:28-57` 的提示模板與 `ROLE_NAMES`、skill 裡的固定啟動句。使用者改不了。
- 2026-10-16 另一個問題：Claude 面板綁的 session 已被刪除，協作站仍硬 `--resume`，CLI 回「No conversation found」，面板只顯示英文錯誤。

決策：

1. **角色腳本（playbook）是一等資料**：每個 agent instance 一份，存在協作站設定，使用者在 GUI 編輯，所有派工（請求檔、自動協作）都先套它。
2. **請求檔派工開放給 Codex**（`agent: codex`），走 `CodexAdapter`（官方 app-server，`supports_approval=True`，核准在 Codex 面板按）。不做 Claude 的請求檔派工（Claude 本身是派工者）。
3. **協作站提供一支通用的派工腳本** `scripts/dispatch_request.py`，skill 端改呼叫它；Hermes 的 `run.sh` 本任務不動（審查者之後自己接）。
4. **resume 前先檢查 transcript 存在**，不存在就把綁定標為失效並用中文提示開新對話。
5. 不碰 adapter（`acw/adapters/*`）、不碰 `acw/store.py` 的 schema。

## 1. 不變量

1. 只動：`acw/requests.py`、`acw/core.py`、`acw/ui.py`、`acw/monitor.py`、`acw/orchestrator.py`（只為套 playbook）、`acw/agents.py`（若需要）、`acw/playbooks.py`（新）、`scripts/dispatch_request.py`（新）、`tests/*.py`、`docs/HERMES.md`、`docs/PLAYBOOKS.md`（新）、`docs/DESIGN-hermes-single-entry.md`。
2. 不過度工程：playbook 是一個 dict，不要做模板引擎、不要做版本控制、不要加新依賴。
3. `python scripts/run_tests.py --ui` 全綠；全套 0 FAIL。
4. 每個 Task 一個 commit，訊息英文；secrets 不進 repo。
5. 既有 Hermes 請求檔行為（`agent` 缺省＝`local`）必須完全相容：`tests/test_hermes_requests.py` 與 skill 的 `scripts/tests/run-offline.sh`（在 `~/.claude/skills/hermes-delegation/scripts/tests/`，可直接執行，用替身不碰真 hermes）都要維持全過。

## 2. 現況與整合點

### 2.1 請求檔 dispatcher（`acw/requests.py`）

- `RequestDispatcher.__init__(core, directory=None, agent='local', clock=…)` `:193`；`active()` `:205`；`poll()` `:259`；`_heartbeat()` `:274`；`_begin()` `:325`（守門：label、JSON、`run_budget`／`max_turns` 數值 `:345-352`、worktree 絕對路徑、`briefs/PROGRESS.md` `:364-372`、`allow_dirty` `:373-378`、adapter Connected）；`_launch()` `:408`（找或建 project、`prepare_conversation(fresh=True)`、暫時覆寫 `adapter.settings['run_budget'/'max_turns']` `:440-446`、`send_message`）；`_advance()` `:474`（逾時 `run_budget + GRACE_SECONDS` `:508`）；`_finish()` `:523`；`close()` `:550`。
- `MonitorProjection` `:62-190`：寫 `<root>/logs/hermes.log` 與 timeline，actor 字串寫死 `'HERMES'`（`:114`）；遮罩用 `acw/hermes_mask.py`。
- `REFUSAL_CODES` `:38`：這些代碼的 rejected 讓呼叫端 `REFUSED` 退出；其他 reason 讓 run.sh 回退直接路徑。
- 結果檔欄位：`label, status(complete|interrupted|rejected|error), reason, exit_code, session_id, task_id, started, ended`。

### 2.2 Codex adapter（`acw/adapters/codex.py`，只讀不改）

- `create_session()` `:450`、`resume_session(session_id)` `:458`（`thread/resume`，`approvalsReviewer: user`）、`send_message()` `:470`、`stop_if_owned(expected)` `:580`、`set_project()` `:590`。
- 核准請求由 `_emit("approval", request_id=…, details=…)` `:323` 發出，面板的 `pending_approval_events`（`acw/ui.py:498`）累積，使用者在面板按核准後走 `core.approve(agent, request_id, approved)`（`acw/core.py:941`）→ `adapter.approve()` `:652`。沒有 `run_budget`／`max_turns` 設定。

### 2.3 角色與模板現況

- `acw/ui.py:40-41` `ROLE_NAMES`／`ROLE_LABELS`；`acw/monitor.py:11` `ROLES`（rail 卡片第二行文字）；`acw/agents.py:12-27` instance 只有 `id, provider, name`。
- `acw/orchestrator.py:28-53` 各步驟提示模板（`{task}`、`{lead}`、`{implementer}`、`{body}` 佔位）；`STEP_NAMES` `:53`；`ROLE_NAMES` `:57`。
- 側欄 agent 標頭：`sidebar_agent_title`（名稱）與其下角色／狀態行（`acw/ui.py` 約 2764 行 `select_role` 更新）。「⋯」工作區選單在 `acw/ui.py:2544-2571`（含「新增 Agent…」）。Settings 對話框的主題下拉在 `acw/ui.py` 約 4400 行（`ui_theme`）。

### 2.4 session 綁定與 resume

- `core.connect(agent)` `acw/core.py:325`；`core.resume_session(agent, session_id)` `:823`；`prepare_conversation` `:188` 在 task 有 `<agent>_session` 時呼叫 `resume_session`；`open_saved_conversation` `:206`。
- `acw/desktop_sessions.py:311` `history_stamp(agent, session_id)`：回傳本機 transcript 的 `(modified, size)`，找不到檔案回 `None`。`agent` 只接受 `claude`／`codex`。這就是「transcript 是否存在」的檢查。
- 面板已有「新對話並傳送」機制（`acw/ui.py:1132-1136`，用 `core.legacy_local_conversation` 判斷），可以沿用它的呈現方式。
- 2026-10-16 的實例：Claude 面板 task 綁 session `dba0c088-…`，`~/.claude/projects/*/` 沒有該 transcript，`claude --resume` 失敗，事件 `error: No conversation found with session ID`。

### 2.5 桌面監看器

- `AI-Collab-Monitor/logs/` 有 `claude.log`、`dot.log`、`codex.log`、`hermes.log`、`timeline.log`，GUI 的 `LegacyReader`（`acw/inspection.py:137`）會讀這五個並投影到對應面板。timeline 格式 `<ISO8601> | <label> | <ACTOR> | <EVENT> | <message>`。

---

## Task A：角色腳本資料模型與編輯器

**要求**：

1. 新檔 `acw/playbooks.py`：
   - `DEFAULTS`：四個內建 agent 的預設 playbook，內容從現有 `ROLE_LABELS`／`orchestrator` 模板抽出。每份 playbook 是 dict：
     ```python
     {'role': '架構與審查',                     # 短標題，顯示在卡片與側欄
      'duties': '...',                          # markdown，給人看
      'instructions': '...',                    # markdown，派工時加在提示最前面
      'limits': {'run_budget': 3000, 'max_turns': 150, 'timeout_seconds': 7200},
      'permissions': {'commit': True, 'push': True, 'outside_card': False},
      'report': '...'}                          # markdown，要求的回報格式
     ```
     內建預設：`claude` 架構與審查（instructions：只讀審查、不改檔、第一行 VERDICT）；`dot` 複核與轉交；`codex` 實作者（只做規格範圍、不 push main、回報附執行輸出）；`local`（Hermes）實作者（照 PROGRESS.md 指的任務卡、長輸出導到 tmp、`[DECISION NEEDED]` 規則）。文字用繁體中文，從 `docs/HERMES.md`、skill 的 PROGRESS 模板與 orchestrator 模板濃縮，不要超過各 15 行。
   - `load(core, agent)`：讀設定 `playbook.<agent_id>`，缺的欄位用 DEFAULTS 補（新增的 instance 用其 provider 的預設）；`save(core, agent, data)`：驗證（`role` ≤ 40 字、各 markdown ≤ 20000 字、limits 正整數、permissions 布林）後寫設定，並把渲染後的 markdown 寫到 `data_dir/playbooks/<agent_id>.md`（tmp + `os.replace`），供 skill 等外部程式讀；`render(data)` 產生那份 markdown（標題、角色、職責、指示、限制、權限、回報格式）；`reset(core, agent)` 回到預設。
   - `compose_prompt(core, agent, body)`：回傳 `instructions + "\n\n---\n\n" + body`；instructions 空字串時只回 body。
2. GUI 編輯器：`acw/ui.py` 新增 `PlaybookDialog(QDialog)`，從「⋯ → 角色腳本…」與側欄 agent 標頭旁的小按鈕「角色腳本」開啟，預設選到目前 agent。左側 agent 清單（含動態 instance），右側表單：`role`（單行）、`duties`／`instructions`／`report`（`QPlainTextEdit`）、limits 三個 `QSpinBox`、permissions 三個 `QCheckBox`、按鈕「還原預設」「儲存」「關閉」。儲存呼叫 `playbooks.save`，並重新整理 rail 與側欄。
3. 顯示：rail 卡片第二行（`monitor.py` `ROLES[...][1]` 的位置）與側欄標頭的角色行改用 `playbook['role']`；`ROLE_LABELS` 只當 fallback。
4. `docs/PLAYBOOKS.md`（新）：欄位說明、存放位置、`data_dir/playbooks/<agent>.md` 的用途、各派工路徑怎麼套用（Task B、C）。

**驗收（附執行輸出原文）**：
- `tests/test_playbooks.py`（新，加進 `scripts/run_tests.py` 的清單若需要）：預設可載入；儲存後 `load` 回相同內容且 md 檔存在並含 role；非法值被拒絕；`reset` 回預設；`compose_prompt` 的空／非空兩種。
- UI 測試：開啟 `PlaybookDialog`、改 role、儲存後 rail 卡片文字含新 role。
- `--ui` 全綠。

## Task B：派工流程套用 playbook，請求檔開放給 Codex

**要求**：

1. 請求檔新增欄位：`agent`（缺省 `local`；允許 `local`／`codex` 或任何 provider 為這兩者的 instance id）、`spec`（Codex 用：worktree 內的相對路徑，例如 `docs/HANDOFF-x.md`）、`timeout_seconds`（缺省用 playbook limits）、`use_playbook`（缺省 true）。
2. `RequestDispatcher` 改成多 agent：`_begin` 依 `agent` 選面板與守門：
   - `local`：維持現有守門（PROGRESS.md、dirty、run_budget／max_turns）。
   - `codex`：守門改為 `spec` 存在且在 worktree 內（否則 `no-spec`，加進 `REFUSAL_CODES`）、dirty 規則相同、adapter Connected；不覆寫任何 adapter settings；逾時用 `timeout_seconds`（playbook 預設 7200）。
   - 兩者都先 `compose_prompt`（`use_playbook` 為 true 時）。
   - 同時只跑一個 run（任何 agent）。
3. 核准：Codex run 期間若該面板有 `pending_approval_events`，逾時計時暫停，並寫 timeline `APPROVAL_NEEDED | <request_id> <摘要>`（一次一筆，核准後寫 `APPROVAL_RESOLVED`）。`_on_event` 要多接 `approval` 與 `approval_response` 事件。
4. `MonitorProjection` 參數化：log 檔依 provider（`local`→`hermes.log`，`codex`→`codex.log`），timeline actor 依 provider（`HERMES`／`CODEX`）。
5. 自動協作（`acw/orchestrator.py`）：每個步驟送出前用 `compose_prompt(core, agent, body)` 套該 agent 的 instructions（只加這一層，不改 VERDICT 信封與流程）。
6. 新檔 `scripts/dispatch_request.py`（stdlib only，給 skill 呼叫）：
   ```
   python scripts/dispatch_request.py --agent codex --worktree <abs> --label <label> --spec docs/HANDOFF-x.md [--prompt-file F] [--timeout 7200] [--data-dir D] [--monitor-root R]
   python scripts/dispatch_request.py --agent local --worktree <abs> --label <label> --briefs docs/briefs/x --prompt-file F [--run-budget N] [--max-turns N]
   ```
   行為照 skill 的 `run.sh` 請求模式：檢查 `requests/.dispatcher.json` 心跳（15 秒內且 pid 活著），沒有就印 `workspace: dispatcher not responding` 並 exit 4（**不**回退直接路徑，那是 run.sh 的事）；寫請求檔（tmp + replace）；寫 timeline `RUN_STARTED mode=workspace`；每秒輪詢結果檔，心跳 30 秒沒更新→撤回請求、`RUN_ENDED exit=1 dispatcher-lost`、exit 1；拿到結果→印 JSON 一行與 `hermes_exit=`／`codex_exit=<exit_code>`，寫 `RUN_ENDED`，`complete` exit 0、其他 exit 1、`REFUSAL_CODES` 的 rejected exit 3。`--prompt-file` 缺省時：codex 用「照 <spec> 執行；做完開 PR 不要 push main；回報用規格的回報格式」，local 用現有固定啟動句。
7. `docs/HERMES.md`「請求檔派工」一節改名「請求檔派工（Hermes 與 Codex）」，補 Codex 的欄位、守門、核准與逾時規則、`dispatch_request.py` 用法；`docs/DESIGN-hermes-single-entry.md` §3.2 加一行指向它。

**驗收**：
- `tests/test_hermes_requests.py` 既有測試全過（相容）。
- 新測試 `tests/test_codex_requests.py`：`agent: codex` 請求→用替身 Codex adapter 經 `core.send_message` 送出、prompt 以 playbook instructions 開頭；缺 `spec`→`no-spec`；替身發 `approval` 後逾時計時不前進、timeline 有 `APPROVAL_NEEDED`，`approval_response` 後有 `APPROVAL_RESOLVED`；`message_end` 後結果 `complete`、`codex.log` 有 `[RESULT`；`use_playbook: false` 時 prompt 不含 instructions。
- `tests/test_dispatch_request.py`：用暫存 data_dir 與假心跳檔測 `dispatch_request.py` 的四種結束碼（0／1／3／4）與請求檔內容（含 `agent`、`spec`）。
- orchestrator 測試：送出的提示以該 agent 的 instructions 開頭（`tests/test_orchestrator.py` 加一個）。
- skill 的 `bash ~/.claude/skills/hermes-delegation/scripts/tests/run-offline.sh` 仍 `OFFLINE TEST PASS`（它的假 GUI 不會帶 `agent` 欄位，驗證相容）。

## Task C：resume 前檢查 transcript 是否存在

**要求**：
1. `acw/core.py` 加 `session_available(agent, session_id)`：provider 為 `claude`／`codex` 時回 `desktop_sessions.history_stamp(provider, session_id) is not None`；其他 provider 回 `True`。
2. `resume_session`、`prepare_conversation`、`open_saved_conversation` 在呼叫 adapter 之前先查；不存在時：記事件 `session_missing`（content 用中文：「此對話的紀錄已不存在（<id 前 8 碼>），請開新對話」）、把 task 的 `<agent>_session` 清空（`_map_session(agent, '')` 或等價），**不**啟動 adapter，丟 `ValueError` 給呼叫端。
3. 面板：接到這個錯誤時在輸入欄上方顯示那句中文，送出鈕改成「新對話並傳送」（沿用 `legacy_local_conversation` 的呈現路徑或等價），按下去建新 session 後送出。
4. `docs/HERMES.md` 或 `docs/USER_GUIDE.md` 補一句說明。

**驗收**：
- `tests/test_core.py` 新增：假 transcript 根目錄下有／沒有該 id 的 `.jsonl`，`session_available` 的真／假；綁了不存在的 session 時 `prepare_conversation` 丟 ValueError、task 的 session 被清空、事件 `session_missing` 存在、adapter 的 `resume_session` **沒被呼叫**。
- UI 測試：模擬該錯誤後送出鈕文字為「新對話並傳送」。
- `--ui` 全綠。

---

## 3. 交付總回報格式

每個 Task 一節：改/增哪些檔（路徑:行號）、驗收逐條 PASS/FAIL 附執行輸出原文、未盡事項。最後附 `--ui` 與全套輸出、skill 離線測試輸出、`git log --oneline main..HEAD`、PR 連結。過不了的明講卡在哪，不要寫「大致完成」。

## 4. 不做

- 不動 `acw/adapters/*`、`acw/store.py`、`AI-Collab-Monitor/`、`~/.claude/` 底下任何檔（skill 的接線由審查者做）。
- 不做 Claude 的請求檔派工，不做 playbook 版本控制或分享匯入。
- 不改自動協作的步驟順序與 VERDICT 規則。
- 不要 push main。

## 5. 審查者後續（非 Codex 範圍）

合併後：Claude 把 `deliver-to-codex` skill 改成呼叫 `scripts/dispatch_request.py --agent codex`，`hermes-delegation` 的 `run.sh` 直接路徑在有 `data_dir/playbooks/local.md` 時把它加進提示檔；Ryan 在 GUI 連線一次 Codex 面板並檢視四份預設 playbook。
