"""Deterministic run-correlated handoffs. No native backend or authorization bypass."""
from __future__ import annotations

import copy
import unittest
from types import SimpleNamespace

from acw.orchestrator import MAX_FORWARD_CHARS, Orchestrator, _reply_envelope


def envelope(token, verdict='PASS', body='complete handoff'):
    return f'VERDICT: {verdict}\nACW_REPLY: {token}\n{body}\nACW_END: {token}'


class CoreFixture:
    agent_ids = ('claude', 'dot', 'codex', 'local')

    def get_setting(self, key, default=None):
        return default

    @staticmethod
    def provider(agent):
        return agent

    @staticmethod
    def agent_name(agent):
        return {'claude': 'Claude', 'codex': 'Codex', 'dot': 'G8毛', 'local': 'Local LLM'}[agent]

    def __init__(self):
        self.current_task_id, self.current_project_id = 'task-1', 'project-1'
        self.current_task = {'id': self.current_task_id, 'project_id': self.current_project_id,
                             **{a + '_session': a + '-session' for a in ('claude', 'dot', 'codex', 'local')}}
        self.current_project = {'id': self.current_project_id}
        self.selection = {}
        self.logs, self.sent, self.rows, self.accepted, self.stop_requests = [], [], [], [], []
        self.history = {a: [] for a in ('claude', 'dot', 'codex', 'local')}
        self.adapters = {a: SimpleNamespace(state='Connected', session_id=a + '-session') for a in self.history}
        dot = self.adapters['dot']
        dot.target, dot.native_room_id = 'dot-session', 'room-1'
        dot.revokes = []
        dot.revoke_run = lambda *, owner: dot.revokes.append(owner)
        self.missing_receipt = False
        self.read_count = 0

    def agent_task(self, agent):
        return self.selection.get(agent, self.current_task)

    def agent_project(self, agent):
        return {'id': (self.agent_task(agent) or {}).get('project_id')}

    def _record(self, *args, **kwargs):
        self.logs.append((args, kwargs))

    def messages(self, task_id, agent):
        return copy.deepcopy(self.history[agent])

    def send_orchestration_message(self, agent, text, contract):
        self.sent.append((agent, text, dict(contract)))
        native_id = 'request-' + str(len(self.sent)) if agent == 'dot' and not self.missing_receipt else ''
        if native_id:
            self.rows.append(self.row(native_id, 'user', text))
        return {'local_message_id': 'local-' + str(len(self.sent)), 'native_message_id': native_id, 'result': {}}

    def read_dot_snapshot_for_run(self, contract):
        self.read_count += 1
        return copy.deepcopy(self.rows)

    def accept_orchestration_reply(self, contract, snapshot):
        stored = dict(snapshot, task_id=contract['task_id'], run_id=contract['run_id'])
        self.accepted.append(stored)
        return stored

    def create_session(self, agent):
        session = agent + '-new-session'
        self.current_task[agent + '_session'] = session
        self.adapters[agent].session_id = session
        return {'id': session}

    def resume_session(self, agent, session):
        self.current_task[agent + '_session'] = session
        self.adapters[agent].session_id = session
        return {'id': session}

    def stop_orchestration_message(self, agent, contract):
        self.stop_requests.append(dict(contract))
        latest = next((c for a, _, c in reversed(self.sent) if a == agent), {})
        if latest.get('run_id') != contract['run_id'] or latest.get('step_sequence') != contract['step_sequence']:
            return False
        if self.adapters[agent].session_id != contract['session_id'] or self.adapters[agent].state != 'Busy':
            return False
        self.adapters[agent].state = 'Connected'
        return True

    def row(self, native_id, role, content):
        return {'native_id': native_id, 'role': role, 'content': content,
                'native_timestamp': 'irrelevant', 'native_room_id': self.adapters['dot'].native_room_id}


