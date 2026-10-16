"""Core reliability regressions: deterministic barriers and in-memory adapters only."""
from __future__ import annotations

import hashlib
import json
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from acw.adapters.dot import DotAdapter
from tests.workspace_fixtures import TranscriptFixtureCore as WorkspaceCore
from acw.store import now
from test_core import SyntheticAdapter


class NativeRunner:
    def __init__(self):
        self.items, self.calls = [], []
        self.receipt = 'native-request'

    def __call__(self, operation, **kwargs):
        self.calls.append((operation, kwargs))
        if operation == 'list':
            return [{'id': 'selected-dot', 'display_name': 'G8毛', 'messaging_room_id': 'verified-room'}]
        if operation == 'messages':
            return {'dot_id': 'selected-dot', 'messaging_room_id': 'verified-room',
                    'messages': self.items, 'lines': ['dot: fixture'] * len(self.items)}
        return {'id': self.receipt, 'dot_id': 'selected-dot', 'messaging_room_id': 'verified-room'}

    def page(self, start, count=32):
        self.items = [{'id': f'native-{index}', 'content': {'text': f'body-{index}'},
                       'created_at': f'2026-10-07T12:{index // 60 % 60:02}:{index % 60:02}Z'}
                      for index in range(start, start + count)]


class TurnAdapter(SyntheticAdapter):
    def __init__(self, agent):
        super().__init__(agent)
        self._active_turn = ''

    def send_message(self, content, **kwargs):
        self.sent.append(content)
        self._active_turn = 'turn-' + str(len(self.sent))
        self.state = 'Busy'
        return {'accepted': True}

    def active_operation_id(self):
        return (self.session_id, self._active_turn) if self.state == 'Busy' and self._active_turn else None

    def stop_if_owned(self, expected):
        if expected is None or self.active_operation_id() != expected:
            return False
        return self.stop()

    def stop(self):
        self.calls.append('stop')
        self.state, self._active_turn = 'Connected', ''
        return True


class CoreBackendReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='core-reliability-')
        self.root = Path(self.temp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.adapters = {agent: SyntheticAdapter(agent) for agent in ('claude', 'codex')}
        self.core = WorkspaceCore(self.root / 'data', self.adapters)
        self.core.git_snapshot = lambda *args, **kwargs: {'branch': 'fixture', 'diff': '', 'status': '', 'log': ''}
        self.project = self.core.create_project('Fixture', self.repo)
        self.core.select_project(self.project['id'], sync=False)
        self.task = self.core.create_task('Task A')
        self.other = self.core.create_task('Task B', select=False)
        self.threads, self.releases = [], []
        self.addCleanup(self.cleanup)
        self.addCleanup(patch.stopall)
        patch('subprocess.Popen', side_effect=AssertionError('Real transport is forbidden')).start()
        patch.object(socket.socket, 'connect', side_effect=AssertionError('Network access is forbidden')).start()

    def cleanup(self):
        for release in self.releases:
            release.set()
        for thread in self.threads:
            thread.join(5)
        if not self.core._closed:
            self.core.close()
        self.temp.cleanup()

    def connected(self, agent):
        self.core.connect(agent)
        return self.core.create_session(agent)

    def background(self, operation):
        outcome = {}
        def execute():
            try:
                outcome['result'] = operation()
            except BaseException as exc:
                outcome['error'] = exc
        thread = threading.Thread(target=execute, daemon=True)
        self.threads.append(thread)
        thread.start()
        return thread, outcome

    def barrier_method(self, adapter, method, *, fail=False):
        entered, release = threading.Event(), threading.Event()
        self.releases.append(release)
        original = getattr(adapter, method)
        def blocked(*args, **kwargs):
            entered.set()
            if not release.wait(5):
                raise AssertionError('Fixture barrier was not released')
            if fail:
                adapter.sent.append(args[0])
                raise RuntimeError('accepted transport, receipt lost')
            return original(*args, **kwargs)
        setattr(adapter, method, blocked)
        return entered, release

    def assert_finished(self, thread, outcome):
        thread.join(5)
        self.assertFalse(thread.is_alive(), 'Fixture thread did not finish')
        self.assertNotIn('error', outcome, str(outcome.get('error')))

    def dot(self):
        runner = NativeRunner()
        adapter = DotAdapter(lambda *args, **kwargs: None, runner=runner)
        adapter._require_room_provenance = True
        adapter.configure_target('selected-dot', 'G8毛')
        self.core.set_adapter('dot', adapter)
        self.adapters['dot'] = adapter
        adapter.authorize_manual_action('connect')
        self.core.connect_dot_conversation()
        return adapter, runner

    def contract(self, agent, owner='a' * 32, prompt='bounded fixture prompt'):
        return {'run_id': owner, 'step_sequence': 1, 'correlation_id': owner + ':1:' + 'b' * 32,
                'step': 'implement' if agent == 'codex' else 'review_plan', 'task_id': self.task['id'],
                'project_id': self.project['id'], 'agent': agent,
                'session_id': self.core.current_task.get(agent + '_session'),
                'dot_id': self.adapters[agent].target if agent == 'dot' else '',
                'room_id': self.adapters[agent].native_room_id if agent == 'dot' else '', 'prompt': prompt}

    def owned_send(self, agent='codex', owner='a' * 32):
        contract = self.contract(agent, owner)
        receipt = self.core.send_orchestration_message(agent, contract['prompt'], contract)
        contract.update(local_request_id=receipt['local_message_id'], native_request_id=receipt['native_message_id'])
        return contract

    def test_create_and_resume_reserve_context_until_exact_session_is_mapped(self):
        for method in ('create_session', 'resume_session'):
            with self.subTest(method=method):
                adapter = self.adapters['codex']
                adapter.state = 'Connected'
                entered, release = self.barrier_method(adapter, method)
                operation = (lambda: self.core.create_session('codex')) if method == 'create_session' else (lambda: self.core.resume_session('codex', 'explicit-resumed-session'))
                thread, outcome = self.background(operation)
                self.assertTrue(entered.wait(3))
                with self.assertRaises(RuntimeError): self.core.select_task(self.other['id'])
                with self.assertRaises(RuntimeError): self.core.select_agent_task('codex', self.other['id'])
                with self.assertRaises(RuntimeError): self.core.create_task('Must not be inserted')
                with self.assertRaises(RuntimeError): self.core.create_agent_task('codex', 'Must not be inserted')
                with self.assertRaises(RuntimeError): self.core.close()
                self.assertEqual(self.task['id'], self.core.current_task_id)
                self.assertEqual(2, len(self.core.list_tasks()))
                release.set()
                self.assert_finished(thread, outcome)
                session = self.core.get_task(self.task['id'])['codex_session']
                self.assertEqual(adapter.session_id, session)
                self.assertEqual(self.task['id'], self.core.store.get('sessions', {'agent': 'codex', 'id': session})['task_id'])
                self.assertFalse(self.core.get_task(self.other['id'])['codex_session'])
                self.assertEqual({}, self.core._operations)

    def test_session_operation_reserves_cross_project_bindings(self):
        directory = self.root / 'other-repo'
        directory.mkdir()
        project = self.core.create_project('Other project', directory)
        task = self.core.create_task('Other project task', project['id'], select=False)
        self.adapters['codex'].state = 'Connected'
        entered, release = self.barrier_method(self.adapters['codex'], 'create_session')
        thread, outcome = self.background(lambda: self.core.create_session('codex'))
        self.assertTrue(entered.wait(3))
        with self.assertRaises(RuntimeError): self.core.select_project(project['id'])
        with self.assertRaises(RuntimeError): self.core.select_agent_project('codex', project['id'])
        with self.assertRaises(RuntimeError): self.core.select_agent_task('codex', task['id'])
        release.set()
        self.assert_finished(thread, outcome)
        self.assertEqual(self.project['id'], self.core.current_project_id)
        self.assertEqual(self.task['id'], self.core.current_task_id)
        session = self.core.get_task(self.task['id'])['codex_session']
        mapped = self.core.store.get('sessions', {'agent': 'codex', 'id': session})
        self.assertEqual((self.project['id'], self.task['id']), (mapped['project_id'], mapped['task_id']))
        self.assertFalse(self.core.get_task(task['id'])['codex_session'])

    def test_inflight_send_blocks_same_agent_changes_but_other_agent_is_independent(self):
        self.connected('codex')
        self.connected('claude')
        entered, release = self.barrier_method(self.adapters['codex'], 'send_message')
        thread, outcome = self.background(lambda: self.core.send_message('codex', 'task A request'))
        self.assertTrue(entered.wait(3))
        with self.assertRaises(RuntimeError): self.core.select_task(self.other['id'])
        with self.assertRaises(RuntimeError): self.core.select_agent_task('codex', self.other['id'])
        self.core.select_agent_task('claude', self.other['id'])
        self.assertEqual(self.other['id'], self.core.agent_task('claude')['id'])
        self.assertEqual('sending', self.core.messages(self.task['id'], 'codex')[-1]['status'])
        release.set()
        self.assert_finished(thread, outcome)
        row = self.core.messages(self.task['id'], 'codex')[-1]
        self.assertEqual(('complete', 'task A request'), (row['status'], row['content']))
        self.assertEqual([], self.core.messages(self.other['id'], 'codex'))

    def test_same_agent_concurrent_operation_is_refused_without_second_dispatch(self):
        self.connected('codex')
        entered, release = self.barrier_method(self.adapters['codex'], 'send_message')
        thread, outcome = self.background(lambda: self.core.send_message('codex', 'first'))
        self.assertTrue(entered.wait(3))
        with self.assertRaisesRegex(RuntimeError, 'Another operation'):
            self.core.send_message('codex', 'second')
        release.set()
        self.assert_finished(thread, outcome)
        self.assertEqual(['first'], self.adapters['codex'].sent)

    def test_connecting_and_outstanding_streams_block_selection(self):
        self.adapters['codex'].state = 'Connecting'
        with self.assertRaises(RuntimeError): self.core.select_task(self.other['id'])
        with self.assertRaises(RuntimeError): self.core.select_agent_task('codex', self.other['id'])
        self.adapters['codex'].state = 'Connected'
        self.adapters['codex'].emit('message_start')
        with self.assertRaises(RuntimeError): self.core.select_task(self.other['id'])
        with self.assertRaises(RuntimeError): self.core.select_agent_task('codex', self.other['id'])
        self.adapters['codex'].emit('message_end', content='complete')
        self.core.select_task(self.other['id'])
        self.assertEqual(self.other['id'], self.core.current_task_id)

    def test_old_adapter_emissions_are_inert_after_replacement(self):
        old = self.adapters['codex'].emit
        replacement = SyntheticAdapter('codex')
        self.core.set_adapter('codex', replacement)
        self.core.drain_events()
        old('session', session_id='stale-session')
        old('message_end', content='stale reply')
        old('system', content='stale event')
        self.assertEqual([], self.core.drain_events())
        self.assertFalse(self.core.current_task['codex_session'])
        self.assertEqual([], self.core.messages(self.task['id'], 'codex'))
        replacement.emit('system', content='current adapter')
        self.assertEqual('current adapter', self.core.messages(self.task['id'], 'codex')[-1]['content'])

    def test_post_dispatch_failure_stays_delivery_unknown_and_never_resends(self):
        self.connected('codex')
        entered, release = self.barrier_method(self.adapters['codex'], 'send_message', fail=True)
        thread, outcome = self.background(lambda: self.core.send_message('codex', 'accepted but uncertain'))
        self.assertTrue(entered.wait(3))
        self.assertEqual('sending', self.core.messages(self.task['id'], 'codex')[-1]['status'])
        release.set()
        thread.join(5)
        self.assertIsInstance(outcome.get('error'), RuntimeError)
        self.assertEqual(['accepted but uncertain'], self.adapters['codex'].sent)
        self.assertEqual('delivery_unknown', self.core.messages(self.task['id'], 'codex')[-1]['status'])
        self.core.close()
        replacement = SyntheticAdapter('codex')
        self.core = WorkspaceCore(self.root / 'data', {'codex': replacement})
        self.assertEqual('delivery_unknown', self.core.messages(self.task['id'], 'codex')[-1]['status'])
        self.assertEqual([], replacement.sent)
        self.assertEqual([], replacement.calls)

    def test_pending_sending_stream_and_handoff_recovery_do_not_retry(self):
        session = self.connected('codex')
        for status in ('pending', 'sending'):
            self.core.store.insert('messages', dict(id='recover-' + status, task_id=self.task['id'], agent='codex',
                session_id=session, role='user', content='request-' + status, timestamp=now(), status=status))
        self.adapters['codex'].emit('message_start')
        self.adapters['codex'].emit('message_delta', content='safe partial\n')
        self.adapters['claude'].emit('message_end', content='handoff source')
        source = self.core.messages(self.task['id'], 'claude')[-1]
        handoff = self.core.prepare_handoff(source['id'], 'codex')
        self.core.store.update('handoffs', {'id': handoff['id']}, {'status': 'sending'})
        self.core.close()
        replacement = SyntheticAdapter('codex')
        self.core = WorkspaceCore(self.root / 'data', {'codex': replacement})
        for status in ('pending', 'sending'):
            self.assertEqual('delivery_unknown', self.core.store.get('messages', {'id': 'recover-' + status})['status'])
        partial = next(row for row in self.core.messages(self.task['id'], 'codex') if row['role'] == 'assistant')
        self.assertEqual(('interrupted', 'safe partial\n'), (partial['status'], partial['content']))
        self.assertEqual('delivery_unknown', self.core.store.get('handoffs', {'id': handoff['id']})['status'])
        self.assertEqual([], replacement.calls)
        self.assertEqual([], replacement.sent)

    def test_dot_lost_receipt_root_and_task_sends_remain_uncertain_without_retry(self):
        adapter, runner = self.dot()
        runner.receipt = ''
        adapter.authorize_manual_action('send')
        with self.assertRaisesRegex(RuntimeError, 'uncertain'):
            self.core.send_dot_conversation('root accepted, missing receipt')
        root = self.core.store.query("SELECT * FROM messages WHERE task_id IS NULL AND role='user'")[-1]
        self.assertEqual('delivery_unknown', root['status'])
        adapter.state = 'Connected'
        self.core.resume_session('dot', adapter.target)
        contract = self.contract('dot')
        adapter.grant_run(10, owner=contract['run_id'])
        with self.assertRaisesRegex(RuntimeError, 'uncertain'):
            self.core.send_orchestration_message('dot', contract['prompt'], contract)
        task_row = [row for row in self.core.messages(self.task['id'], 'dot') if row['role'] == 'user'][-1]
        self.assertEqual('delivery_unknown', task_row['status'])
        self.assertEqual(2, sum(op == 'send' for op, _ in runner.calls))
        self.assertEqual(contract['run_id'], task_row['metadata']['orchestration']['run_id'])

    def test_indexed_native_ingestion_is_page_linear_and_unchanged_pages_are_noops(self):
        adapter, runner = self.dot()
        self.assertTrue(self.core.store.native_lookup_index, 'Supported test SQLite must expose indexed JSON lookup')
        metadata = lambda index: json.dumps({'native_id': f'native-{index}', 'native_room_id': 'verified-room',
                                             'native_timestamp': f'2026-10-07T12:{index // 60 % 60:02}:{index % 60:02}Z'})
        records = [(f'root-{i}', None, 'dot', 'selected-dot', 'assistant', f'body-{i}', now(), 'complete', metadata(i))
                   for i in range(10000)]
        with self.core.store.lock:
            self.core.store.db.executemany('INSERT INTO messages(id,task_id,agent,session_id,role,content,timestamp,status,metadata) VALUES (?,?,?,?,?,?,?,?,?)', records)
            self.core.store.db.commit()
        runner.page(9990)
        original = self.core.store._decode
        decoded = []
        def decode(row):
            if 'role' in row.keys(): decoded.append(row['id'])
            return original(row)
        self.core.drain_events()
        with patch.object(self.core.store, '_decode', side_effect=decode):
            adapter.authorize_manual_action('messages')
            self.core.read_dot_conversation()
        self.assertLessEqual(len(decoded), 40, f'One page decoded {len(decoded)} message rows')
        events = self.core.store.query("SELECT id FROM events WHERE type='message_snapshot'")
        self.assertEqual(22, len(events))
        source_refs = {row['id']: row['raw_ref'] for row in self.core.store.query("SELECT id,raw_ref FROM messages WHERE raw_ref!=''")}
        self.core.drain_events()
        adapter.authorize_manual_action('messages')
        self.core.read_dot_conversation()
        self.assertEqual(events, self.core.store.query("SELECT id FROM events WHERE type='message_snapshot'"))
        self.assertEqual(source_refs, {row['id']: row['raw_ref'] for row in self.core.store.query("SELECT id,raw_ref FROM messages WHERE raw_ref!=''")})
        read_events = self.core.drain_events()
        self.assertFalse(any(event['type'] == 'message_snapshot' for event in read_events))
        self.assertLessEqual(len(read_events), 4, 'Only bounded read lifecycle audit records are expected')
        self.assertEqual(10022, self.core.store.query("SELECT COUNT(*) AS n FROM messages WHERE task_id IS NULL AND agent='dot'")[0]['n'])
        self.assertEqual([], self.core.messages(self.task['id'], 'dot'))
        # Older pages are the adversarial case: timestamp ordering must not scan 10k rows per ID.
        steps = [0]
        def progress():
            steps[0] += 100
            return 0
        runner.page(0)
        self.core.store.db.set_progress_handler(progress, 100)
        try:
            adapter.authorize_manual_action('messages')
            self.core.read_dot_conversation()
        finally:
            self.core.store.db.set_progress_handler(None, 0)
        self.assertLess(steps[0], 10000, f'An unchanged 32-message old page used approximately {steps[0]} SQLite VM steps')

    def test_native_index_is_used_and_malformed_legacy_metadata_does_not_break_lookup(self):
        adapter, runner = self.dot()
        self.core.store.insert('messages', dict(id='malformed-legacy', task_id=None, agent='dot', session_id=adapter.target,
            role='assistant', content='legacy body', timestamp=now(), metadata='not valid JSON'))
        runner.page(20, 1)
        adapter.authorize_manual_action('messages')
        self.core.read_dot_conversation()
        row = self.core.store.find_native_message('dot', adapter.target, None, adapter.native_room_id, 'native-20')
        self.assertEqual('body-20', row['content'])
        original_query, lookups = self.core.store.query, []
        def capture_query(sql, params=()):
            if 'FROM messages' in sql and 'json_extract' in sql:
                lookups.append((sql, params))
            return original_query(sql, params)
        with patch.object(self.core.store, 'query', side_effect=capture_query):
            self.core.store.find_native_message('dot', adapter.target, None, adapter.native_room_id, 'native-20')
        self.assertEqual(1, len(lookups))
        sql, params = lookups[0]
        with self.core.store.lock:
            plan = self.core.store.db.execute('EXPLAIN QUERY PLAN ' + sql, params).fetchall()
        self.assertTrue(any('messages_native_scope' in str(item['detail']) for item in plan), str([dict(item) for item in plan]))

    def test_scoped_scan_fallback_retains_correctness_and_is_disclosed(self):
        adapter, runner = self.dot()
        runner.page(25, 1)
        adapter.authorize_manual_action('messages')
        self.core.read_dot_conversation()
        self.core.store.insert('messages', dict(id='legacy-invalid', task_id=None, agent='dot', session_id=adapter.target,
            role='assistant', content='invalid legacy metadata', timestamp=now(), metadata='not JSON'))
        self.core.store.native_lookup_index = False  # Exercise the documented older-SQLite fallback.
        row = self.core.store.find_native_message('dot', adapter.target, None, adapter.native_room_id, 'native-25')
        self.assertEqual('body-25', row['content'])
        self.assertIsNone(self.core.store.find_native_message('dot', adapter.target, None, 'different-room', 'native-25'))
        self.assertEqual('scoped_scan_fallback', self.core.diagnostics()['native_message_lookup'])

    def test_changed_native_message_updates_one_source_losslessly(self):
        adapter, runner = self.dot()
        runner.page(30, 1)
        adapter.authorize_manual_action('messages')
        self.core.read_dot_conversation()
        old = self.core.store.find_native_message('dot', adapter.target, None, adapter.native_room_id, 'native-30')
        body = 'complete replacement\nend byte  \n'
        runner.items[0]['content']['text'] = body
        adapter.authorize_manual_action('messages')
        self.core.read_dot_conversation()
        current = self.core.store.find_native_message('dot', adapter.target, None, adapter.native_room_id, 'native-30')
        self.assertEqual(old['id'], current['id'])
        self.assertEqual(body, current['content'])
        self.assertNotEqual(old['raw_ref'], current['raw_ref'])
        self.assertEqual(1, self.core.store.query("SELECT COUNT(*) AS n FROM messages WHERE task_id IS NULL AND role='assistant'")[0]['n'])

    def test_accepted_dot_evidence_is_exact_task_scoped_idempotent_and_immutable(self):
        adapter, runner = self.dot()
        self.core.resume_session('dot', adapter.target)
        contract = self.contract('dot')
        adapter.grant_run(20, owner=contract['run_id'])
        receipt = self.core.send_orchestration_message('dot', contract['prompt'], contract)
        contract.update(local_request_id=receipt['local_message_id'], native_request_id=receipt['native_message_id'])
        runner.page(40, 1)
        content = 'VERDICT: PASS\nACW_REPLY: ' + contract['correlation_id'] + '\nexact body  \nACW_END: ' + contract['correlation_id']
        runner.items[0]['content']['text'] = content
        snapshot = self.core.read_dot_snapshot_for_run(contract)[0]
        self.assertEqual([], [row for row in self.core.messages(self.task['id'], 'dot') if row['role'] == 'assistant'])
        accepted = self.core.accept_orchestration_reply(contract, snapshot)
        root = self.core.store.find_native_message('dot', adapter.target, None, adapter.native_room_id, snapshot['native_id'])
        self.assertEqual(self.task['id'], accepted['task_id'])
        self.assertEqual(content, accepted['content'])
        self.assertEqual(root['id'], accepted['metadata']['source_root_message_id'])
        self.assertEqual(hashlib.sha256(content.encode()).hexdigest(), accepted['metadata']['content_sha256'])
        self.assertEqual(accepted['id'], self.core.accept_orchestration_reply(contract, snapshot)['id'])
        accepted['content'] = 'caller mutation'
        self.assertEqual(content, self.core.store.get('messages', {'id': accepted['id']})['content'])
        runner.items[0]['content']['text'] = content.replace('exact body', 'changed root body')
        changed = self.core.read_dot_snapshot_for_run(contract)[0]
        with self.assertRaisesRegex(ValueError, 'immutable'):
            self.core.accept_orchestration_reply(contract, changed)
        self.assertEqual(content, self.core.store.get('messages', {'id': accepted['id']})['content'])

    def test_manual_dot_send_invalidates_old_run_read_and_acceptance_ownership(self):
        adapter, runner = self.dot()
        self.core.resume_session('dot', adapter.target)
        contract = self.contract('dot')
        adapter.grant_run(20, owner=contract['run_id'])
        receipt = self.core.send_orchestration_message('dot', contract['prompt'], contract)
        contract.update(local_request_id=receipt['local_message_id'], native_request_id=receipt['native_message_id'])
        runner.page(50, 1)
        snapshot = self.core.read_dot_snapshot_for_run(contract)[0]
        adapter.authorize_manual_action('send')
        self.core.send_dot_conversation('explicit intervening manual send')
        with self.assertRaisesRegex(RuntimeError, 'ownership'):
            self.core.read_dot_snapshot_for_run(contract)
        with self.assertRaisesRegex(RuntimeError, 'ownership'):
            self.core.accept_orchestration_reply(contract, snapshot)
        self.assertEqual([], [row for row in self.core.messages(self.task['id'], 'dot') if row['role'] == 'assistant'])

    def test_handoff_pre_dispatch_failure_is_failed_and_clears_probe(self):
        self.adapters['claude'].emit('message_end', content='handoff source')
        source = self.core.messages(self.task['id'], 'claude')[-1]
        preview = self.core.prepare_handoff(source['id'], 'codex')
        with self.assertRaisesRegex(RuntimeError, 'connect backend'):
            self.core.send_handoff(preview)
        self.assertEqual('failed', self.core.store.get('handoffs', {'id': preview['id']})['status'])
        self.assertEqual([], self.adapters['codex'].sent)
        self.assertEqual([], self.core.messages(self.task['id'], 'codex'))
        self.assertIsNone(getattr(self.core._operation_context, 'dispatch_probe', None))

    def test_empty_task_assistant_cannot_create_metadata_only_handoff(self):
        for content in ('', ' \n\t'):
            with self.subTest(content=content):
                self.adapters['claude'].emit('message_end', content=content)
                source = self.core.messages(self.task['id'], 'claude')[-1]
                with self.assertRaisesRegex(ValueError, 'non-empty|empty|text'):
                    self.core.prepare_handoff(source['id'], 'codex')
        self.assertEqual([], self.core.handoffs(self.task['id']))
        self.assertEqual([], self.adapters['codex'].sent)

    def test_handoff_post_dispatch_failure_is_unknown_and_not_sent(self):
        self.connected('codex')
        self.adapters['claude'].emit('message_end', content='handoff report')
        source = self.core.messages(self.task['id'], 'claude')[-1]
        preview = self.core.prepare_handoff(source['id'], 'codex')
        def fail(content, **kwargs):
            self.adapters['codex'].sent.append(content)
            raise RuntimeError('accepted transport, lost acknowledgement')
        self.adapters['codex'].send_message = fail
        with self.assertRaises(RuntimeError):
            self.core.send_handoff(preview)
        self.assertEqual('delivery_unknown', self.core.store.get('handoffs', {'id': preview['id']})['status'])
        with self.assertRaisesRegex(ValueError, 'already been attempted'):
            self.core.send_handoff(preview)
        self.assertEqual(1, len(self.adapters['codex'].sent))
        self.assertIsNone(getattr(self.core._operation_context, 'dispatch_probe', None))

    def test_handoff_annotation_cannot_race_the_frozen_dispatch(self):
        self.connected('codex')
        self.adapters['claude'].emit('message_end', content='approved source')
        source = self.core.messages(self.task['id'], 'claude')[-1]
        preview = self.core.prepare_handoff(source['id'], 'codex', 'approved initial annotation')
        entered, release, updater_finished = threading.Event(), threading.Event(), threading.Event()
        self.releases.append(release)
        original_get, handoff_reads = self.core.store.get, [0]
        sender_id = [None]
        def captured_get(table, identity):
            result = original_get(table, identity)
            if table == 'handoffs' and identity.get('id') == preview['id'] and threading.get_ident() == sender_id[0]:
                handoff_reads[0] += 1
                if handoff_reads[0] == 2:
                    entered.set()
                    if not release.wait(5): raise AssertionError('Handoff capture barrier was not released')
            return result
        def send():
            sender_id[0] = threading.get_ident()
            return self.core.send_handoff(preview)
        def annotate():
            try:
                return self.core.update_handoff_annotation(preview['id'], 'late annotation')
            finally:
                updater_finished.set()
        with patch.object(self.core.store, 'get', side_effect=captured_get):
            sender, send_outcome = self.background(send)
            self.assertTrue(entered.wait(3))
            updater, update_outcome = self.background(annotate)
            self.assertFalse(updater_finished.wait(.05), 'Annotation must wait for the frozen handoff capture')
            release.set()
            self.assert_finished(sender, send_outcome)
            updater.join(5)
            self.assertFalse(updater.is_alive())
        self.assertIsInstance(update_outcome.get('error'), ValueError)
        record = self.core.store.get('handoffs', {'id': preview['id']})
        self.assertEqual(('sent', 'approved initial annotation'), (record['status'], record['annotation']))
        self.assertIn('approved initial annotation', self.adapters['codex'].sent[-1])
        self.assertNotIn('late annotation', self.adapters['codex'].sent[-1])

    def test_native_lookup_keeps_task_root_and_verified_room_separate(self):
        adapter, runner = self.dot()
        for identity, task, room, body in (('root', None, 'verified-room', 'root body'),
                                            ('task', self.task['id'], 'verified-room', 'task evidence'),
                                            ('other-room', None, 'other-room', 'other room')):
            self.core.store.insert('messages', dict(id=identity, task_id=task, agent='dot', session_id=adapter.target,
                role='assistant', content=body, timestamp=now(), metadata={'native_id': 'same-native', 'native_room_id': room}))
        for task, room, expected in ((None, 'verified-room', 'root'), (self.task['id'], 'verified-room', 'task'), (None, 'other-room', 'other-room')):
            self.assertEqual(expected, self.core.store.find_native_message('dot', adapter.target, task, room, 'same-native')['id'])

    def test_cancellation_requires_exact_owner_local_request_adapter_session_and_turn(self):
        adapter = TurnAdapter('codex')
        self.core.set_adapter('codex', adapter)
        self.adapters['codex'] = adapter
        self.connected('codex')
        contract = self.owned_send()
        for changed in ({'run_id': 'other'}, {'local_request_id': 'other'}, {'session_id': 'other'}):
            self.assertFalse(self.core.stop_orchestration_message('codex', dict(contract, **changed)))
        saved_turn = adapter._active_turn
        adapter._active_turn = 'new-turn'
        self.assertFalse(self.core.stop_orchestration_message('codex', contract))
        adapter._active_turn = saved_turn
        self.assertTrue(self.core.stop_orchestration_message('codex', contract))
        self.assertEqual(1, adapter.calls.count('stop'))
        self.assertFalse(self.core.stop_orchestration_message('codex', contract))

    def test_delayed_cancellation_cannot_stop_new_send_or_replacement(self):
        adapter = TurnAdapter('codex')
        self.core.set_adapter('codex', adapter)
        self.adapters['codex'] = adapter
        self.connected('codex')
        old = self.owned_send()
        adapter.state = 'Connected'
        self.core.send_message('codex', 'new ordinary user send')
        self.assertFalse(self.core.stop_orchestration_message('codex', old))
        self.assertEqual('Busy', adapter.state)
        self.assertNotIn('stop', adapter.calls)
        replacement = TurnAdapter('codex')
        replacement.session_id, replacement.state, replacement._active_turn = adapter.session_id, 'Busy', adapter._active_turn
        self.core.set_adapter('codex', replacement)
        self.assertFalse(self.core.stop_orchestration_message('codex', old))
        self.assertNotIn('stop', replacement.calls)

    def test_close_waits_for_already_started_emitter_then_rejects_late_emissions(self):
        emitter = self.adapters['codex'].emit
        entered, release, closed = threading.Event(), threading.Event(), threading.Event()
        self.releases.append(release)
        original = self.core.store.append_raw
        def append(*args, **kwargs):
            entered.set()
            if not release.wait(5): raise AssertionError('Close barrier not released')
            return original(*args, **kwargs)
        self.core.store.append_raw = append
        worker, outcome = self.background(lambda: emitter('system', content='already started'))
        self.assertTrue(entered.wait(3))
        def close():
            self.core.close()
            closed.set()
        closer, close_outcome = self.background(close)
        self.assertFalse(closed.wait(.05), 'Close must not pass a persistence callback in progress')
        release.set()
        self.assert_finished(worker, outcome)
        self.assert_finished(closer, close_outcome)
        self.assertTrue(closed.is_set())
        self.assertIsNone(emitter('system', content='too late'))

    def test_inflight_adapter_replacement_does_not_turn_acceptance_into_keyerror(self):
        self.connected('codex')
        entered, release = self.barrier_method(self.adapters['codex'], 'send_message')
        thread, outcome = self.background(lambda: self.core.send_message('codex', 'old adapter accepted'))
        self.assertTrue(entered.wait(3))
        replacement = SyntheticAdapter('codex')
        self.core.set_adapter('codex', replacement)
        release.set()
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertNotIn('error', outcome, str(outcome.get('error')))
        self.assertEqual('complete', self.core.messages(self.task['id'], 'codex')[-1]['status'])
        self.assertNotIn('codex', self.core._active_requests)


if __name__ == '__main__':
    unittest.main()
