"""Bounded automatic collaboration: Claude plans and gives the final review, G8毛 relays and
reviews in between, Codex implements.

A run exists only between an explicit start and its first stop condition. Nothing here
approves a tool request, retries on its own, or survives a restart. The class has no Qt and
no threads: the owner calls `tick()` and supplies `dispatch` to run blocking calls.
"""
from __future__ import annotations

import re
import time

VERDICT = re.compile(r'^\s*\**\s*VERDICT\s*[:：]\s*\**\s*([A-Z_]+)', re.MULTILINE)
MAX_FORWARD_CHARS = 12000
TIMEOUTS = {'claude': 900, 'codex': 1800, 'dot': 1200, 'local': 900}
DOT_POLL_SECONDS = 10

PROMPTS = {
    'plan': ('【自動協作 · 規劃】\n任務：{task}\n\n請只做規劃，不要修改任何檔案。輸出：目標、實作步驟、驗收條件、風險。\n'
             '回覆的第一行必須是 `VERDICT: PLAN_READY`。'),
    'replan': ('【自動協作 · 修訂計畫】\n審查者 G8毛 對你的計畫有以下意見。請據此修訂計畫，不要修改任何檔案。\n'
               '回覆的第一行必須是 `VERDICT: PLAN_READY`。\n\n---\n{body}'),
    'review_plan': ('【自動協作 · 審查計畫並轉交】\n原始任務：{task}\n\n以下是 Claude 的計畫。請審查，需要時可自行到 GitHub 查看程式碼。\n'
                    '若可行，第一行寫 `VERDICT: PASS`，接著寫出給實作者 Codex 的完整交接單（自足，含驗收條件）。\n'
                    '若需修改，第一行寫 `VERDICT: REVISE`，接著列出具體意見。\n\n---\n{body}'),
    'implement': ('【自動協作 · 實作】\n請依以下交接單實作。完成後 commit 並 push 到工作分支（不要 push main）。\n'
                  '回報：改了哪些檔、測試結果、repo URL／分支／commit SHA、未盡事項。\n'
                  '回覆的第一行必須是 `VERDICT: IMPLEMENTED`；無法完成則寫 `VERDICT: BLOCKED` 並說明原因。\n\n---\n{body}'),
    'review_work': ('【自動協作 · 審查實作並轉交】\n原始任務：{task}\n\n以下是 Codex 的實作回報。請依回報中的 repo／分支／commit 自行查看變更並審查。\n'
                    '第一行寫 `VERDICT: PASS` 或 `VERDICT: CONCERNS`，接著寫給最終審查者 Claude 的審查請求，包含你的發現。\n\n---\n{body}'),
    'final_review': ('【自動協作 · 最終審查】\n原始任務：{task}\n\n請審查目前專案資料夾中的實作。只讀，不要修改任何檔案。以下是 G8毛 的審查意見。\n'
                     '通過寫 `VERDICT: APPROVED`；需修改寫 `VERDICT: CHANGES_REQUESTED` 並列出具體修改項。第一行必須是判定。\n\n---\n{body}'),
    'local_review': ('【自動協作 · 本地模型第二意見】\n原始任務：{task}\n\n請檢查目前專案資料夾中的實作。只讀，不要修改任何檔案。以下是實作者的回報。\n'
                     '第一行寫 `VERDICT: PASS` 或 `VERDICT: CONCERNS`，接著簡短列出你的發現。\n\n---\n{body}'),
    'relay_changes': ('【自動協作 · 轉交修改意見】\n以下是 Claude 的最終審查意見。請改寫成給實作者 Codex 的修改交接單（自足，含驗收條件）。\n'
                      '第一行寫 `VERDICT: PASS`。\n\n---\n{body}'),
}
# step -> (agent, {verdict: next step or terminal marker})
STEPS = {
    'plan': ('claude', {'PLAN_READY': 'review_plan'}),
    'replan': ('claude', {'PLAN_READY': 'review_plan'}),
    'review_plan': ('dot', {'PASS': 'implement', 'REVISE': 'replan'}),
    'implement': ('codex', {'IMPLEMENTED': 'review_work', 'BLOCKED': '!Codex 回報無法完成'}),
    'review_work': ('dot', {'PASS': 'final_review', 'CONCERNS': 'final_review'}),
    'final_review': ('claude', {'APPROVED': '=Claude 最終審查通過', 'CHANGES_REQUESTED': 'relay_changes'}),
    'relay_changes': ('dot', {'PASS': 'implement'}),
}
STEP_NAMES = {'local_review': 'Local LLM 第二意見', 'plan': 'Claude 規劃', 'replan': 'Claude 修訂計畫', 'review_plan': 'G8毛 審查計畫', 'implement': 'Codex 實作',
              'review_work': 'G8毛 審查實作', 'final_review': 'Claude 最終審查', 'relay_changes': 'G8毛 轉交修改意見'}
