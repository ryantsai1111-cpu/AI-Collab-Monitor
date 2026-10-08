"""Real adapter cancellation and late-dispatch contracts with fixture stdio only."""
from __future__ import annotations

import io
import json
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from acw.adapters.base import Capabilities
from acw.adapters.claude import ClaudeAdapter
from acw.adapters.codex import CodexAdapter
from acw.core import WorkspaceCore
from acw.orchestrator import Orchestrator
from test_core import SyntheticAdapter


class FixtureStdin:
    def __init__(self, callback):
        self.callback, self.closed, self.partial, self.packets = callback, False, '', []

    def write(self, value):
        self.partial += value

    def flush(self):
        packet = json.loads(self.partial)
        self.partial = ''
        self.packets.append(packet)
        self.callback(packet)


class FixtureProcess:
    def __init__(self, callback):
        self.stdin = FixtureStdin(callback)
        self.stdout, self.stderr = [], []

    def poll(self):
        return None


class ControlledEvent:
    def __init__(self):
        self.flag, self.entered, self.release = threading.Event(), threading.Event(), threading.Event()

    def is_set(self): return self.flag.is_set()
    def set(self): self.flag.set()
    def clear(self): self.flag.clear()
    def wait(self, timeout):
        self.entered.set()
        if not self.release.wait(5): raise AssertionError('Lifecycle wait barrier was not released')
        return self.flag.is_set()


class AdapterOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.threads, self.releases = [], []
        self.events = []
        self.addCleanup(self.cleanup_threads)
        self.addCleanup(patch.stopall)
        patch('subprocess.Popen', side_effect=AssertionError('Real transport is forbidden')).start()
        patch.object(socket.socket, 'connect', side_effect=AssertionError('Network is forbidden')).start()

    def cleanup_threads(self):
        for release in self.releases: release.set()
        for thread in self.threads: thread.join(5)

    def background(self, operation):
        result = {}
        def run():
            try: result['value'] = operation()
            except BaseException as exc: result['error'] = exc
        thread = threading.Thread(target=run, daemon=True)
        self.threads.append(thread)
        thread.start()
        return thread, result

    def finish(self, thread, result):
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertNotIn('error', result, str(result.get('error')))

    def codex(self):
        adapter = CodexAdapter(lambda kind, **data: self.events.append((kind, data)))
        sequence = [0]
        def respond(packet):
            method = packet.get('method')
            if method == 'turn/start':
                sequence[0] += 1
                result = {'turn': {'id': f'turn-{sequence[0]}'}}
            else:
                result = {}
            adapter._handle_message({'id': packet['id'], 'result': result})
        adapter._process = FixtureProcess(respond)
        adapter.state, adapter.session_id, adapter._session_ready = 'Connected', 'owned-thread', True
        adapter._permission_state = {'sandbox': {'type': 'readOnly'}}
        adapter.capabilities = Capabilities(supports_cancel=True)
        return adapter

    def claude(self):
        adapter = ClaudeAdapter(lambda kind, **data: self.events.append((kind, data)))
        adapter.state, adapter.session_id = 'Connected', '11111111-2222-4333-8444-555555555555'
        def respond(packet):
            if packet.get('type') == 'control_request':
                adapter._handle({'type': 'control_response', 'response': {
                    'request_id': packet['request_id'], 'subtype': 'success', 'response': {}}}, process=adapter._process)
        adapter._process = FixtureProcess(respond)
        adapter.capabilities = Capabilities(supports_cancel=True)
        return adapter

    def started(self, adapter, turn):
        adapter._handle_message({'method': 'turn/started', 'params': {'threadId': adapter.session_id, 'turn': {'id': turn}}})

    def completed(self, adapter, turn):
        adapter._handle_message({'method': 'turn/completed', 'params': {
            'threadId': adapter.session_id, 'turn': {'id': turn, 'status': 'completed'}}})

    def test_codex_token_binds_actual_send_receipt_and_native_turn(self):
        adapter = self.codex()
        turn = adapter.send_message('first')
        token = adapter.active_operation_id()
        self.assertIsInstance(token, tuple)
        self.started(adapter, turn)
        self.assertTrue(adapter.stop_if_owned(token))
        interrupt = adapter._process.stdin.packets[-1]
        self.assertEqual(('turn/interrupt', {'threadId': 'owned-thread', 'turnId': turn}), (interrupt['method'], interrupt['params']))

    def test_codex_unsolicited_replacement_before_getter_cannot_be_owned(self):
        adapter = self.codex()
        self.assertEqual('turn-1', adapter.send_message('accepted first'))
        self.started(adapter, 'replacement-B')
        self.assertIsNone(adapter.active_operation_id())
        self.assertFalse(adapter.stop_if_owned(None))
        self.assertEqual(['turn/start'], [p['method'] for p in adapter._process.stdin.packets])

    def test_codex_rechecks_exact_turn_after_lifecycle_wait(self):
        adapter = self.codex()
        adapter.send_message('accepted first')
        token = adapter.active_operation_id()
        wait = ControlledEvent()
        self.releases.append(wait.release)
        adapter._turn_started = wait
        thread, result = self.background(lambda: adapter.stop_if_owned(token))
        self.assertTrue(wait.entered.wait(3))
        self.started(adapter, 'replacement-B')
        wait.release.set()
        self.finish(thread, result)
        self.assertFalse(result['value'])
        self.assertEqual('replacement-B', adapter._turn_id)
        self.assertEqual(['turn/start'], [p['method'] for p in adapter._process.stdin.packets])

    def test_codex_new_send_old_token_and_process_replacement_are_rejected(self):
        adapter = self.codex()
        first = adapter.send_message('first')
        old = adapter.active_operation_id()
        self.started(adapter, first)
        self.completed(adapter, first)
        second = adapter.send_message('second')
        current = adapter.active_operation_id()
        self.started(adapter, second)
        self.assertNotEqual(old, current)
        self.assertFalse(adapter.stop_if_owned(old))
        process = adapter._process
        adapter._process = FixtureProcess(lambda packet: None)
        self.assertIsNone(adapter.active_operation_id())
        self.assertFalse(adapter.stop_if_owned(current))
        self.assertFalse(any(packet['method'] == 'turn/interrupt' for packet in process.stdin.packets))

    def test_codex_final_write_rechecks_owned_operation(self):
        adapter = self.codex()
        turn = adapter.send_message('first')
        token = adapter.active_operation_id()
        self.started(adapter, turn)
        entered, release = threading.Event(), threading.Event()
        self.releases.append(release)
        original = adapter._write
        def delayed(packet, **kwargs):
            if packet.get('method') == 'turn/interrupt':
                entered.set()
                if not release.wait(5): raise AssertionError('Interrupt barrier not released')
            return original(packet, **kwargs)
        adapter._write = delayed
        thread, result = self.background(lambda: adapter.stop_if_owned(token))
        self.assertTrue(entered.wait(3))
        self.started(adapter, 'replacement-before-write')
        release.set()
        self.finish(thread, result)
        self.assertFalse(result['value'])
        self.assertFalse(any(p['method'] == 'turn/interrupt' for p in adapter._process.stdin.packets))
        self.assertEqual({}, adapter._pending)

    def test_claude_local_generation_exists_before_user_write(self):
        adapter = self.claude()
        captured = []
        original = adapter._process.stdin.callback
        def capture(packet):
            if packet.get('type') == 'user': captured.append(adapter.active_operation_id())
            return original(packet)
        adapter._process.stdin.callback = capture
        adapter.send_message('first')
        token = adapter.active_operation_id()
        self.assertEqual([token], captured)
        self.assertIsInstance(token, tuple)
        self.assertTrue(adapter.stop_if_owned(token))
        self.assertEqual('interrupt', adapter._process.stdin.packets[-1]['request']['subtype'])

    def test_claude_new_send_and_wrong_session_reject_old_local_token(self):
        adapter = self.claude()
        adapter.send_message('first')
        old = adapter.active_operation_id()
        adapter._handle({'type': 'result', 'session_id': adapter.session_id})
        adapter.send_message('second')
        current = adapter.active_operation_id()
        self.assertNotEqual(old, current)
        self.assertFalse(adapter.stop_if_owned(old))
        adapter.session_id = 'different-session'
        self.assertFalse(adapter.stop_if_owned(current))
        self.assertFalse(any(p.get('type') == 'control_request' for p in adapter._process.stdin.packets))

    def test_claude_final_interrupt_write_cannot_target_replacement_send(self):
        adapter = self.claude()
        adapter.send_message('first')
        old = adapter.active_operation_id()
        entered, release = threading.Event(), threading.Event()
        self.releases.append(release)
        original = adapter._write
        def delayed(packet, **kwargs):
            if packet.get('type') == 'control_request':
                entered.set()
                if not release.wait(5): raise AssertionError('Claude interrupt barrier not released')
            return original(packet, **kwargs)
        adapter._write = delayed
        thread, result = self.background(lambda: adapter.stop_if_owned(old))
        self.assertTrue(entered.wait(3))
        adapter._handle({'type': 'result', 'session_id': adapter.session_id})
        adapter.send_message('replacement')
        current = adapter.active_operation_id()
        release.set()
        self.finish(thread, result)
        self.assertFalse(result['value'])
        self.assertEqual(current, adapter.active_operation_id())
        self.assertFalse(adapter._stopping)
        self.assertEqual(['user', 'user'], [p['type'] for p in adapter._process.stdin.packets])
        self.assertEqual({}, adapter._pending)

    def test_claude_old_process_or_session_result_cannot_release_current_send(self):
        adapter = self.claude()
        adapter.send_message('current')
        token = adapter.active_operation_id()
        old = FixtureProcess(lambda packet: None)
        old.stdout = [json.dumps({'type': 'result', 'session_id': adapter.session_id}) + '\n']
        adapter._read_stdout(old)
        self.assertEqual(token, adapter.active_operation_id())
        self.assertFalse(adapter._idle.is_set())
        adapter._handle({'type': 'result', 'session_id': 'different-session'})
        self.assertEqual(token, adapter.active_operation_id())
        self.assertEqual('Busy', adapter.state)

    def test_claude_stale_or_closing_stderr_never_enters_current_context(self):
        adapter = self.claude()
        adapter.send_message('current')
        token = adapter.active_operation_id()
        self.events.clear()
        old = FixtureProcess(lambda packet: None)
        old.stderr = io.StringIO('stale old-process diagnostic\n')
        adapter._read_stderr(old)
        self.assertEqual([], self.events)
        self.assertEqual('', adapter._last_stderr)
        adapter._closed = True
        adapter._process.stderr = io.StringIO('closing diagnostic\n')
        adapter._read_stderr(adapter._process)
        self.assertEqual([], self.events)
        adapter._closed = False
        adapter._process.stderr = io.StringIO('current public diagnostic\n')
        adapter._read_stderr(adapter._process)
        self.assertEqual('current public diagnostic', adapter._last_stderr)
        self.assertEqual(token, adapter.active_operation_id())
        self.assertEqual('stderr', self.events[-1][1]['stream'])

    def test_claude_closing_process_has_no_cancellable_local_operation(self):
        adapter = self.claude()
        adapter.send_message('current')
        token = adapter.active_operation_id()
        adapter._closed = True
        self.assertIsNone(adapter.active_operation_id())
        self.assertFalse(adapter.stop_if_owned(token))
        self.assertEqual(['user'], [p['type'] for p in adapter._process.stdin.packets])

    def test_real_adapters_check_guard_after_prep_and_at_final_write(self):
        for build in (self.codex, self.claude):
            with self.subTest(adapter=build.__name__):
                adapter = build()
                calls = []
                def reject_final(*, final=False):
                    calls.append(final)
                    if final: raise RuntimeError('run stopped immediately before dispatch')
                with self.assertRaisesRegex(RuntimeError, 'stopped'):
                    adapter.send_message('must not be sent', dispatch_guard=reject_final)
                self.assertIn(False, calls)
                self.assertIn(True, calls)
                self.assertEqual([], adapter._process.stdin.packets)
                self.assertIsNone(adapter.active_operation_id())
                self.assertEqual({}, adapter._pending)

    def test_core_can_cancel_owned_real_codex_and_claude_operations(self):
        for build in (self.codex, self.claude):
            with self.subTest(adapter=build.__name__), tempfile.TemporaryDirectory() as directory:
                adapter = build()
                repo = Path(directory) / 'repo'; repo.mkdir()
                core = WorkspaceCore(Path(directory) / 'data', {adapter.agent: adapter})
                core.git_snapshot = lambda *a, **k: {'branch': '', 'diff': '', 'status': '', 'log': ''}
                project = core.create_project('fixture', repo)
                core.select_project(project['id'], sync=False)
                task = core.create_task('fixture')
                core.store.update('tasks', {'id': task['id']}, {adapter.agent + '_session': adapter.session_id})
                contract = {'agent': adapter.agent, 'run_id': 'a' * 32, 'task_id': task['id'], 'project_id': project['id'],
                    'session_id': adapter.session_id, 'correlation_id': 'a' * 32 + ':1:' + 'b' * 32, 'prompt': 'owned request'}
                receipt = core.send_orchestration_message(adapter.agent, contract['prompt'], contract)
                contract['local_request_id'] = receipt['local_message_id']
                if adapter.agent == 'codex': self.started(adapter, adapter._turn_id)
                self.assertIsInstance(core._active_requests[adapter.agent]['cancel_token'], tuple)
                self.assertTrue(core.stop_orchestration_message(adapter.agent, contract))
                saved = core.store.get('messages', {'id': receipt['local_message_id']})
                self.assertNotIn('cancel_token', saved['metadata'])
                packet = adapter._process.stdin.packets[-1]
                self.assertEqual('turn/interrupt' if adapter.agent == 'codex' else 'control_request', packet.get('method', packet.get('type')))
                core.close()

    def test_core_real_codex_does_not_capture_unsolicited_turn_as_its_request(self):
        adapter = self.codex()
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / 'repo'; repo.mkdir()
            core = WorkspaceCore(Path(directory) / 'data', {'codex': adapter})
            self.addCleanup(core.close)
            core.git_snapshot = lambda *a, **k: {'branch': '', 'diff': '', 'status': '', 'log': ''}
            project = core.create_project('fixture', repo)
            core.select_project(project['id'], sync=False)
            task = core.create_task('fixture')
            core.store.update('tasks', {'id': task['id']}, {'codex_session': adapter.session_id})
            contract = {'agent': 'codex', 'run_id': 'a' * 32, 'task_id': task['id'], 'project_id': project['id'],
                'session_id': adapter.session_id, 'correlation_id': 'a' * 32 + ':1:' + 'b' * 32, 'prompt': 'owned request'}
            original = adapter.active_operation_id
            def replaced_before_getter():
                self.started(adapter, 'unsolicited-B')
                return original()
            adapter.active_operation_id = replaced_before_getter
            receipt = core.send_orchestration_message('codex', contract['prompt'], contract)
            contract['local_request_id'] = receipt['local_message_id']
            self.assertIsNone(core._active_requests['codex']['cancel_token'])
            self.assertFalse(core.stop_orchestration_message('codex', contract))
            self.assertEqual(['turn/start'], [p['method'] for p in adapter._process.stdin.packets])
            core.close()

    def test_orchestrator_stop_during_core_or_adapter_prep_prevents_real_user_write(self):
        for stage in ('core_project', 'adapter_content'):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory:
                claude = self.claude()
                codex = self.codex()
                dot = SyntheticAdapter('dot')
                dot.state, dot.target, dot.native_room_id, dot.session_id = 'Connected', 'selected', 'room', 'selected'
                dot.revoke_run = lambda *, owner: None
                adapters = {'claude': claude, 'codex': codex, 'dot': dot}
                repo = Path(directory) / 'repo'; repo.mkdir()
                core = WorkspaceCore(Path(directory) / 'data', adapters)
                core.git_snapshot = lambda *a, **k: {'branch': '', 'diff': '', 'status': '', 'log': ''}
                project = core.create_project('fixture', repo)
                core.select_project(project['id'], sync=False)
                task = core.create_task('fixture')
                core.store.update('tasks', {'id': task['id']}, {agent + '_session': adapter.session_id for agent, adapter in adapters.items()})
                entered, release = threading.Event(), threading.Event()
                self.releases.append(release)
                method = 'set_project' if stage == 'core_project' else '_prepare_content'
                original = getattr(claude, method)
                def blocked(*args, **kwargs):
                    entered.set()
                    if not release.wait(5): raise AssertionError('Preparation barrier not released')
                    return original(*args, **kwargs)
                setattr(claude, method, blocked)
                dispatched = []
                def dispatch(operation, done, failed):
                    def execute():
                        try: result = operation()
                        except Exception as exc: failed(exc)
                        else: done(result)
                    thread, outcome = self.background(execute)
                    dispatched.append((thread, outcome))
                run = Orchestrator(core, 'approved task', dispatch)
                run.start()
                self.assertTrue(entered.wait(3))
                run.stop()
                self.assertTrue(run._cancel_event.is_set())
                release.set()
                for thread, outcome in dispatched: self.finish(thread, outcome)
                self.assertEqual('stopped', run.state)
                self.assertEqual([], claude._process.stdin.packets)
                self.assertNotIn('codex', core._active_requests)
                outgoing = [m for m in core.messages(task['id'], 'claude') if m['role'] == 'user']
                self.assertTrue(all(m['status'] == 'failed' for m in outgoing))
                core.close()


if __name__ == '__main__':
    unittest.main()