class CorrelationTests(unittest.TestCase):
    def setUp(self):
        self.core = CoreFixture()
        self.clock = [100.0]
        self.pending_approval = False
        self.pending_calls = []
        self.deferred = False
        def dispatch(operation, done, failed):
            if self.deferred:
                self.pending_calls.append((operation, done, failed))
                return
            try:
                result = operation()
            except Exception as exc:
                failed(exc)
            else:
                done(result)
        self.dispatch = dispatch
        self.run = self.new_run()
        self.run.start()

    def new_run(self):
        return Orchestrator(self.core, 'approved implementation', self.dispatch, workflow='relay',
            clock=lambda: self.clock[0], timeouts={a: 20 for a in self.core.history}, dot_poll_seconds=1,
            has_pending_approval=lambda: self.pending_approval)

    def non_dot_reply(self, content, message_id='reply-1', agent=None, status='complete'):
        agent = agent or self.run._waiting
        self.core.history[agent].append({'id': message_id, 'role': 'assistant', 'content': content,
                                          'status': status, 'session_id': self.core.adapters[agent].session_id})

    def to_dot(self):
        self.non_dot_reply(envelope(self.run._contract['correlation_id'], 'PLAN_READY', 'plan'))
        self.run.tick()
        self.assertEqual('review_plan', self.run.step)
        return self.run._contract['correlation_id']

    def poll_dot(self):
        self.clock[0] += 1
        self.run.tick()  # detached page read
        self.run.tick()  # validation and routing

    def expire(self):
        self.clock[0] += 30
        self.run.tick()

    def test_unique_random_challenges_and_monotonic_steps(self):
        token1 = self.run._contract['correlation_id']
        token2 = self.to_dot()
        self.assertRegex(token1, r'^[0-9a-f]{32}:1:[0-9a-f]{32}$')
        self.assertRegex(token2, r'^[0-9a-f]{32}:2:[0-9a-f]{32}$')
        self.assertNotEqual(token1.rsplit(':', 1)[1], token2.rsplit(':', 1)[1])
        self.assertNotEqual(self.run.run_id, self.new_run().run_id)

    def test_unrelated_bare_verdict_never_advances(self):
        token = self.to_dot()
        self.core.rows.append(self.core.row('unrelated', 'assistant', 'VERDICT: PASS\nunrelated ordinary reply'))
        self.poll_dot()
        self.assertEqual('review_plan', self.run.step)
        self.assertEqual([], self.core.accepted)
        self.expire()
        self.assertEqual('paused', self.run.state)
        self.assertEqual(2, len(self.core.sent))

    def test_wrong_step_and_run_and_nonce_never_advance(self):
        token = self.to_dot()
        run_id, seq, nonce = token.split(':')
        for index, wrong in enumerate((f'{run_id}:1:{nonce}', f'{"f" * 32}:{seq}:{nonce}', f'{run_id}:{seq}:{"e" * 32}')):
            self.core.rows.append(self.core.row('wrong-' + str(index), 'assistant', envelope(wrong)))
        self.poll_dot()
        self.assertEqual('review_plan', self.run.step)
        self.assertEqual([], self.core.accepted)
        self.core.rows.append(self.core.row('right', 'assistant', envelope(token)))
        self.poll_dot()
        self.assertEqual('implement', self.run.step)
        self.assertEqual(['right'], [row['native_id'] for row in self.core.accepted])

    def test_old_token_from_previous_round_cannot_route_replanning(self):
        old = self.run._contract['correlation_id']
        token = self.to_dot()
        self.core.rows.append(self.core.row('revision', 'assistant', envelope(token, 'REVISE', 'revise plan')))
        self.poll_dot()
        self.assertEqual('replan', self.run.step)
        current = self.run._contract['correlation_id']
        self.assertNotEqual(old, current)
        self.non_dot_reply(envelope(old, 'PLAN_READY', 'replayed plan'), 'replay')
        self.run.tick()
        self.assertEqual('replan', self.run.step)
        self.non_dot_reply(envelope(current, 'PLAN_READY', 'current plan'), 'current')
        self.run.tick()
        self.assertEqual('review_plan', self.run.step)
        self.assertIn('current plan', self.core.sent[-1][1])
        self.assertNotIn('replayed plan', self.core.sent[-1][1])

    def test_stopped_run_challenge_cannot_resume_a_new_run(self):
        old = self.run._contract['correlation_id']
        self.run.stop()
        self.run = self.new_run()
        self.run.start()
        current = self.run._contract['correlation_id']
        self.non_dot_reply(envelope(old, 'PLAN_READY', 'old stopped reply'), 'old-stop')
        self.run.tick()
        self.assertEqual('plan', self.run.step)
        self.non_dot_reply(envelope(current, 'PLAN_READY', 'new reply'), 'new-reply')
        self.run.tick()
        self.assertEqual('review_plan', self.run.step)
        self.assertIn('new reply', self.core.sent[-1][1])
        self.assertNotIn('old stopped reply', self.core.sent[-1][1])

    def test_partial_same_message_can_finish_in_later_snapshot(self):
        token = self.to_dot()
        partial = self.core.row('partial', 'assistant', f'VERDICT: PASS\nACW_REPLY: {token}\nfirst half')
        self.core.rows.append(partial)
        self.poll_dot()
        self.assertEqual('review_plan', self.run.step)
        partial['content'] = envelope(token, body='first half\nsecond half')
        self.poll_dot()
        self.assertEqual('implement', self.run.step)
        self.assertIn('second half', self.core.sent[-1][1])
        self.assertEqual(1, len(self.core.accepted))

    def test_split_messages_cannot_supply_end_marker(self):
        token = self.to_dot()
        self.core.rows.extend((self.core.row('part-1', 'assistant', f'VERDICT: PASS\nACW_REPLY: {token}\nbody'),
                               self.core.row('part-2', 'assistant', f'ACW_END: {token}')))
        self.poll_dot()
        self.assertEqual('review_plan', self.run.step)
        self.expire()
        self.assertEqual('paused', self.run.state)
        self.assertEqual([], self.core.accepted)

    def test_same_native_id_once_distinct_candidate_ids_are_ambiguous(self):
        token = self.to_dot()
        candidate = self.core.row('same', 'assistant', envelope(token))
        self.core.rows.extend((candidate, dict(candidate)))
        self.poll_dot()
        self.assertEqual('implement', self.run.step)
        self.assertEqual(1, len(self.core.accepted))
        # Another independent run exercises distinct IDs with the same token.
        self.run.stop()
        self.core.rows = []
        self.core.history['claude'] = []
        self.run = self.new_run()
        self.run.start()
        token = self.to_dot()
        self.core.rows.extend((self.core.row('candidate-a', 'assistant', envelope(token)),
                               self.core.row('candidate-b', 'assistant', envelope(token))))
        self.poll_dot()
        self.assertEqual('paused', self.run.state)
        self.assertIn('多個相關回覆', self.run.reason)
        self.assertEqual(1, len(self.core.accepted))

    def test_missing_native_receipt_pauses_without_retry(self):
        self.core.missing_receipt = True
        self.non_dot_reply(envelope(self.run._contract['correlation_id'], 'PLAN_READY', 'plan'))
        self.run.tick()
        self.assertEqual('paused', self.run.state)
        self.assertIn('缺少原生訊息收據', self.run.reason)
        self.assertEqual(2, len(self.core.sent))
        self.run.tick()
        self.assertEqual(2, len(self.core.sent))

    def test_page_requires_receipt_and_exact_prompt(self):
        token = self.to_dot()
        receipt = self.core.rows.pop()
        self.core.rows.append(self.core.row('reply', 'assistant', envelope(token)))
        self.poll_dot()
        self.assertEqual('review_plan', self.run.step)
        self.assertEqual([], self.core.accepted)
        self.core.rows.insert(0, dict(receipt, content=receipt['content'] + 'different'))
        self.poll_dot()
        self.assertEqual('paused', self.run.state)
        self.assertIn('提示內容不符', self.run.reason)

    def test_reply_before_request_and_intervening_human_pause(self):
        token = self.to_dot()
        self.core.rows.insert(0, self.core.row('early', 'assistant', envelope(token)))
        self.poll_dot()
        self.assertEqual('paused', self.run.state)
        self.assertIn('早於', self.run.reason)
        self.assertEqual([], self.core.accepted)

    def test_intervening_human_even_after_reply_pauses_before_routing(self):
        token = self.to_dot()
        self.core.rows.extend((self.core.row('candidate', 'assistant', envelope(token)),
                               self.core.row('human-edit', 'user', 'change the task')))
        self.poll_dot()
        self.assertEqual('paused', self.run.state)
        self.assertIn('人類訊息介入', self.run.reason)
        self.assertEqual([], self.core.accepted)

    def test_missing_acceptance_evidence_cannot_route(self):
        token = self.to_dot()
        self.core.rows.append(self.core.row('valid-reply', 'assistant', envelope(token)))
        self.core.accept_orchestration_reply = lambda contract, candidate: None
        self.poll_dot()
        self.assertEqual('paused', self.run.state)
        self.assertIn('未確認儲存', self.run.reason)
        self.assertEqual(2, len(self.core.sent))

    def test_wrong_native_room_pauses_before_acceptance(self):
        token = self.to_dot()
        self.core.rows.append(dict(self.core.row('wrong-room', 'assistant', envelope(token)), native_room_id='room-other'))
        self.poll_dot()
        self.assertEqual('paused', self.run.state)
        self.assertEqual([], self.core.accepted)

    def test_ten_thousand_unrelated_native_rows_and_repeated_pages_route_once(self):
        token = self.to_dot()
        request = self.core.rows.pop()
        stale = 'c' * 32 + ':1:' + 'd' * 32
        self.core.rows = [self.core.row(f'history-{i}', 'assistant',
            envelope(stale) if i % 2 else 'VERDICT: PASS\nunrelated') for i in range(10000)]
        self.core.rows.append(request)
        self.poll_dot()
        self.poll_dot()
        self.assertEqual('review_plan', self.run.step)
        self.assertEqual(2, len(self.core.sent))
        self.assertEqual([], self.core.accepted)
        body = 'complete\nlast byte  \n'
        candidate = self.core.row('current-complete', 'assistant', envelope(token, body=body))
        self.core.rows.extend((candidate, dict(candidate)))
        self.poll_dot()
        self.run.tick()
        self.assertEqual('implement', self.run.step)
        self.assertEqual(3, len(self.core.sent))
        self.assertEqual(['current-complete'], [row['native_id'] for row in self.core.accepted])
        self.assertIn(body, self.core.sent[-1][1])

    def test_protocol_looking_human_message_cannot_be_a_candidate(self):
        token = self.to_dot()
        self.core.rows.append(self.core.row('human-protocol', 'user', envelope(token)))
        self.poll_dot()
        self.assertEqual('paused', self.run.state)
        self.assertEqual([], self.core.accepted)
        self.assertEqual(2, len(self.core.sent))

    def test_empty_mismatched_duplicate_and_trailing_dot_envelopes_never_accept(self):
        self.run.stop()
        for kind in ('empty', 'mismatched', 'duplicate-end', 'duplicate-reply', 'trailing'):
            with self.subTest(kind=kind):
                self.core = CoreFixture()
                self.run = self.new_run()
                self.run.start()
                token = self.to_dot()
                content = envelope(token)
                if kind == 'empty': content = envelope(token, body='  ')
                elif kind == 'mismatched': content = content.replace('ACW_END: ' + token, 'ACW_END: incorrect')
                elif kind == 'duplicate-end': content += '\nACW_END: ' + token
                elif kind == 'duplicate-reply': content = envelope(token, body='ACW_REPLY: ' + token + '\nbody')
                elif kind == 'trailing': content += '\ntrailing text'
                self.core.rows.append(self.core.row('malformed', 'assistant', content))
                self.poll_dot()
                self.assertEqual('paused', self.run.state)
                self.assertEqual([], self.core.accepted)
                self.assertEqual(2, len(self.core.sent))

    def test_closed_envelope_validation_and_byte_preservation(self):
        token = self.run._contract['correlation_id']
        body = '  leading\nVERDICT: REVISE\nend byte  \n\n'
        self.assertEqual(('PASS', body, None), _reply_envelope(envelope(token, body=body), token))
        for bad, reason in ((envelope(token) + '\ntrailing', 'text after'),
                            (envelope(token).replace('ACW_END:', 'ACW_END: wrong\nACW_END:'), 'duplicate end'),
                            (envelope(token, body=''), 'empty'),
                            (envelope(token).replace('ACW_END: ' + token, 'ACW_END: ' + 'a' * 32 + ':1:' + 'b' * 32), 'mismatched'),
                            (envelope(token, body=f'ACW_REPLY: {token}\nbody'), 'duplicate correlation')):
            with self.subTest(reason=reason):
                self.assertIn(reason, _reply_envelope(bad, token)[2])

    def test_non_dot_completion_requires_closed_envelope_and_not_busy(self):
        token = self.run._contract['correlation_id']
        self.non_dot_reply(envelope(token, 'PLAN_READY', 'plan'))
        self.core.adapters['claude'].state = 'Busy'
        self.run.tick()
        self.assertEqual('plan', self.run.step)
        self.core.adapters['claude'].state = 'Connected'
        self.run.tick()
        self.assertEqual('review_plan', self.run.step)

    def test_non_dot_matching_challenge_from_wrong_session_never_routes(self):
        token = self.run._contract['correlation_id']
        self.non_dot_reply(envelope(token, 'PLAN_READY'))
        self.core.history['claude'][0]['session_id'] = 'another-session'
        self.run.tick()
        self.assertEqual('plan', self.run.step)
        self.expire()
        self.assertEqual('paused', self.run.state)
        self.assertEqual(1, len(self.core.sent))

    def test_non_dot_distinct_matching_messages_pause(self):
        token = self.run._contract['correlation_id']
        self.non_dot_reply(envelope(token, 'PLAN_READY'), 'message-a')
        self.non_dot_reply(envelope(token, 'PLAN_READY'), 'message-b')
        self.run.tick()
        self.assertEqual('paused', self.run.state)
        self.assertEqual(1, len(self.core.sent))

    def test_context_changes_during_call_invalidate_callback(self):
        token = self.to_dot()
        self.deferred = True
        self.run.tick()
        operation, done, failed = self.pending_calls.pop()
        result = operation()
        self.core.current_project_id = 'different-project'
        done(result)
        self.assertEqual('paused', self.run.state)
        self.assertEqual([], self.core.accepted)

    def test_every_binding_is_rechecked_even_while_call_is_in_flight(self):
        for field in ('task', 'agent-task', 'adapter', 'session', 'task-session', 'dot', 'room'):
            with self.subTest(field=field):
                core = CoreFixture()
                run = Orchestrator(core, 'task', self.dispatch, workflow='relay', clock=lambda: self.clock[0])
                run.start()
                if field == 'task': core.current_task_id = 'changed'
                elif field == 'agent-task': core.selection['codex'] = dict(core.current_task, id='changed')
                elif field == 'adapter': core.adapters['claude'] = SimpleNamespace(state='Connected', session_id='claude-session')
                elif field == 'session': core.adapters['codex'].session_id = 'changed'
                elif field == 'task-session': core.current_task['codex_session'] = 'changed'
                elif field == 'dot': core.adapters['dot'].target = 'changed'
                elif field == 'room': core.adapters['dot'].native_room_id = 'changed'
                run._calling = True
                run.tick()
                self.assertEqual('paused', run.state)
                self.assertEqual(1, len(core.sent))

    def test_preparation_allows_only_its_explicit_session_result(self):
        self.run.stop()
        self.core.current_task['claude_session'] = ''
        self.core.adapters['claude'].session_id = ''
        self.deferred = True
        run = self.new_run()
        run.start()
        operation, done, failed = self.pending_calls.pop()
        result = operation()
        run.tick()  # The authorized preparation has changed its two session fields.
        self.assertEqual('running', run.state)
        done(result)
        self.assertEqual('claude-new-session', run._bindings['claude']['session_id'])
        operation, done, failed = self.pending_calls.pop()
        done(operation())
        self.assertEqual('plan', run.step)
        self.assertEqual('claude', run._waiting)

    def test_preparation_result_cannot_adopt_a_different_session(self):
        self.run.stop()
        self.core.current_task['claude_session'] = ''
        self.core.adapters['claude'].session_id = ''
        self.deferred = True
        run = self.new_run()
        run.start()
        operation, done, failed = self.pending_calls.pop()
        result = operation()
        done({'id': 'some-other-session'})
        self.assertEqual('paused', run.state)
        self.assertIn('session 準備未完成', run.reason)

    def test_context_change_before_queued_dispatch_does_no_io(self):
        self.run.stop()
        self.deferred = True
        run = self.new_run()
        run.start()
        operation, done, failed = self.pending_calls.pop()
        before = len(self.core.sent)
        self.core.adapters['codex'].session_id = 'unexpected'
        self.assertIsNone(operation())
        done(None)
        self.assertEqual('paused', run.state)
        self.assertEqual(before, len(self.core.sent))

    def test_request_receipt_role_is_rejected(self):
        token = self.to_dot()
        self.core.rows[0]['role'] = 'assistant'
        self.core.rows.append(self.core.row('valid-reply', 'assistant', envelope(token)))
        self.poll_dot()
        self.assertEqual('paused', self.run.state)
        self.assertEqual([], self.core.accepted)

    def test_page_with_missing_native_identity_is_rejected(self):
        token = self.to_dot()
        self.core.rows.append(dict(self.core.row('valid-reply', 'assistant', envelope(token)), native_id=''))
        self.poll_dot()
        self.assertEqual('paused', self.run.state)
        self.assertEqual([], self.core.accepted)

    def test_partial_non_dot_envelope_updates_same_completed_id(self):
        token = self.run._contract['correlation_id']
        self.non_dot_reply(f'VERDICT: PLAN_READY\nACW_REPLY: {token}\npartial')
        self.run.tick()
        self.assertEqual('plan', self.run.step)
        self.core.history['claude'][0]['content'] = envelope(token, 'PLAN_READY', 'complete')
        self.run.tick()
        self.assertEqual('review_plan', self.run.step)

    def test_legacy_non_dot_bare_verdict_waits_then_requires_review(self):
        self.non_dot_reply('VERDICT: PLAN_READY\nlegacy content')
        self.run.tick()
        self.assertEqual('plan', self.run.step)
        self.expire()
        self.assertEqual('paused', self.run.state)
        self.assertIn('需人工審查', self.run.reason)

    def test_stop_makes_queued_operation_and_callback_inert_restart_is_new_run(self):
        self.run.stop()
        self.deferred = True
        run = self.new_run()
        run.start()
        operation, done, failed = self.pending_calls.pop()
        before = len(self.core.sent)
        run.stop()
        self.assertIsNone(operation())
        done({'local_message_id': 'late', 'native_message_id': ''})
        failed(RuntimeError('late error'))
        self.assertEqual('stopped', run.state)
        self.assertEqual(before, len(self.core.sent))
        self.assertIsNone(run._contract)
        self.assertNotEqual(self.run.run_id, run.run_id)
        self.assertEqual([self.run.run_id, run.run_id], self.core.adapters['dot'].revokes)

    def test_delayed_stop_cannot_cancel_new_run_turn(self):
        self.core.adapters['claude'].state = 'Busy'
        self.deferred = True
        self.run.stop()
        old_stop, done, failed = self.pending_calls.pop()
        self.deferred = False
        self.core.adapters['claude'].state = 'Connected'
        new = self.new_run()
        new.start()
        self.core.adapters['claude'].state = 'Busy'
        self.assertFalse(old_stop())
        self.assertEqual('Busy', self.core.adapters['claude'].state)
        self.assertEqual('running', new.state)
        self.assertEqual(self.run.run_id, self.core.stop_requests[-1]['run_id'])

    def test_never_completing_send_and_preparation_pause_and_invalidate(self):
        self.run.stop()
        for preparation in (False, True):
            with self.subTest(preparation=preparation):
                self.core = CoreFixture()
                if preparation:
                    self.core.current_task['claude_session'] = ''
                    self.core.adapters['claude'].session_id = ''
                self.deferred = True
                self.run = self.new_run()
                self.run.start()
                operation, done, failed = self.pending_calls.pop()
                self.expire()
                self.assertEqual('paused', self.run.state)
                self.assertIn('請求逾時', self.run.reason)
                self.assertIsNone(operation())
                done({'local_message_id': 'late', 'native_message_id': ''})
                self.assertEqual([], self.core.sent)
                self.assertEqual('paused', self.run.state)

    def test_never_completing_dot_read_or_acceptance_is_bounded(self):
        self.run.stop()
        for phase in ('read', 'acceptance'):
            with self.subTest(phase=phase):
                self.core = CoreFixture()
                self.deferred = False
                self.run = self.new_run()
                self.run.start()
                token = self.to_dot()
                self.core.rows.append(self.core.row('valid', 'assistant', envelope(token)))
                if phase == 'acceptance':
                    self.run.tick()  # Read the detached page synchronously.
                self.deferred = True
                self.run.tick()
                operation, done, failed = self.pending_calls.pop()
                self.expire()
                self.assertEqual('paused', self.run.state)
                self.assertIsNone(operation())
                done(None)
                failed(RuntimeError('late'))
                self.assertEqual([], self.core.accepted)
                self.assertEqual(2, len(self.core.sent))

    def test_approval_arriving_during_acceptance_defers_downstream_send(self):
        token = self.to_dot()
        self.core.rows.append(self.core.row('valid', 'assistant', envelope(token)))
        self.run.tick()  # Read page before acceptance is deferred.
        self.deferred = True
        self.run.tick()
        operation, done, failed = self.pending_calls.pop()
        stored = operation()
        self.pending_approval = True
        done(stored)
        self.assertEqual(2, len(self.core.sent))
        self.assertEqual('running', self.run.state)
        self.run.tick()
        self.clock[0] += 1000
        self.run.tick()
        self.assertEqual(2, len(self.core.sent))
        self.pending_approval, self.deferred = False, False
        self.run.tick()
        self.assertEqual('implement', self.run.step)
        self.assertEqual(3, len(self.core.sent))

    def test_approval_arriving_before_queued_send_prevents_io(self):
        self.non_dot_reply(envelope(self.run._contract['correlation_id'], 'PLAN_READY', 'plan'))
        self.deferred = True
        self.run.tick()
        operation, done, failed = self.pending_calls.pop()
        original_token = self.run._contract['correlation_id']
        self.pending_approval = True
        done(operation())
        self.assertEqual(1, len(self.core.sent))
        self.assertIsNone(self.run._waiting)
        self.run.tick()
        self.pending_approval, self.deferred = False, False
        self.run.tick()
        self.assertEqual(2, len(self.core.sent))
        self.assertEqual('dot', self.run._waiting)
        self.assertEqual(original_token, self.run._contract['correlation_id'])

    def test_approval_hold_is_not_added_to_new_step_deadline(self):
        token = self.to_dot()
        self.core.rows.append(self.core.row('valid', 'assistant', envelope(token)))
        self.run.tick()
        self.deferred = True
        self.run.tick()
        operation, done, failed = self.pending_calls.pop()
        stored = operation()
        self.pending_approval = True
        self.run.tick()
        self.clock[0] += 1000
        self.pending_approval, self.deferred = False, False
        done(stored)  # Completion arrives before the first tick after approval clears.
        self.assertEqual('implement', self.run.step)
        self.assertEqual(self.clock[0] + 20, self.run._deadline)
        self.run.tick()
        self.assertEqual(self.clock[0] + 20, self.run._deadline)
        self.clock[0] += 30
        self.run.tick()
        self.assertEqual('paused', self.run.state)

    def test_callback_after_operation_deadline_cannot_route_before_tick(self):
        token = self.to_dot()
        self.core.rows.append(self.core.row('valid', 'assistant', envelope(token)))
        self.run.tick()
        self.deferred = True
        self.run.tick()
        operation, done, failed = self.pending_calls.pop()
        stored = operation()
        self.clock[0] += 30
        done(stored)
        self.assertEqual('paused', self.run.state)
        self.assertEqual(2, len(self.core.sent))

    def test_manual_approval_freezes_inflight_operation_deadline(self):
        token = self.to_dot()
        self.deferred = True
        self.run.tick()
        operation, done, failed = self.pending_calls.pop()
        self.pending_approval = True
        self.run.tick()
        self.clock[0] += 1000
        self.run.tick()
        self.assertEqual('running', self.run.state)
        self.pending_approval = False
        self.run.tick()
        self.assertEqual('running', self.run.state)
        self.clock[0] += 30
        self.run.tick()
        self.assertEqual('paused', self.run.state)
        self.assertIsNone(operation())

    def test_manual_approval_freezes_timeout_and_routing(self):
        token = self.run._contract['correlation_id']
        self.non_dot_reply(envelope(token, 'PLAN_READY'))
        self.pending_approval = True
        self.run.tick()
        self.clock[0] += 1000
        self.run.tick()
        self.assertEqual('plan', self.run.step)
        self.assertEqual('running', self.run.state)
        self.pending_approval = False
        self.run.tick()
        self.assertEqual('review_plan', self.run.step)

    def test_overflow_before_any_io_and_exact_end_bytes_forwarded(self):
        original_sends, original_reads = len(self.core.sent), self.core.read_count
        self.run._send('review_work', 'x' * (MAX_FORWARD_CHARS + 1))
        self.assertEqual('paused', self.run.state)
        self.assertEqual(original_sends, len(self.core.sent))
        self.assertEqual(original_reads, self.core.read_count)
        core = CoreFixture()
        run = Orchestrator(core, 'task', self.dispatch, workflow='relay')
        run.start()
        body = 'x' * (MAX_FORWARD_CHARS - 5) + 'end  '
        run._send('implement', body)
        self.assertEqual('running', run.state)
        self.assertIn(body, core.sent[-1][1])
        self.assertNotIn('完成後 commit 並 push', core.sent[-1][1])
        self.assertIn('明確授權', core.sent[-1][1])


if __name__ == '__main__':
    unittest.main()
