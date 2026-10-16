"""Bounded automatic collaboration: scripted in-memory adapters, real WorkspaceCore, no network."""
from __future__ import annotations

import os
import re
from contextlib import contextmanager
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest
from pathlib import Path

from acw.adapters.dot import DotAdapter
from acw.core import WorkspaceCore
from acw.orchestrator import Orchestrator, parse_verdict
from acw.store import now, uid
from test_ui_refresh import OfflineAdapter

AGENTS = ("claude", "dot", "codex", "local")
HAPPY = {"claude": ["VERDICT: PLAN_READY\n計畫內容 P", "VERDICT: APPROVED\n可以合併"],
         "dot": ["VERDICT: PASS\n交接單 G1", "VERDICT: PASS\n審查請求 G2"],
         "codex": ["VERDICT: IMPLEMENTED\n回報 R"]}


def correlated_reply(reply, prompt):
    """Echo the actual dispatched challenge; fixture scripts cannot guess run tokens."""
    token = re.findall(r'ACW_REPLY: ([0-9a-f]{32}:[1-9][0-9]*:[0-9a-f]{32})', prompt)[-1]
    lines = str(reply).splitlines(keepends=True)
    header_index = next((i for i, line in enumerate(lines) if line.strip()), None)
    if header_index is None:
        return f'ACW_REPLY: {token}\nACW_END: {token}'
    header = ''.join(lines[:header_index + 1]).rstrip('\r\n')
    body = ''.join(lines[header_index + 1:])
    return f'{header}\nACW_REPLY: {token}\n{body}\nACW_END: {token}'


class Scripted(OfflineAdapter):
    """In-memory native Dot pages and completed non-Dot replies, no network."""
    def __init__(self, agent, replies):
        super().__init__(agent)
        self.replies, self.sent, self.core, self.pending, self.fail = list(replies), [], None, False, None
        self.native_room_id = 'fixture-room' if agent == 'dot' else ''
        self.native_rows = []
        self.grants = []

    def grant_run(self, budget, *, owner):
        self.grants.append(('grant', budget, owner))

    def revoke_run(self, *, owner):
        self.grants.append(('revoke', owner))

    def _reply(self):
        if not self.replies:
            return
        content = correlated_reply(self.replies.pop(0), self.sent[-1])
        if self.agent == 'dot':
            self.native_rows.append(dict(native_id=uid('native-'), role='assistant', content=content,
                                         native_timestamp=now(), native_room_id=self.native_room_id))
            return
        task = self.core.agent_task(self.agent)
        self.core.store.insert('messages', dict(id=uid('msg-'), task_id=task['id'], agent=self.agent,
            session_id=task.get(self.agent + '_session') or '', role='assistant', content=content,
            timestamp=now(), status='complete', metadata={}))

    def send_message(self, content, model=None, effort=None, attachments=None, **kwargs):
        if self.fail:
            raise RuntimeError(self.fail)
        self.sent.append(content)
        self.calls.append(('send', content))
        if self.agent == 'dot':
            native_id = uid('request-')
            self.native_rows.append(dict(native_id=native_id, role='user', content=content,
                                         native_timestamp=now(), native_room_id=self.native_room_id))
            self.pending = True
            self.emit('send_ack', native_id=native_id)
            return {'id': native_id}
        self._reply()
        return {'accepted': True}

    def refresh_messages(self, older=False, **kwargs):
        self.calls.append(('read', older))
        if self.pending:
            self.pending = False
            self._reply()
        for row in self.native_rows:
            self.emit('message_snapshot', native_id=row['native_id'], role=row['role'], content=row['content'],
                      native_timestamp=row['native_timestamp'])
        return len(self.native_rows)

    @contextmanager
    def operation_scope(self, *, owner):
        self.operation_owner = owner
        try:
            yield
        finally:
            self.operation_owner = None

    def get_snapshot(self):
        return [dict(row) for row in self.native_rows]


class OrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="acw-auto-")
        self.clock = [1000.0]
        self.approval = [False]

    def tearDown(self):
        if hasattr(self, "core"):
            self.core.close()
        self.temp.cleanup()

    def build(self, script=None, **options):
        if hasattr(self, "core"):
            self.core.close()  # a test may build more than one workspace in the same folder
            del self.core
        options.setdefault('workflow', 'relay')
        script = dict(HAPPY, **(script or {}))
        self.adapters = {agent: Scripted(agent, script.get(agent, [])) for agent in AGENTS}
        self.core = WorkspaceCore(Path(self.temp.name) / "data", self.adapters)
        self.core.git_snapshot = lambda *a, **k: {"branch": "", "dirty": False, "ahead": 0, "behind": 0,
                                                  "status": "", "diff": "", "log": "", "is_git": False, "error": ""}
        (Path(self.temp.name) / "repo").mkdir(exist_ok=True)
        project = self.core.create_project("Auto", Path(self.temp.name) / "repo")
        self.core.select_project(project["id"], sync=False)
        self.core.create_task("auto task")
        for agent in AGENTS:
            self.adapters[agent].core = self.core
            self.adapters[agent].state = "Connected"
        def dispatch(operation, done, failed):
            try:
                result = operation()
            except Exception as exc:
                return failed(str(exc))
            done(result)
        self.run_ = Orchestrator(self.core, "把按鈕改成藍色", dispatch, clock=lambda: self.clock[0],
                                 has_pending_approval=lambda: self.approval[0], dot_poll_seconds=10, **options)
        return self.run_

    def test_each_dispatched_step_starts_with_instance_playbook_instructions(self):
        from acw import playbooks
        run = self.build()
        for agent in AGENTS:
            playbooks.save(self.core, agent, {'instructions': 'Fixture instruction for ' + agent})
        run.start()
        self.advance()
        self.assertEqual('done', run.state)
        for agent in ('claude', 'codex', 'dot'):
            self.assertTrue(self.adapters[agent].sent)
            self.assertTrue(all(prompt.startswith('Fixture instruction for ' + agent + '\n\n---\n\n')
                                for prompt in self.adapters[agent].sent))

    def advance(self, ticks=40, seconds=11):
        for _ in range(ticks):
            if not self.run_.active:
                break
            self.clock[0] += seconds
            self.run_.tick()

    def sends(self):
        return [(agent, len(self.adapters[agent].sent)) for agent in ("claude", "dot", "codex")]

    def test_verdict_parsing_accepts_only_a_line_start_token(self):
        self.assertEqual("PASS", parse_verdict("VERDICT: PASS\nbody"))
        self.assertIsNone(parse_verdict("前言\n**VERDICT：CHANGES_REQUESTED**\n細節"))
        self.assertEqual("CHANGES_REQUESTED", parse_verdict("**VERDICT：CHANGES_REQUESTED**\n細節"))
        self.assertIsNone(parse_verdict("I think the verdict: pass"))
        self.assertIsNone(parse_verdict(""))

    def test_happy_path_routes_each_reply_to_the_next_role_once(self):
        run = self.build()
        run.start()
        self.advance()
        self.assertEqual(("done", "Claude 最終審查通過"), (run.state, run.reason))
        self.assertEqual([("claude", 2), ("dot", 2), ("codex", 1)], self.sends())
        self.assertIn("把按鈕改成藍色", self.adapters["claude"].sent[0])
        self.assertIn("計畫內容 P", self.adapters["dot"].sent[0])
        self.assertIn("交接單 G1", self.adapters["codex"].sent[0])
        self.assertNotIn("VERDICT: PASS", self.adapters["codex"].sent[0].split("---", 1)[1])
        self.assertIn("回報 R", self.adapters["dot"].sent[1])
        self.assertIn("審查請求 G2", self.adapters["claude"].sent[1])
        self.assertEqual(1, run.round)
        self.assertNotIn("approve", [call[0] for adapter in self.adapters.values() for call in adapter.calls])
        self.assertEqual([], self.adapters["local"].calls)

    def test_plan_revision_goes_back_to_claude_and_not_to_codex(self):
        run = self.build({"claude": ["VERDICT: PLAN_READY\nP1", "VERDICT: PLAN_READY\nP2"],
                          "dot": ["VERDICT: REVISE\n缺驗收條件"]})
        run.start()
        self.advance()
        self.assertEqual(2, len(self.adapters["claude"].sent))
        self.assertIn("缺驗收條件", self.adapters["claude"].sent[1])
        self.assertEqual([], self.adapters["codex"].sent)
        self.assertEqual(2, run.round)

    def test_changes_requested_loops_through_g8_until_the_round_limit_then_sends_nothing(self):
        run = self.build({"claude": ["VERDICT: PLAN_READY\nP"] + ["VERDICT: CHANGES_REQUESTED\n再改"] * 5,
                          "dot": ["VERDICT: PASS\nG"] * 12, "codex": ["VERDICT: IMPLEMENTED\nR"] * 5}, max_rounds=2)
        run.start()
        self.advance(200)
        self.assertEqual("paused", run.state)
        self.assertIn("回合上限 2", run.reason)
        self.assertIn("尚未取得最終 APPROVED", run.reason)
        self.assertEqual(2, len(self.adapters["codex"].sent))
        self.assertIn("再改", self.adapters["dot"].sent[2])
        before = self.sends()
        self.advance(20)
        self.assertEqual(before, self.sends())

    def test_reply_without_a_usable_verdict_pauses_instead_of_guessing(self):
        run = self.build({"codex": ["我做完了，沒有寫判定"]})
        run.start()
        self.advance()
        self.assertEqual("paused", run.state)
        self.assertIn("invalid verdict", run.reason)
        self.assertEqual(1, len(self.adapters["dot"].sent))

    def test_blocked_implementation_pauses(self):
        run = self.build({"codex": ["VERDICT: BLOCKED\n缺權限"]})
        run.start()
        self.advance()
        self.assertEqual(("paused", "Codex 回報無法完成"), (run.state, run.reason))

    def test_pending_tool_approval_holds_the_run_and_never_times_out_meanwhile(self):
        run = self.build(timeouts={"claude": 30, "codex": 30, "dot": 30})
        self.approval[0] = True
        run.start()
        self.advance(50, seconds=100)
        self.assertTrue(run.active)
        self.assertIn("等待核准", run.status())
        self.assertEqual([("claude", 1), ("dot", 0), ("codex", 0)], self.sends())
        self.approval[0] = False
        self.advance(seconds=5)
        self.assertEqual("done", run.state)
        self.assertNotIn("approve", [call[0] for adapter in self.adapters.values() for call in adapter.calls])

    def test_stop_ends_the_run_and_nothing_more_is_sent(self):
        run = self.build()
        run.start()
        self.adapters["codex"].state = "Busy"
        run.stop()
        self.assertEqual("stopped", run.state)
        before = self.sends()
        self.advance(20)
        self.assertEqual(before, self.sends())

    def test_g8_timeout_and_adapter_errors_pause_with_the_reason(self):
        run = self.build({"dot": []}, timeouts={"dot": 60})
        run.start()
        self.advance(30)
        self.assertEqual("paused", run.state)
        self.assertIn("G8毛 逾時未回覆", run.reason)
        self.assertLessEqual(sum(call[0] == "read" for call in self.adapters["dot"].calls), 8)
        run = self.build()
        self.adapters["codex"].fail = "backend exploded"
        run.start()
        self.advance()
        self.assertEqual("paused", run.state)
        self.assertIn("backend exploded", run.reason)

    def test_old_g8_messages_with_a_verdict_are_not_mistaken_for_the_answer(self):
        run = self.build({"dot": ["VERDICT: REVISE\n真正的回覆"], "claude": ["VERDICT: PLAN_READY\nP", "VERDICT: PLAN_READY\nP2"]})
        dot = self.adapters['dot']
        dot.native_rows.append(dict(native_id='old-verdict', role='assistant',
            content='VERDICT: PASS\n上一次執行留下的舊訊息', native_timestamp='old', native_room_id=dot.native_room_id))
        run.start()
        self.advance()
        self.assertEqual([], self.adapters["codex"].sent, "The stale PASS must not route work to Codex")
        self.assertIn("真正的回覆", self.adapters["claude"].sent[1])

    def test_start_requires_a_task_and_all_three_roles_connected(self):
        run = self.build()
        self.adapters["dot"].state = "Disconnected"
        with self.assertRaises(RuntimeError):
            run.start()
        self.assertEqual([("claude", 0), ("dot", 0), ("codex", 0)], self.sends())
        with self.assertRaises(ValueError):
            Orchestrator(self.core, "   ", lambda *a: None)

    def test_local_llm_second_opinion_is_attached_to_what_g8_reviews(self):
        run = self.build({"local": ["VERDICT: CONCERNS\n少了測試"]}, local_role="reviewer")
        run.start()
        self.advance()
        self.assertEqual("done", run.state)
        self.assertIn("回報 R", self.adapters["local"].sent[0])
        review = self.adapters["dot"].sent[1]
        self.assertIn("回報 R", review)
        self.assertIn("Hermes 第二意見（CONCERNS）", review)
        self.assertIn("少了測試", review)
        self.assertEqual(1, len(self.adapters["codex"].sent))

    def test_local_llm_second_opinion_never_blocks_the_run(self):
        for problem in ("no verdict", "timeout", "offline", "error"):
            with self.subTest(problem=problem):
                run = self.build({"local": ["沒有判定的回覆"] if problem == "no verdict" else []},
                                 local_role="reviewer", timeouts={"local": 30})
                local = self.adapters["local"]
                if problem == "error":
                    local.fail = "local server down"
                run.start()
                if problem == "offline":
                    for _ in range(10):
                        self.clock[0] += 11
                        run.tick()
                        if run.step == "local_review" and run._waiting == "local":
                            local.state = "Error"
                            break
                self.advance()
                self.assertEqual(("done", "Claude 最終審查通過"), (run.state, run.reason))
                self.assertIn("回報 R", self.adapters["dot"].sent[1])
                self.assertIn("未提供", self.adapters["dot"].sent[1])

    def test_local_llm_as_implementer_replaces_codex(self):
        run = self.build({"local": ["VERDICT: IMPLEMENTED\n本地回報 L"]}, local_role="implementer")
        self.adapters["codex"].state = "Disconnected"
        run.start()
        self.advance()
        self.assertEqual("done", run.state)
        self.assertEqual([], self.adapters["codex"].sent)
        self.assertIn("交接單 G1", self.adapters["local"].sent[0])
        self.assertIn("本地回報 L", self.adapters["dot"].sent[1])
        self.assertIn("Hermes 實作", run.names["implement"])

    def test_local_llm_must_be_connected_when_it_takes_part(self):
        run = self.build(local_role="reviewer")
        self.adapters["local"].state = "Disconnected"
        with self.assertRaises(RuntimeError) as raised:
            run.start()
        self.assertIn("Hermes", str(raised.exception))
        with self.assertRaises(ValueError):
            self.build(local_role="boss")

    def test_switching_task_mid_run_pauses(self):
        run = self.build()
        self.approval[0] = True
        run.start()
        self.core.create_task("another task")
        self.approval[0] = False
        self.advance()
        self.assertEqual(("paused", "任務已被切換"), (run.state, run.reason))