NEW_ROUND = ('replan', 'relay_changes')
LOCAL_ROLES = (None, 'reviewer', 'implementer')
ROLE_NAMES = {'claude': 'Claude', 'dot': 'G8毛', 'codex': 'Codex', 'local': 'Local LLM'}


def parse_verdict(text):
    match = VERDICT.search(text or '')
    return match.group(1) if match else None


class Orchestrator:
    def __init__(self, core, task, dispatch, *, max_rounds=3, has_pending_approval=lambda: False,
                 clock=time.monotonic, timeouts=None, dot_poll_seconds=DOT_POLL_SECONDS, local_role=None):
        if not str(task).strip():
            raise ValueError('請輸入任務')
        if local_role not in LOCAL_ROLES:
            raise ValueError('Local LLM 的角色不正確')
        # Local LLM joins on request: as the implementer instead of Codex, or as an advisory
        # second opinion after the implementation. Its opinion never blocks the run.
        self.local_role = local_role
        self.steps = dict(STEPS)
        self.names = dict(STEP_NAMES)
        self.optional = set()
        if local_role == 'implementer':
            self.steps['implement'] = ('local', STEPS['implement'][1])
            self.names['implement'] = 'Local LLM 實作'
        elif local_role == 'reviewer':
            self.steps['implement'] = ('codex', dict(STEPS['implement'][1], IMPLEMENTED='local_review'))
            self.steps['local_review'] = ('local', {'PASS': 'review_work', 'CONCERNS': 'review_work'})
            self.optional.add('local_review')
        self.agents = tuple(dict.fromkeys(agent for agent, _ in self.steps.values()))
        self._carry = ''
        self.core, self.task, self.dispatch = core, str(task).strip(), dispatch
        self.max_rounds = max(1, min(int(max_rounds), 10))
        self.has_pending_approval, self.clock = has_pending_approval, clock
        self.timeouts = dict(TIMEOUTS, **(timeouts or {}))
        self.dot_poll_seconds = dot_poll_seconds
        self.state, self.reason, self.step, self.round = 'idle', '', '', 1
        self.task_id = None
        self._calling = False   # a dispatched call is in flight
        self._waiting = None    # agent whose reply is awaited
        self._seen, self._deadline, self._next_poll = set(), 0.0, 0.0
        self._paused_at = None  # set while a tool approval is pending

    # --- lifecycle -------------------------------------------------------------------
    def start(self):
        if self.state != 'idle':
            raise RuntimeError('這次執行已經開始過')
        task = self.core.current_task
        if not self.core.current_project or not task:
            raise ValueError('請先選擇專案與任務')
        offline = [agent for agent in self.agents if getattr(self.core.adapters.get(agent), 'state', '') != 'Connected']
        if offline:
            raise RuntimeError('請先連線：' + '、'.join(ROLE_NAMES[agent] for agent in offline))
        self.task_id = task['id']
        self.state = 'running'
        self._note('started', f'自動協作開始 · 回合上限 {self.max_rounds}')
        self._prepare_sessions()

    def stop(self, reason='使用者停止'):
        if self.state not in ('running',):
            return
        waiting = self._waiting
        self._finish('stopped', reason)
        if waiting in ('claude', 'codex', 'local') and getattr(self.core.adapters.get(waiting), 'state', '') == 'Busy':
            self.dispatch(lambda: self.core.stop(waiting), lambda _: None, lambda _: None)

    @property
    def active(self):
        return self.state == 'running'

    def status(self):
        if self.state == 'running':
            wait = '等待核准 · ' if self._paused_at is not None else ''
            return f'自動協作 · 第 {self.round}/{self.max_rounds} 回合 · {wait}{self.names.get(self.step, "準備中")}'
        prefix = {'done': '自動協作完成', 'stopped': '自動協作已停止', 'paused': '自動協作已暫停'}.get(self.state, '自動協作')
        return prefix + (' · ' + self.reason if self.reason else '')

    # --- internals -------------------------------------------------------------------
    def _note(self, kind, content):
        self.core._record('orchestration', 'workspace', task_id=self.task_id, status=kind, content=content,
                          step=self.step, round=self.round)

    def _finish(self, state, reason):
        self.state, self.reason, self._waiting, self._calling = state, reason, None, False
        self._note(state, self.status())

    def _call(self, operation, done):
        self._calling = True
        def succeeded(result):
            if self.state != 'running':
                return
            self._calling = False
            done(result)
        def failed(error):
            if self.state != 'running':
                return
            if self.step in self.optional:
                self._calling = False
                return self._skip_optional('發生錯誤：' + str(error)[:200])
            self._finish('paused', '發生錯誤：' + str(error)[:300])
        self.dispatch(operation, succeeded, failed)

    def _prepare_sessions(self):
        # Starting a run is the explicit action that maps each role to a conversation for this task.
        task = self.core.current_task
        pending = [agent for agent in self.agents if agent != 'dot' and not task.get(agent + '_session')]
        dot = self.core.adapters['dot']
        def step(_=None):
            if pending:
                agent = pending.pop(0)
                self._call(lambda: self.core.create_session(agent), step)
            elif getattr(dot, 'session_id', '') != getattr(dot, 'target', '') or self.core.current_task.get('dot_session') != dot.target:
                self._call(lambda: self.core.resume_session('dot', dot.target), lambda _: self._send('plan', ''))
            else:
                self._send('plan', '')
        step()

    def _messages(self, agent):
        return [m for m in self.core.messages(self.task_id, agent) if m.get('role') == 'assistant' and m.get('status', 'complete') == 'complete']

    def _skip_optional(self, reason):
        # An advisory step that cannot answer is recorded and passed over; it never stops the run.
        self._waiting = None
        self._note('skipped', f'{self.names[self.step]} 未提供意見（{reason}），流程繼續')
        self._send('review_work', self._carry + f'\n\n## Local LLM 第二意見\n未提供（{reason}）。')

    def _send(self, step, body):
        agent = self.steps[step][0]
        self.step = step
        if len(body) > MAX_FORWARD_CHARS:
            body = body[:MAX_FORWARD_CHARS] + f'\n\n…（內容過長已截斷，原長 {len(body)} 字元）'
        text = PROMPTS[step].format(task=self.task, body=body)
        self._note('step', self.names[step])
        def sent(_):
            self._waiting = agent
            self._deadline = self.clock() + self.timeouts[agent]
            self._next_poll = self.clock() + self.dot_poll_seconds
        def send(_=None):
            self._seen = {m['id'] for m in self._messages(agent)}
            self._call(lambda: self.core.send_message(agent, text), sent)
        if agent == 'dot':
            # Read once first so older G8毛 messages (and their verdicts) are never taken for this answer.
            self._call(lambda: self.core.adapters['dot'].refresh_messages(False), send)
        else:
            send()

    def tick(self):
        """Advance at most one step. Safe to call often."""
        if self.state != 'running' or self._calling:
            return
        if self.core.current_task_id != self.task_id:
            return self._finish('paused', '任務已被切換')
        now = self.clock()
        if self.has_pending_approval():
            if self._paused_at is None:
                self._paused_at = now
            return  # a human decides; the clock does not run against the agents meanwhile
        if self._paused_at is not None:
            self._deadline += now - self._paused_at
            self._paused_at = None
        agent = self._waiting
        if agent is None:
            return
        state = getattr(self.core.adapters.get(agent), 'state', '')
        if state in ('Error', 'Offline', 'Disconnected'):
            if self.step in self.optional:
                return self._skip_optional(f'連線狀態：{state}')
            return self._finish('paused', f'{ROLE_NAMES[agent]} 連線狀態：{state}')
        fresh = [m for m in self._messages(agent) if m['id'] not in self._seen]
        reply = '\n\n'.join(str(m['content']) for m in fresh)
        if agent == 'dot':
            # No completion signal exists for G8毛: its answer is complete once it carries a verdict.
            if parse_verdict(reply):
                return self._advance(reply)
            if now >= self._deadline:
                return self._finish('paused', 'G8毛 逾時未回覆')
            if now >= self._next_poll:
                self._next_poll = now + self.dot_poll_seconds
                self._call(lambda: self.core.adapters['dot'].refresh_messages(False), lambda _: None)
            return
        if state != 'Busy' and fresh:
            return self._advance(reply)
        if now >= self._deadline:
            if self.step in self.optional:
                return self._skip_optional('逾時')
            self._finish('paused', f'{ROLE_NAMES[agent]} 逾時未完成')

    def _advance(self, reply):
        self._waiting = None
        verdict, routes = parse_verdict(reply), self.steps[self.step][1]
        if verdict not in routes:
            if self.step in self.optional:
                return self._skip_optional('回覆沒有可用的判定')
            return self._finish('paused', f'{self.names[self.step]} 的回覆沒有可用的判定（收到：{verdict or "無"}）')
        target = routes[verdict]
        if target.startswith('='):
            return self._finish('done', target[1:])
        if target.startswith('!'):
            return self._finish('paused', target[1:])
        if target in NEW_ROUND:
            if self.round >= self.max_rounds:
                return self._finish('done', f'已達回合上限 {self.max_rounds}，最後判定：{verdict}')
            self.round += 1
        body = VERDICT.sub('', reply, count=1).strip()
        if target == 'local_review':
            self._carry = body
        elif self.step == 'local_review':
            body = self._carry + f'\n\n## Local LLM 第二意見（{verdict}）\n' + body
        self._send(target, body)
