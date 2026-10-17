# 返工規格 01 — PR #9（codex/playbooks-dispatch）

> 對象：Codex。承接 `docs/HANDOFF-playbooks-dispatch.md`，**在同一個 branch `codex/playbooks-dispatch` 與同一個 worktree `../AI-Collab-Workspace-playbooks` 上繼續**，新增 commit 推到 PR #9，不要開新 PR、不要 rebase。不變量與不做清單沿用原規格。不要啟動 `run.py`。

審查者（Claude）獨立驗收的結論：Task A、B 達標；Task C 有一個會擋住正常使用的缺陷，另有幾個中低問題。下面依嚴重度排序，**R1、R2 必修**，R3–R6 一併處理。

---

## R1（嚴重）新建對話的第一則訊息被「紀錄已不存在」擋掉

**證據**：`acw/core.py:232-234`

```python
if session_id:
    self._require_available_session(agent,session_id)
    if getattr(adapter,'session_id','')!=session_id: self.resume_session(agent,session_id)
```

檢查放在「adapter 已持有該 session」的判斷之前。新建的 Claude／Codex session 在第一則訊息送出前本機沒有 transcript，所以：按「新對話」→ 直接打字送出 → `prepare_conversation(fresh=False)` → ValueError「此對話的紀錄已不存在」，而且綁定被清空。審查者用真實 `WorkspaceCore` 加 UUID 替身 adapter 重現，`docs/HERMES.md:124` 的描述也與實際不符。

**修法（照做）**：
1. 把檢查限定在**真的要 resume** 的時候：`prepare_conversation`／`open_saved_conversation`／`resume_session` 只在 `getattr(adapter,'session_id','') != session_id`（也就是 adapter 目前沒持有這個 session，需要 `--resume`／`thread/resume`）時才呼叫 `_require_available_session`。adapter 已持有的 session 一律放行。
2. 另外加一個豁免：`core.create_session(agent)` 建出的 session id 記進 `self._fresh_sessions[agent] = session_id`（或等價）；同一個 core 存活期間，對這個 id 不做 transcript 檢查（它的 transcript 會在第一則回覆後才出現）。重啟 GUI 後才恢復檢查，那時若仍沒有 transcript，代表第一則訊息從未送出，標為失效是對的。
3. `docs/HERMES.md` 那段改成與實作一致。

**驗收**：`tests/test_core.py` 新增「真實 Core + 替身 adapter + 空 transcript 根目錄：`prepare_conversation(fresh=True)` 後立刻 `prepare_conversation(fresh=False)` 不丟例外、綁定仍在、`resume_session` 沒被呼叫」；另一個測試「重建 core 後同一個 id 仍無 transcript → 丟 ValueError 並清綁定」。**這兩個測試不得使用 `tests/workspace_fixtures.py` 把 `session_available` 固定為 True 的 fixture**。

## R2（中，會弄丟資料）在「角色」欄位按 Enter 會觸發「還原預設」

**證據**：`acw/ui.py:215` 的「還原預設」是對話框裡第一個 `QPushButton`，`autoDefault` 為 true，成為預設鈕；role 欄位送 Return 就執行還原並覆寫 md。

**修法**：`PlaybookDialog` 裡所有按鈕 `setAutoDefault(False)`、`setDefault(False)`；「還原預設」改為先 `QMessageBox.question` 確認（預設 No）。順手：切換 agent 時若有未儲存修改，問「要先儲存嗎？」（是／否／取消），不要無聲丟掉。

**驗收**：UI 測試：對 role 欄位 `QTest.keyClick(..., Qt.Key_Return)` 後 role 未變、md 未被改寫；切換 agent 前有修改時 `QMessageBox.question` 被呼叫（patch）。

## R3（低）playbook 設定損壞會讓整個 UI 刷新與派工連帶失敗

**證據**：`playbooks.load` 對壞資料 `raise`（`acw/playbooks.py:62-63`），而 `ui.py:2901`、`monitor.py:29`、`orchestrator.py:529`、`requests.py:365` 都沒有 fallback。

**修法**：`load` 遇到無效資料時回 provider 預設，並 `logging.getLogger('acw.playbooks').warning(...)` 一次；`save` 的順序改成先 `set_setting` 再寫 md。

**驗收**：測試：`set_setting('playbook.claude', {'role': 'x'*99})` 後 `load` 回預設且不丟例外；`compose_prompt` 正常。

## R4（低）`scripts/dispatch_request.py` 參數驗證與路徑

**修法**：
- `--agent codex` 缺 `--spec`、`--agent local` 缺 `--briefs` 時 `parser.error`（exit 2），不要送出含 `None` 的請求。
- `/c/...` 形式的 worktree 在 Windows 上自動轉成 `C:\...`（偵測 `^/[a-zA-Z]/`）。
- 「label 已存在」的結束碼改成 2（參數問題），不要跟 `REFUSAL_CODES` 的 3 混用；訊息說明可改 label。

**驗收**：`tests/test_dispatch_request.py` 各加一個案例。

## R5（低）limits 欄位哪些有效要說清楚

`run_budget`／`max_turns` 只在 Hermes 請求沒自帶值時當預設，`timeout_seconds` 只對 Codex 生效。在 `PlaybookDialog` 的 limits 區加一行說明文字，`docs/PLAYBOOKS.md` 的 limits 列同步寫清楚。並讓 local 請求在沒帶 `run_budget`／`max_turns` 時真的用 playbook 的值（`requests.py:366` 目前傳 `None`）。

**驗收**：`tests/test_hermes_requests.py` 加一個：請求不帶 `run_budget` 時，adapter 收到的覆寫值等於 playbook limits。

## R6（資訊，不必改程式）

- 核准計時：Codex 在伺服端自行清掉的核准不會發事件；目前 adapter 不會發 `approval_cancelled`，風險低，寫進 `docs/HERMES.md` 的已知限制即可。
- 直接路徑的 run.sh 尚未套 playbook，由審查者接線，不在本 PR。

---

## 回報格式

每項 R 一節：改了哪些檔（路徑:行號）、驗收 PASS/FAIL 附執行輸出原文。最後附 `python scripts/run_tests.py --ui` 與全套輸出、`git log --oneline main..HEAD`。
