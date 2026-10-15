"""Bounded automatic collaboration with a user-selected lead and implementer.
G8毛 can optionally review and relay between them.

A run exists only between an explicit start and its first stop condition. Nothing here
approves a tool request, retries on its own, or survives a restart. The class has no Qt and
no threads: the owner calls `tick()` and supplies `dispatch` to run blocking calls.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re
import secrets
import time
import threading

VERDICT = re.compile(r'(?P<bold>\*\*)?VERDICT[ \t]*[:：][ \t]*(?P<value>[A-Z_]+)(?(bold)\*\*)')
MAX_FORWARD_CHARS = 12000
TIMEOUTS = {'claude': 900, 'codex': 1800, 'dot': 1200, 'local': 900}
DOT_POLL_SECONDS = 10
_NOT_DISPATCHED = object()

PROMPTS = {
    'plan': ('【自動協作 · 規劃】\n任務：{task}\n\n請只做規劃，不要修改任何檔案。輸出：目標、實作步驟、驗收條件、風險。\n'
             '回覆的第一行必須是 `VERDICT: PLAN_READY`。'),
    'replan': ('【自動協作 · 修訂計畫】\n審查者 G8毛 對你的計畫有以下意見。請據此修訂計畫，不要修改任何檔案。\n'
               '回覆的第一行必須是 `VERDICT: PLAN_READY`。\n\n---\n{body}'),
    'review_plan': ('【自動協作 · 審查計畫並轉交】\n原始任務：{task}\n\n以下是 {lead} 的計畫。請審查，需要時可自行到 GitHub 查看程式碼。\n'
                    '若可行，第一行寫 `VERDICT: PASS`，接著寫出給實作者 {implementer} 的完整交接單（自足，含驗收條件）。\n'
                    '若需修改，第一行寫 `VERDICT: REVISE`，接著列出具體意見。\n\n---\n{body}'),
    'implement': ('【自動協作 · 實作】\n請依以下交接單實作。commit、push 或發布需要原始任務明確授權；實作許可本身不包含發布。\n'
                  '回報：改了哪些檔、測試結果、repo URL／分支／commit SHA、未盡事項。\n'
                  '回覆的第一行必須是 `VERDICT: IMPLEMENTED`；無法完成則寫 `VERDICT: BLOCKED` 並說明原因。\n\n---\n{body}'),
    'review_work': ('【自動協作 · 審查實作並轉交】\n原始任務：{task}\n\n以下是 {implementer} 的實作回報。請依回報中的 repo／分支／commit 自行查看變更並審查。\n'
                    '第一行寫 `VERDICT: PASS` 或 `VERDICT: CONCERNS`，接著寫給最終審查者 {lead} 的審查請求，包含你的發現。\n\n---\n{body}'),
    'final_review': ('【自動協作 · 最終審查】\n原始任務：{task}\n\n請審查目前專案資料夾中的實作。只讀，不要修改任何檔案。以下是 G8毛 的審查意見。\n'
                     '通過寫 `VERDICT: APPROVED`；需修改寫 `VERDICT: CHANGES_REQUESTED` 並列出具體修改項。第一行必須是判定。\n\n---\n{body}'),
    'local_review': ('【自動協作 · Hermes 第二意見】\n原始任務：{task}\n\n請檢查目前專案資料夾中的實作。只讀，不要修改任何檔案。以下是實作者的回報。\n'
                     '第一行寫 `VERDICT: PASS` 或 `VERDICT: CONCERNS`，接著簡短列出你的發現。\n\n---\n{body}'),
    'relay_changes': ('【自動協作 · 轉交修改意見】\n以下是 {lead} 的最終審查意見。請改寫成給實作者 {implementer} 的修改交接單（自足，含驗收條件）。\n'
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
STEP_NAMES = {'local_review': 'Hermes 第二意見', 'plan': 'Claude 規劃', 'replan': 'Claude 修訂計畫', 'review_plan': 'G8毛 審查計畫', 'implement': 'Codex 實作',
              'review_work': 'G8毛 審查實作', 'final_review': 'Claude 最終審查', 'relay_changes': 'G8毛 轉交修改意見'}
NEW_ROUND = ('replan', 'relay_changes')
LOCAL_ROLES = (None, 'reviewer', 'implementer')
ROLE_NAMES = {'claude': 'Claude', 'dot': 'G8毛', 'codex': 'Codex', 'local': 'Hermes'}


@dataclass(frozen=True)
class RunLimits:
    max_rounds: int = 3
    max_steps: int = 24
    max_active_seconds: int = 3600

    def __post_init__(self):
        for name, upper in (('max_rounds', 10), ('max_steps', 100), ('max_active_seconds', 86400)):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= upper:
                raise ValueError(f'{name} must be an integer between 1 and {upper}')


def _verdict_parts(text):
    """Only the first non-empty line can be the control header, never quoted body text."""
    lines = (text or '').splitlines(keepends=True)
    for index, line in enumerate(lines):
        header = line.strip()
        if not header:
            continue
        match = VERDICT.fullmatch(header)
        if not match:
            return None, ''
        return match.group('value'), ''.join(lines[index + 1:]).strip()
    return None, ''


def parse_verdict(text):
    return _verdict_parts(text)[0]



CORRELATION = re.compile(r'[0-9a-f]{32}:[1-9][0-9]*:[0-9a-f]{32}')
MARKER = re.compile(r'ACW_(REPLY|END)[ \t]*:[ \t]*(.*)')


def _reply_envelope(text, correlation_id):
    """Parse a single, closed application envelope without altering forwarded bytes.

    This does not authenticate an author or establish native backend completion.
    The one line ending separating the body from ACW_END is framing, not body.
    """
    if not isinstance(correlation_id, str) or not CORRELATION.fullmatch(correlation_id):
        return None, '', 'unmatched'
    lines = str(text or '').splitlines(keepends=True)
    nonempty = [i for i, line in enumerate(lines) if line.strip()]
    if len(nonempty) < 2:
        return None, '', 'incomplete'
    verdict = parse_verdict(lines[nonempty[0]])
    reply_index = nonempty[1]
    reply_marker = MARKER.fullmatch(lines[reply_index].strip())
    if not reply_marker or reply_marker.group(1) != 'REPLY' or reply_marker.group(2) != correlation_id:
        return verdict, '', 'unmatched'
    markers = [(i, MARKER.fullmatch(line.strip())) for i, line in enumerate(lines)]
    markers = [(i, marker) for i, marker in markers if marker]
    if len([marker for _, marker in markers if marker.group(1) == 'REPLY']) != 1:
        return verdict, '', 'duplicate correlation markers'
    ends = [(i, marker) for i, marker in markers if marker.group(1) == 'END']
    if not ends:
        return verdict, '', 'incomplete'
    if len(ends) != 1:
        return verdict, '', 'duplicate end markers'
    end_index, end_marker = ends[0]
    if end_marker.group(2) != correlation_id:
        return verdict, '', 'mismatched end marker'
    if end_index != nonempty[-1] or end_index <= reply_index:
        return verdict, '', 'text after end marker'
    if not verdict:
        return None, '', 'invalid verdict'
    body = ''.join(lines[reply_index + 1:end_index])
    if body.endswith('\r\n'):
        body = body[:-2]
    elif body.endswith(('\n', '\r')):
        body = body[:-1]
    if not body.strip():
        return verdict, '', 'empty forwarded body'
    return verdict, body, None


class Orchestrator:
    def __init__(self, core, task, dispatch, *, max_rounds=3, has_pending_approval=lambda: False,
                 clock=time.monotonic, timeouts=None, dot_poll_seconds=DOT_POLL_SECONDS, local_role=None,
                 workflow='direct', max_steps=24, max_active_seconds=3600, lead='claude', implementer=None):
        if not str(task).strip():
            raise ValueError('請輸入任務')
        if local_role not in LOCAL_ROLES:
            raise ValueError('Hermes 的角色不正確')
        if workflow not in ('direct', 'relay'):
            raise ValueError('協作流程不正確')
        if lead not in core.agent_ids or core.provider(lead) not in ('claude', 'codex', 'local'):
            raise ValueError('請選擇可派工的 Agent')
        self.role_names = {agent: core.agent_name(agent) for agent in core.agent_ids}
        self._lead = lead
        counterpart = implementer or ('codex' if core.provider(lead) == 'claude' else 'claude')
        if counterpart not in core.agent_ids or core.provider(counterpart) not in ('claude', 'codex', 'local'):
            raise ValueError('請選擇可實作的 Agent')
        self._implementer = 'local' if local_role == 'implementer' else counterpart
        if self._implementer == lead or (local_role == 'reviewer' and 'local' in (lead, self._implementer)):
            raise ValueError('同一次協作的派工、實作與第二意見需使用不同 Agent instance')
        self.workflow = workflow
        self.local_role = local_role
        self.steps = dict(STEPS)
        self.names = dict(STEP_NAMES)
        self.prompts = dict(PROMPTS)
        if workflow == 'direct':
            self.steps = {
                'plan': ('claude', {'PLAN_READY': 'implement'}),
                'implement': ('codex', {'IMPLEMENTED': 'final_review', 'BLOCKED': '!Codex 回報無法完成'}),
                'final_review': ('claude', {'APPROVED': '=Claude 最終審查通過', 'CHANGES_REQUESTED': 'implement'}),
            }
            self.names['plan'] = 'Claude 派工'
            self.prompts['plan'] += '\n請直接寫成給實作者的完整交接單，包含範圍、限制、驗收條件與必要測試。'
            self.prompts['final_review'] = PROMPTS['final_review'].replace('G8毛 的審查意見', '實作者的回報與可選第二意見')
        self.review_target = 'final_review' if workflow == 'direct' else 'review_work'
        self.optional = set()
        if local_role == 'implementer':
            self.steps['implement'] = ('local', dict(self.steps['implement'][1], BLOCKED='!Hermes 回報無法完成'))
            self.names['implement'] = 'Hermes 實作'
        elif local_role == 'reviewer':
            self.steps['implement'] = ('codex', dict(self.steps['implement'][1], IMPLEMENTED='local_review'))
            self.steps['local_review'] = ('local', {'PASS': self.review_target, 'CONCERNS': self.review_target})
            self.optional.add('local_review')
        # Roles belong to this run, never to a backend's permanent capability set.
        assignments = {'claude': self.lead, 'codex': counterpart, 'local': 'local', 'dot': 'dot'}
        self.steps = {step: (assignments[agent], dict(routes)) for step, (agent, routes) in self.steps.items()}
        self.steps['implement'][1]['BLOCKED'] = '!' + self.role_names[self.implementer] + ' 回報無法完成'
        self.steps['final_review'][1]['APPROVED'] = '=' + self.role_names[self.lead] + ' 最終審查通過'
        self.names.update(plan=self.role_names[self.lead] + (' 派工' if workflow == 'direct' else ' 規劃'),
                          replan=self.role_names[self.lead] + ' 修訂計畫',
                          implement=self.role_names[self.implementer] + ' 實作',
                          final_review=self.role_names[self.lead] + ' 最終審查')
        self.agents = tuple(dict.fromkeys(agent for agent, _ in self.steps.values()))
        self._carry = ''
        self.core, self.task, self.dispatch = core, str(task).strip(), dispatch
        self.limits = RunLimits(max_rounds, max_steps, max_active_seconds)
        self.has_pending_approval, self.clock = has_pending_approval, clock
        self.timeouts = dict(TIMEOUTS, **(timeouts or {}))
        for agent in self.agents:
            self.timeouts.setdefault(agent, self.timeouts[core.provider(agent)])
        self.dot_poll_seconds = dot_poll_seconds
        self.state, self.reason, self.step, self.round = 'idle', '', '', 1
        self.run_id = secrets.token_hex(16)
        self._cancel_event = threading.Event()
        self.step_sequence = 0
        self.task_id = self.project_id = None
        self._calling, self._waiting = False, None
        self._seen, self._deadline, self._next_poll = set(), 0.0, 0.0
        self._paused_at = None
        self._generation = 0
        self._bindings = {}
        self._contract = None
        self._dot_snapshot = None
        self._reply_problem = ''
        self._preparing_agent = None
        self._call_deadline = 0.0
        self._deferred_dispatch = None
        self._frozen_task_text = self.task
        self._started_at = self._ended_at = None
        self._held_seconds = 0.0

    @property
    def lead(self):
        return self._lead

    @property
    def implementer(self):
        return self._implementer

    @property
    def max_rounds(self):
        return self.limits.max_rounds

    def snapshot(self):
        """Read-only local view; no adapter calls or clock/approval state mutation."""
        now = self._ended_at if self._ended_at is not None else self.clock()
        held = self._held_seconds + (max(0, now - self._paused_at) if self._paused_at is not None else 0)
        elapsed = max(0, now - self._started_at - held) if self._started_at is not None else 0
        return dict(state=self.state, reason=self.reason, task=self._frozen_task_text,
                    task_id=self.task_id, project_id=self.project_id, run_id=self.run_id,
                    workflow=self.workflow, agents=self.agents, step=self.step,
                    lead=self.lead, implementer=self.implementer,
                    stage=self.names.get(self.step, '準備中'), agent=self.steps.get(self.step, ('',))[0],
                    round=self.round, max_rounds=self.max_rounds, steps=self.step_sequence,
                    max_steps=self.limits.max_steps, elapsed_seconds=int(elapsed),
                    remaining_seconds=max(0, int(self.limits.max_active_seconds - elapsed)),
                    max_active_seconds=self.limits.max_active_seconds,
                    waiting_approval=self._paused_at is not None,
                    stages=tuple((key, self.names[key]) for key in self.steps if key not in ('replan', 'relay_changes')))

    def _check_run_budget(self):
        self._budget_now()
        if self.snapshot()['elapsed_seconds'] >= self.limits.max_active_seconds:
            self._finish('paused', '已達整次執行的有效時間上限；未重送，請檢查目前角色的執行結果')
            return False
        return True

    def start(self):
        if self.state != 'idle':
            raise RuntimeError('這次執行已經開始過')
        task, project = self.core.agent_task(self.lead), self.core.agent_project(self.lead)
        if not project or not task:
            raise ValueError('請先為主導 Agent 選擇 Project 並開啟對話')
        missing = [agent for agent in self.agents if not self.core.agent_task(agent) or not self.core.agent_project(agent)]
        if missing:
            raise ValueError('請先為參與 Agent 選擇 Project 並開啟對話：' + '、'.join(self.role_names[a] for a in missing))
        offline = [agent for agent in self.agents if getattr(self.core.adapters.get(agent), 'state', '') != 'Connected']
        if offline:
            raise RuntimeError('請先連線：' + '、'.join(self.role_names[a] for a in offline))
        dot = self.core.adapters.get('dot')
        if 'dot' in self.agents and (not getattr(dot, 'target', '') or not getattr(dot, 'native_room_id', '')):
            raise RuntimeError('G8毛 缺少已驗證的 Dot／對話識別，請先連線')
        self.task_id, self.project_id = task['id'], project['id']
        self._legacy_global_scope = any(a not in getattr(self.core, '_agent_selections', {}) for a in self.agents)
        self._bindings = {a: self._binding(a) for a in self.agents}
        self.state = 'running'
        self._started_at = self.clock()
        self._note('started', f'自動協作開始 · {self.role_names[self.lead]} 主導 / {self.role_names[self.implementer]} 實作 · '
                   f'{self.workflow} · 回合上限 {self.max_rounds} · '
                   f'步數上限 {self.limits.max_steps} · 有效時間上限 {self.limits.max_active_seconds} 秒')
        self._prepare_sessions()

    def stop(self, reason='使用者停止'):
        if self.state != 'running':
            return
        waiting, contract = self._waiting, dict(self._contract or {})
        bound = self._bindings.get(waiting, {}).get('adapter')
        self._finish('stopped', reason)
        if waiting in self.agents and self.core.provider(waiting) != 'dot' and bound is self.core.adapters.get(waiting) and getattr(bound, 'state', '') == 'Busy':
            # Core atomically rejects delayed cancellation after a new send or replacement.
            self.dispatch(lambda: self.core.stop_orchestration_message(waiting, contract),
                          lambda _: None, lambda _: None)

    @property
    def active(self):
        return self.state == 'running'

    def status(self):
        if self.state == 'running':
            wait = '等待核准 · ' if self._paused_at is not None else ''
            return f'自動協作 · 第 {self.round}/{self.max_rounds} 回合 · {wait}{self.names.get(self.step, "準備中")}'
        prefix = {'done': '自動協作完成', 'stopped': '自動協作已停止', 'paused': '自動協作已暫停'}.get(self.state, '自動協作')
        return prefix + (' · ' + self.reason if self.reason else '')

    def _binding(self, agent):
        adapter = self.core.adapters.get(agent)
        task = self.core.agent_task(agent) or {}
        project = self.core.agent_project(agent) or {}
        return {'adapter': adapter, 'task_id': task.get('id'), 'project_id': project.get('id'),
                'task_session': task.get(agent + '_session') or '',
                'session_id': getattr(adapter, 'session_id', '') or '',
                'dot_id': getattr(adapter, 'target', '') if agent == 'dot' else '',
                'room_id': getattr(adapter, 'native_room_id', '') if agent == 'dot' else ''}

    def _context_reason(self, allow_session_agent=None):
        if self.task != self._frozen_task_text:
            return '執行任務內容已被變更'
        if getattr(self, '_legacy_global_scope', False):
            if self.core.current_task_id != self.task_id: return '任務已被切換'
            if self.core.current_project_id != self.project_id: return '專案已被切換'
        for agent, frozen in self._bindings.items():
            current = self._binding(agent)
            for key, value in frozen.items():
                if agent == allow_session_agent and key in ('task_session', 'session_id'):
                    continue
                changed = current[key] is not value if key == 'adapter' else current[key] != value
                if changed:
                    return f'{self.role_names[agent]} 的專案、任務、session 或對話綁定已變更'
        return ''

    def _check_context(self, allow_session_agent=None):
        reason = self._context_reason(allow_session_agent)
        if reason:
            self._finish('paused', reason)
            return False
        return True

    def _note(self, kind, content):
        self.core._record('orchestration', 'workspace', task_id=self.task_id, status=kind, content=content,
                          step=self.step, round=self.round, run_id=self.run_id, step_sequence=self.step_sequence,
                          workflow=self.workflow, max_rounds=self.max_rounds, max_steps=self.limits.max_steps,
                          max_active_seconds=self.limits.max_active_seconds, lead=self.lead, implementer=self.implementer)

    def _finish(self, state, reason):
        self._ended_at = self.clock()
        self._cancel_event.set()  # Also blocks already-entered Core/adapter preparation.
        self._generation += 1  # Queued operations and callbacks from this run are now inert.
        self.state, self.reason, self._waiting, self._calling = state, reason, None, False
        self._contract, self._dot_snapshot = None, None
        self._preparing_agent = None
        self._call_deadline = 0.0
        self._deferred_dispatch = None
        dot = self._bindings.get('dot', {}).get('adapter')
        revoke = getattr(dot, 'revoke_run', None)
        if revoke:
            try:
                revoke(owner=self.run_id)
            except Exception as exc:
                self._note('grant_revoke_error', str(exc)[:200])
        self._note(state, self.status())

    def _resume_clock(self, now):
        if self._paused_at is not None:
            held = now - self._paused_at
            self._held_seconds += held
            self._deadline += held
            if self._call_deadline:
                self._call_deadline += held
            self._paused_at = None

    def _budget_now(self):
        now = self.clock()
        if self.has_pending_approval():
            if self._paused_at is None:
                self._paused_at = now
            # New budgets created during a human hold begin when the hold ends.
            return self._paused_at
        self._resume_clock(now)
        return now

    def _expire_call(self):
        self._generation += 1
        self._calling = False
        self._call_deadline = 0.0
        self._preparing_agent = None
        if self.step in self.optional:
            return self._skip_optional('請求逾時；結果尚未確認，未重送')
        return self._finish('paused', self.names.get(self.step, 'Session 準備') + ' 請求逾時；結果尚未確認，未重送')

    def _call(self, operation, done, *, allow_session_agent=None, expected_session=None):
        if self.state != 'running' or not self._check_context():
            return
        if not self._check_run_budget():
            return
        self._generation += 1
        generation = self._generation
        self._calling = True
        self._preparing_agent = allow_session_agent
        agent = allow_session_agent or self.steps.get(self.step, ('claude',))[0]
        self._call_deadline = self._budget_now() + self.timeouts[agent]
        if self._waiting is not None:
            self._call_deadline = min(self._call_deadline, self._deadline)
        settled = False
        def guarded_operation():
            if self.state != 'running' or generation != self._generation:
                return None
            if not self._check_context():
                return None
            if not self._check_run_budget():
                return None
            if self._budget_now() >= self._call_deadline:
                self._expire_call()
                return None
            return operation()
        def succeeded(result):
            nonlocal settled
            if settled or self.state != 'running' or generation != self._generation:
                return
            settled = True
            if not self._check_run_budget():
                return
            if self._budget_now() >= self._call_deadline:
                return self._expire_call()
            self._calling = False
            self._call_deadline = 0.0
            if not self._check_context(allow_session_agent):
                return
            if allow_session_agent:
                current = self._binding(allow_session_agent)
                returned = result.get('id', result.get('session_id', '')) if isinstance(result, dict) else result
                expected = expected_session or returned
                if not isinstance(expected, str) or not expected or current['task_session'] != expected or current['session_id'] != expected:
                    return self._finish('paused', f'{self.role_names[allow_session_agent]} session 準備未完成')
                self._bindings[allow_session_agent] = current
            self._preparing_agent = None
            done(result)
        def failed(error):
            nonlocal settled
            if settled or self.state != 'running' or generation != self._generation:
                return
            settled = True
            if self._budget_now() >= self._call_deadline:
                return self._expire_call()
            self._calling = False
            self._call_deadline = 0.0
            self._preparing_agent = None
            if not self._check_context(allow_session_agent):
                return
            if self.step in self.optional:
                return self._skip_optional('發生錯誤：' + str(error)[:200])
            self._finish('paused', '發生錯誤：' + str(error)[:300])
        try:
            self.dispatch(guarded_operation, succeeded, failed)
        except Exception as exc:
            failed(exc)

    def _prepare_sessions(self):
        pending = list(self.agents)
        def step(_=None):
            if not self._check_context():
                return
            if not pending:
                return self._send('plan', '')
            agent = pending.pop(0)
            binding = self._bindings[agent]
            expected = binding['dot_id'] if agent == 'dot' else binding['task_session']
            if not expected:
                return self._call(lambda: self.core.create_session(agent), step, allow_session_agent=agent)
            if binding['session_id'] != expected or binding['task_session'] != expected:
                return self._call(lambda: self.core.resume_session(agent, expected), step, allow_session_agent=agent, expected_session=expected)
            step()
        step()

    def _messages(self, agent):
        session_id = self._bindings.get(agent, {}).get('session_id')
        return [m for m in self.core.messages(self._bindings[agent]['task_id'], agent) if m.get('role') == 'assistant'
                and m.get('status', 'complete') == 'complete' and m.get('session_id', '') == session_id]

    def _skip_optional(self, reason):
        if self.state != 'running' or not self._check_context():
            return
        self._waiting = None
        self._note('skipped', f'{self.names[self.step]} 未提供意見（{reason}），流程繼續')
        self._send(self.review_target, self._carry + f'\n\n## Hermes 第二意見\n未提供（{reason}）。')

    def _assert_dispatch_allowed(self, contract):
        """RAM-only late dispatch gate; it grants no authorization and performs no I/O."""
        if self._cancel_event.is_set() or self.state != 'running' or self._contract is not contract:
            raise RuntimeError('Run stopped or changed before native dispatch; request was not sent')
        reason = self._context_reason()
        if reason:
            raise RuntimeError(reason + '；未傳送')
        if self.snapshot()['elapsed_seconds'] >= self.limits.max_active_seconds:
            raise RuntimeError('Run time budget expired; request was not sent')
        if contract['step_sequence'] > 1 and self.has_pending_approval():
            raise RuntimeError('Pending human approval blocks native dispatch; request was not sent')
        # A human hold is excluded from the operation's budget, including before its next tick.
        now = self._paused_at if self._paused_at is not None else self.clock()
        if self._call_deadline and now >= self._call_deadline:
            raise RuntimeError('Run dispatch deadline expired; request was not sent')

    def _send(self, step, body):
        self.step = step
        # Check before constructing a prompt, reading, sending, or accepting any reply.
        if len(body) > MAX_FORWARD_CHARS:
            return self._finish('paused',
                f'{self.names[step]} 的交接內容超過上限（{len(body)}/{MAX_FORWARD_CHARS} 字元）；'
                '未截斷或傳送，請查看原始訊息並重新整理完整交接')
        if self.state != 'running' or not self._check_context():
            return
        if not self._check_run_budget():
            return
        if self.step_sequence >= self.limits.max_steps:
            return self._finish('paused', f'已達步數上限 {self.limits.max_steps}，尚未取得最終 APPROVED')
        if self.step_sequence and self.has_pending_approval():
            self._generation += 1
            self._waiting, self._contract, self._dot_snapshot = None, None, None
            self._deferred_dispatch = lambda: self._send(step, body)
            return
        agent = self.steps[step][0]
        self.step_sequence += 1
        correlation_id = f'{self.run_id}:{self.step_sequence}:{secrets.token_hex(16)}'
        text = self.prompts[step].format(task=self._frozen_task_text, body=body,
                                         lead=self.role_names[self.lead], implementer=self.role_names[self.implementer])
        text += ('\n\n【單一訊息回覆格式】第一個非空行使用上面的 VERDICT 判定；'
                 f'第二個非空行必須原樣寫 ACW_REPLY: {correlation_id}。'
                 '\n接著寫完整且非空的交接內容，最後一個非空行必須原樣寫 '
                 f'ACW_END: {correlation_id}。不得分成多則訊息，不得在結尾標記後加文字。'
                 '\n這些標記只界定應用程式交接內容完整性，不代表原生完成訊號或作者身分驗證。')
        binding = self._bindings[agent]
        contract = {'run_id': self.run_id, 'step_sequence': self.step_sequence, 'correlation_id': correlation_id,
                    'step': step, 'task_id': binding['task_id'], 'project_id': binding['project_id'], 'agent': agent,
                    'session_id': binding['session_id'], 'dot_id': binding['dot_id'], 'room_id': binding['room_id'],
                    'prompt': text, '_cancel_event': self._cancel_event}
        contract['_dispatch_guard'] = lambda: self._assert_dispatch_allowed(contract)
        self._contract = contract
        self._dot_snapshot, self._reply_problem = None, ''
        self._seen = {m['id'] for m in self._messages(agent)} if agent != 'dot' else set()
        self._note('step', self.names[step])
        def sent(receipt):
            if receipt is _NOT_DISPATCHED:
                self._deferred_dispatch = submit
                return
            if not isinstance(receipt, dict) or not isinstance(receipt.get('local_message_id'), str) or not receipt['local_message_id']:
                return self._finish('paused', '傳送接受狀態不確定：缺少本地訊息識別；未重送')
            contract['local_request_id'] = receipt['local_message_id']
            contract['native_request_id'] = receipt.get('native_message_id') or ''
            if agent == 'dot' and (not isinstance(contract['native_request_id'], str) or not contract['native_request_id']):
                return self._finish('paused', 'G8毛 傳送接受狀態不確定：缺少原生訊息收據；未重送')
            self._waiting = agent
            self._deadline = self._budget_now() + self.timeouts[agent]
            self._next_poll = self.clock()
        def operation():
            if contract['step_sequence'] > 1 and self.has_pending_approval():
                return _NOT_DISPATCHED  # No external send occurred; defer this exact request.
            return self.core.send_orchestration_message(agent, text, contract)
        def submit():
            self._call(operation, sent)
        submit()

    @staticmethod
    def _unique_rows(rows, key):
        if not isinstance(rows, (list, tuple)):
            return None
        unique = {}
        for row in rows:
            if not isinstance(row, dict):
                return None
            identity = row.get(key)
            if not isinstance(identity, str) or not identity:
                return None
            if identity in unique and unique[identity] != row:
                return None
            unique.setdefault(identity, row)
        return list(unique.values())

    def _candidate(self, rows, key):
        token = self._contract['correlation_id']
        candidates = []
        for row in rows:
            lines = [line.strip() for line in str(row.get('content', '')).splitlines() if line.strip()]
            # A partial envelope may grow in this same native message on the next read.
            if len(lines) >= 2 and lines[1] == 'ACW_REPLY: ' + token:
                candidates.append(row)
        candidates = self._unique_rows(candidates, key)
        if candidates is None or len(candidates) > 1:
            self._finish('paused', '同一步驟收到多個相關回覆，無法唯一確認交接；請人工審查')
            return None
        return candidates[0] if candidates else None

    def _process_dot_snapshot(self):
        rows = self._dot_snapshot
        if rows is None:
            return
        rows = self._unique_rows(rows, 'native_id')
        if rows is None:
            return self._finish('paused', 'G8毛 原生訊息頁缺少有效識別或同一識別含衝突內容；請人工審查')
        contract = self._contract
        if any(row.get('native_room_id') != contract['room_id'] for row in rows):
            return self._finish('paused', 'G8毛 回覆的原生對話識別不符')
        receipt_index = next((i for i, row in enumerate(rows) if row.get('native_id') == contract['native_request_id']), None)
        if receipt_index is None:
            self._reply_problem = '同一頁尚未顯示已接受的原生請求收據'
            return
        request = rows[receipt_index]
        if request.get('role') != 'user' or request.get('content') != contract['prompt']:
            return self._finish('paused', 'G8毛 原生請求收據的角色或提示內容不符')
        if any(row.get('role') == 'user' for row in rows[receipt_index + 1:]):
            return self._finish('paused', 'G8毛 請求後有人類訊息介入；請人工審查後重新開始')
        assistants = [row for row in rows if row.get('role') == 'assistant']
        candidate = self._candidate(assistants, 'native_id')
        if self.state != 'running' or candidate is None:
            return
        if rows.index(candidate) <= receipt_index:
            return self._finish('paused', 'G8毛 相關回覆早於已接受的請求收據；未轉交')
        verdict, body, problem = _reply_envelope(candidate.get('content'), contract['correlation_id'])
        if problem:
            self._reply_problem = problem
            if problem != 'incomplete':
                self._finish('paused', 'G8毛 交接封套無效：' + problem)
            return
        if not self._check_context():
            return
        # Only a validated single native root message is copied into this task's history.
        def accepted(stored):
            if (not isinstance(stored, Mapping) or stored.get('task_id') != contract['task_id']
                    or stored.get('role') != 'assistant' or stored.get('content') != candidate['content']):
                return self._finish('paused', 'G8毛 未確認儲存精確的任務交接證據；未轉交')
            self._advance(candidate['content'])
        self._call(lambda: self.core.accept_orchestration_reply(contract, candidate), accepted)

    def tick(self):
        """Advance at most one step; late callbacks and switched bindings cannot route work."""
        if self.state != 'running':
            return
        if not self._check_context(self._preparing_agent if self._calling else None):
            return
        now = self.clock()
        if self.has_pending_approval():
            if self._paused_at is None:
                self._paused_at = now
            return
        self._resume_clock(now)
        if not self._check_run_budget():
            return
        if self._calling:
            if now >= self._call_deadline:
                self._expire_call()
            return
        if self._deferred_dispatch is not None:
            pending, self._deferred_dispatch = self._deferred_dispatch, None
            pending()
            return
        agent = self._waiting
        if agent is None:
            return
        state = getattr(self.core.adapters.get(agent), 'state', '')
        if state in ('Error', 'Offline', 'Disconnected'):
            if self.step in self.optional:
                return self._skip_optional(f'連線狀態：{state}')
            return self._finish('paused', f'{self.role_names[agent]} 連線狀態：{state}')
        if agent == 'dot':
            previous_sequence = self.step_sequence
            self._process_dot_snapshot()
            if self.state != 'running' or self._calling or self.step_sequence != previous_sequence:
                return
            if now >= self._deadline:
                detail = '：' + self._reply_problem if self._reply_problem else ''
                return self._finish('paused', 'G8毛 逾時未回覆完整相關交接' + detail)
            if now >= self._next_poll:
                self._next_poll = now + self.dot_poll_seconds
                contract = self._contract
                self._call(lambda: self.core.read_dot_snapshot_for_run(contract),
                           lambda rows: setattr(self, '_dot_snapshot', rows))
            return
        fresh = [m for m in self._messages(agent) if m['id'] not in self._seen]
        if state != 'Busy':
            candidate = self._candidate(fresh, 'id')
            if self.state != 'running':
                return
            if candidate:
                verdict, body, problem = _reply_envelope(candidate.get('content'), self._contract['correlation_id'])
                if not problem:
                    return self._advance(candidate['content'])
                self._reply_problem = problem
                if problem != 'incomplete':
                    if self.step in self.optional:
                        return self._skip_optional('交接封套無效：' + problem)
                    return self._finish('paused', self.names[self.step] + ' 交接封套無效：' + problem)
            elif fresh and any(parse_verdict(m.get('content')) and 'ACW_REPLY:' not in m.get('content', '') for m in fresh):
                # Legacy replies remain visible but cannot drive automatic transitions.
                self._reply_problem = '舊格式回覆缺少相關性／結尾標記，需人工審查'
        if now >= self._deadline:
            if self.step in self.optional:
                return self._skip_optional('逾時或未提供完整相關交接')
            detail = '：' + self._reply_problem if self._reply_problem else ''
            self._finish('paused', f'{self.role_names[agent]} 逾時未完成相關交接' + detail)

    def _advance(self, reply):
        if self.state != 'running' or not self._check_context():
            return
        verdict, body, problem = _reply_envelope(reply, self._contract['correlation_id'])
        if problem:
            return self._finish('paused', '交接封套無效：' + problem)
        routes = self.steps[self.step][1]
        if verdict not in routes:
            if self.step in self.optional:
                return self._skip_optional('回覆沒有可用的判定')
            return self._finish('paused', f'{self.names[self.step]} 的回覆沒有可用的判定（收到：{verdict or "無"}）')
        self._waiting = None
        target = routes[verdict]
        if target.startswith('='):
            return self._finish('done', target[1:])
        if target.startswith('!'):
            return self._finish('paused', target[1:])
        if target in NEW_ROUND or (self.step == 'final_review' and target == 'implement'):
            if self.round >= self.max_rounds:
                return self._finish('paused', f'已達回合上限 {self.max_rounds}，尚未取得最終 APPROVED；最後判定：{verdict}')
            self.round += 1
        if target == 'local_review':
            self._carry = body
        elif self.step == 'local_review':
            body = self._carry + f'\n\n## Hermes 第二意見（{verdict}）\n' + body
        self._send(target, body)