class DotRunGrantTests(unittest.TestCase):
    def adapter(self):
        self.runs = []
        def runner(operation, **kwargs):
            self.runs.append(operation)
            return {"messages": [], "lines": []} if operation == "messages" else {"id": "sent-1"}
        dot = DotAdapter(lambda *a, **k: None, runner=runner)
        dot.target, dot.target_name, dot.state = "fixture-dot", "G8毛", "Connected"
        return dot

    def test_without_run_grant_programmatic_actions_are_still_refused(self):
        dot = self.adapter()
        with self.assertRaises(PermissionError):
            dot.send_message("hi")
        self.assertEqual([], self.runs)

    def test_grant_covers_send_and_read_for_the_selected_dot_until_budget_or_revoke(self):
        dot = self.adapter()
        dot.grant_run(3)
        dot.send_message("one")
        dot.refresh_messages(False)
        dot.send_message("two")
        self.assertEqual(["send", "messages", "send"], self.runs)
        dot.state = "Connected"
        with self.assertRaises(PermissionError):
            dot.send_message("over budget")
        dot = self.adapter()
        dot.grant_run(50)
        dot.revoke_run()
        with self.assertRaises(PermissionError):
            dot.refresh_messages(False)
        self.assertEqual([], self.runs)

    def test_grant_does_not_cover_listing_connecting_or_another_target(self):
        dot = self.adapter()
        dot.grant_run(50)
        with self.assertRaises(PermissionError):
            dot._call("list", "list")
        dot.target = "some-other-dot"
        with self.assertRaises(PermissionError):
            dot.send_message("wrong target")
        self.assertEqual([], self.runs)

    def test_owned_grant_is_not_ambient_and_cannot_be_revoked_by_another_owner(self):
        dot = self.adapter()
        owner, other = 'a' * 32, 'b' * 32
        dot.grant_run(4, owner=owner)
        with self.assertRaises(PermissionError):
            dot.send_message('ambient root cannot borrow a run grant')
        dot.state = 'Connected'
        with self.assertRaises(PermissionError):
            with dot.operation_scope(owner=other):
                dot.send_message('another run cannot borrow it either')
        dot.state = 'Connected'
        dot.revoke_run(owner=other)
        dot.revoke_run()
        with dot.operation_scope(owner=owner):
            dot.send_message('owned send')
            dot.refresh_messages(False)
        self.assertEqual(['send', 'messages'], self.runs)
        dot.revoke_run(owner=owner)
        with self.assertRaises(PermissionError):
            with dot.operation_scope(owner=owner):
                dot.send_message('revoked')



if __name__ == "__main__":
    unittest.main()


class WindowRunTests(unittest.TestCase):
    """The window drives a run: lock, status bar, G8毛 grant lifetime."""
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from test_ui_refresh import OfflineWindow
        self.temp = tempfile.TemporaryDirectory(prefix="acw-auto-ui-")
        self.adapters = {agent: Scripted(agent, HAPPY.get(agent, [])) for agent in AGENTS}
        self.core = WorkspaceCore(Path(self.temp.name) / "data", self.adapters)
        self.core.git_snapshot = lambda *a, **k: {"branch": "", "dirty": False, "ahead": 0, "behind": 0,
                                                  "status": "", "diff": "", "log": "", "is_git": False, "error": ""}
        (Path(self.temp.name) / "repo").mkdir()
        project = self.core.create_project("Auto", Path(self.temp.name) / "repo")
        self.core.select_project(project["id"], sync=False)
        self.core.create_task("auto task")
        self.grants = []
        dot = self.adapters["dot"]
        dot.grant_run = lambda budget, *, owner: self.grants.append(("grant", budget, owner))
        dot.revoke_run = lambda *, owner: self.grants.append(("revoke", owner))
        for agent in ("claude", "dot", "codex"):
            self.adapters[agent].core = self.core
            self.adapters[agent].state = "Connected"
        self.core.desktop_sessions = lambda agent: []
        self.window = OfflineWindow(self.core)

    def tearDown(self):
        self.window.timer.stop()
        self.window.run_timer.stop()
        self.window.close()
        self.core.close()
        self.temp.cleanup()

    def test_nothing_runs_until_started_and_the_bar_is_hidden(self):
        self.window.poll_events()
        self.assertIsNone(self.window.orchestrator)
        self.assertTrue(self.window.run_bar.isHidden())
        self.assertEqual([], [call for adapter in self.adapters.values() for call in adapter.calls if call[0] in ("send", "read")])

    def test_run_locks_context_grants_g8_for_the_run_only_and_reports_the_result(self):
        self.window.run_auto_collab("把按鈕改成藍色", 3, workflow="relay", consented=True)
        self.window.run_timer.stop()
        self.assertEqual(("grant", 400, self.window.orchestrator.run_id), self.grants[0])
        self.assertTrue(self.window.task_combo.isEnabled())
        self.assertFalse(self.window.panels['codex'].project.isEnabled())
        self.assertFalse(self.window.panels['claude'].send_button.isEnabled())
        self.assertFalse(self.window.run_bar.isHidden())
        run = self.window.orchestrator
        ticks = iter(range(10 ** 6))
        base = run.clock()
        run.clock = lambda: base + next(ticks) * 11.0  # each look at the clock is 11 seconds later
        for _ in range(60):
            if not run.active:
                break
            self.window.tick_auto_collab()
        self.window.tick_auto_collab()
        self.assertEqual("done", run.state)
        self.assertIn("自動協作完成", self.window.run_status.text())
        self.assertEqual("revoke", self.grants[-1][0])
        self.assertTrue(self.window.task_combo.isEnabled())
        self.assertEqual([], self.window.reported_errors)

    def test_start_is_refused_with_a_clear_message_when_a_role_is_offline(self):
        self.adapters["codex"].state = "Disconnected"
        self.window.run_auto_collab("任務", 3, workflow="relay", consented=True)
        self.assertIsNone(self.window.orchestrator)
        self.assertIn("Codex", self.window.reported_errors[-1])
        self.assertEqual("revoke", self.grants[-1][0])
        self.assertTrue(self.window.task_combo.isEnabled())
        self.window.reported_errors.clear()

    def test_stop_button_stops_and_unlocks(self):
        self.adapters["claude"].replies = []
        self.window.run_auto_collab("任務", 3, workflow="relay", consented=True)
        self.window.run_timer.stop()
        self.assertTrue(self.window.orchestrator.active)
        self.window.stop_auto_collab()
        self.assertEqual("stopped", self.window.orchestrator.state)
        self.assertTrue(self.window.task_combo.isEnabled())
        self.assertEqual("revoke", self.grants[-1][0])
