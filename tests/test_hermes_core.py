"""Offline Hermes integration: stable workspace aliases and restored native sessions."""
import io
import json
import os
import re
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from acw.core import WorkspaceCore
from acw.adapters.hermes import HermesAdapter
from acw.orchestrator import Orchestrator
from tests.test_core import SyntheticAdapter


class HermesFixture(SyntheticAdapter):
    """In-memory contract double; does not launch Hermes or access its files."""
    local_harness = 'hermes'

    def __init__(self, agent='local'):
        super().__init__(agent)
        self._process = None
        self.native_session_id = ''
        self.restored = []

    def create_session(self):
        self.session_id = 'hermes-' + uuid.uuid4().hex
        self.native_session_id = ''
        self.emit('session', session_id=self.session_id)
        return self.session_id

    def restore_session_metadata(self, session_id, metadata):
        self.restored.append((session_id, dict(metadata)))
        self.native_session_id = metadata.get('native_session_id', '')

    def native_session(self, native_id):
        self.native_session_id = native_id
        self.emit('session', session_id=self.session_id, native_session_id=native_id,
                  cwd=self.cwd, local_harness=self.local_harness)


class NativeProcessFixture:
    """A JSONL process double with an optional read barrier for cancellation."""
    def __init__(self, events=(), blocked=False):
        release = self.release = threading.Event()
        if not blocked:
            release.set()

        class Output(io.StringIO):
            def readline(self, size=-1):
                if not release.wait(5):
                    raise RuntimeError('Fixture stream was not released')
                return super().readline(size)

        self.stdout = Output(''.join(json.dumps(event) + '\n' for event in events))
        self.stderr = io.StringIO()
        self.returncode = None

    def wait(self, timeout=None):
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = -15
        self.release.set()


class HermesCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='acw-hermes-core-')
        self.root = Path(self.temp.name)
        # The shared run.sh mutex is redirected so fixtures never touch the machine lock.
        self.lock_env = patch.dict(os.environ, {'ACW_HERMES_LOCK': str(self.root / 'hermes.lock')})
        self.lock_env.start()
        self.adapter = HermesFixture()
        self.core = WorkspaceCore(self.root / 'data', {'local': self.adapter})
        self.core.git_snapshot = lambda *args, **kwargs: {'branch': 'fixture'}
        self.project = self.core.create_project('Hermes fixture', self.root)
        self.core.select_project(self.project['id'], sync=False)
        self.task = self.core.create_task('Hermes conversation')
        self.adapter.state = 'Connected'

    def tearDown(self):
        self.core.close()
        self.lock_env.stop()
        self.temp.cleanup()

    def test_alias_created_before_first_native_run_can_be_resumed(self):
        alias = self.core.create_session('local')
        self.assertRegex(alias, r'^hermes-[0-9a-f]{32}$')
        saved = self.core.store.get('sessions', {'agent': 'local', 'id': alias})
        self.assertEqual('hermes', saved['metadata']['local_harness'])
        self.assertNotIn('native_session_id', saved['metadata'])
        self.core.resume_session('local', alias)
        self.assertEqual(alias, self.core.current_task['local_session'])
        self.assertEqual('', self.adapter.native_session_id)
        self.assertEqual(self.project['repo_path'], self.adapter.restored[-1][1]['cwd'])

    def test_native_compaction_changes_preserve_alias_history_and_custom_metadata(self):
        alias = self.core.create_session('local')
        self.core.store.update('sessions', {'agent': 'local', 'id': alias},
                               {'metadata': {'local_harness': 'hermes', 'custom': 'preserved'}})
        for native_id, body in (('native-first', 'First response'), ('native-compacted', 'Second response')):
            self.adapter.native_session(native_id)
            self.adapter.emit('message_end', content=body)
        saved = self.core.store.get('sessions', {'agent': 'local', 'id': alias})
        self.assertEqual({'local_harness': 'hermes', 'custom': 'preserved',
                          'native_session_id': 'native-compacted'}, saved['metadata'])
        self.assertEqual(alias, self.core.current_task['local_session'])
        self.assertEqual([alias], [row['id'] for row in self.core.sessions('local')])
        self.assertEqual(['First response', 'Second response'],
                         [row['content'] for row in self.core.messages(agent='local')])
        self.assertTrue(all(row['session_id'] == alias for row in self.core.messages(agent='local')))

    def test_restart_restores_latest_native_session_only_on_explicit_resume(self):
        alias = self.core.create_session('local')
        self.adapter.native_session('native-first')
        self.adapter.native_session('native-compacted')
        self.core.close()
        self.adapter = HermesFixture()
        self.core = WorkspaceCore(self.root / 'data', {'local': self.adapter})
        self.assertEqual([], self.adapter.restored)
        self.assertEqual('', self.adapter.native_session_id)
        self.assertEqual('Disconnected', self.adapter.state)
        self.adapter.state = 'Connected'
        self.core.resume_session('local', alias)
        self.assertEqual(alias, self.adapter.session_id)
        self.assertEqual('native-compacted', self.adapter.native_session_id)
        self.assertEqual(self.project['repo_path'], self.adapter.restored[-1][1]['cwd'])

    def test_legacy_or_unidentified_sessions_never_reach_hermes_resume(self):
        alias = self.core.create_session('local')
        for metadata in ({'local_harness': 'codex'}, {'local_harness': 'claude'}, {}):
            with self.subTest(metadata=metadata):
                self.core.store.update('sessions', {'agent': 'local', 'id': alias}, {'metadata': metadata})
                with patch.object(self.adapter, 'resume_session') as resume:
                    with self.assertRaisesRegex(ValueError, '舊紀錄仍保留'):
                        self.core.resume_session('local', alias)
                    resume.assert_not_called()
                self.assertEqual(metadata, self.core.store.get('sessions', {'agent': 'local', 'id': alias})['metadata'])
        with self.assertRaisesRegex(ValueError, 'Hermes'):
            self.core.resume_session('local', 'unknown-native-id')
        self.assertEqual([], self.adapter.restored)

    def test_reconnect_does_not_reapply_legacy_executable_after_factory_migration(self):
        from acw.adapters.local import LocalCodexAdapter
        legacy = LocalCodexAdapter(lambda *args, **kwargs: None, executable='legacy-codex.exe')
        self.core.set_adapter('local', legacy)
        values = {'harness': 'codex', 'executable': 'legacy-codex.exe',
                  'base_url': 'http://localhost:1234', 'model': 'legacy-model'}
        self.core.set_setting('agent.local', values)
        with patch.object(HermesAdapter, 'connect', return_value=None):
            self.core.connect('local')
        adapter = self.core.adapters['local']
        self.assertIsInstance(adapter, HermesAdapter)
        self.assertEqual('', adapter.executable)
        self.assertEqual('', adapter.settings['model'])
        self.assertEqual(values, self.core.get_setting('agent.local'))

    def test_same_alias_cannot_be_opened_by_another_connected_hermes_instance(self):
        alias = self.core.create_session('local')
        with patch('acw.core.make_adapter', return_value=HermesFixture()) as factory:
            agent = self.core.create_agent_instance('local', 'Hermes worker', project_id=self.project['id'])['id']
        other = self.core.adapters[agent]
        other.agent = agent
        other.state = 'Connected'
        self.core.select_agent_task(agent, self.task['id'])
        self.core._map_session(agent, alias, native_session_id='native-shared')
        with self.assertRaisesRegex(RuntimeError, 'already connected'):
            self.core.resume_session(agent, alias)
        self.assertEqual([], other.restored)
        self.assertEqual('local', factory.call_args.args[0])

    def test_orchestration_accepts_reply_after_native_session_changes(self):
        lead = SyntheticAdapter('claude')
        self.core.set_adapter('claude', lead)
        lead.state = 'Connected'
        sent = []

        def reply(adapter, content, **options):
            guard = options.get('dispatch_guard')
            if guard:
                guard(final=True)
            token = re.findall(r'ACW_REPLY: ([0-9a-f]{32}:[1-9][0-9]*:[0-9a-f]{32})', content)[-1]
            verdict = 'PLAN_READY' if not sent else 'IMPLEMENTED' if adapter is self.adapter else 'APPROVED'
            sent.append(adapter.agent)
            if adapter is self.adapter:
                adapter.native_session('native-created')
                adapter.native_session('native-compacted')
            adapter.emit('message_end', content=f'VERDICT: {verdict}\nACW_REPLY: {token}\nVerified fixture reply\nACW_END: {token}')
            return {'accepted': True}

        lead.send_message = lambda content, **options: reply(lead, content, **options)
        self.adapter.send_message = lambda content, **options: reply(self.adapter, content, **options)

        def dispatch(operation, done, failed):
            try:
                result = operation()
            except Exception as exc:
                failed(exc)
            else:
                done(result)

        run = Orchestrator(self.core, 'Offline Hermes integration', dispatch, local_role='implementer')
        run.start()
        for _ in range(4):
            run.tick()
        self.assertEqual('done', run.state, run.reason)
        self.assertEqual(['claude', 'local', 'claude'], sent)
        self.assertEqual('Hermes 實作', run.names['implement'])
        self.assertEqual(self.adapter.session_id, run._bindings['local']['session_id'])

    def actual_adapter(self):
        adapter = HermesAdapter(lambda *args, **kwargs: None, executable='fixture-hermes.exe')
        self.core.set_adapter('local', adapter)
        adapter.state = 'Connected'
        terminate = patch.object(adapter, '_terminate', side_effect=lambda owned: owned.terminate())
        terminate.start()
        self.addCleanup(terminate.stop)
        self.addCleanup(adapter.disconnect)
        return adapter

    def test_actual_adapter_persists_native_compaction_and_resumes_it_after_replacement(self):
        adapter = self.actual_adapter()
        alias = self.core.create_session('local')
        first = '20261011_010203_a1b2c3d4'
        compacted = '20261011_010204_e5f6a7b8'
        process = NativeProcessFixture([
            {'type': 'system', 'subtype': 'init', 'session_id': first},
            {'type': 'text', 'text': 'Verified response'},
            {'type': 'result', 'session_id': compacted, 'text': 'Verified response', 'exit_code': 0},
        ])
        with patch('acw.adapters.hermes.subprocess.Popen', return_value=process):
            self.core.send_message('local', '中文 prompt with "quotes" and `backticks`')
            adapter._thread.join(5)
        self.assertFalse(adapter._thread.is_alive())
        self.assertEqual('Connected', adapter.state, adapter.last_error)
        self.assertEqual(compacted, self.core.sessions('local')[0]['metadata']['native_session_id'])
        adapter.disconnect()
        replacement = self.actual_adapter()
        self.core.resume_session('local', alias)
        process = NativeProcessFixture([
            {'type': 'system', 'subtype': 'init', 'session_id': compacted},
            {'type': 'result', 'session_id': compacted, 'text': 'Resumed response', 'exit_code': 0},
        ])
        with patch('acw.adapters.hermes.subprocess.Popen', return_value=process) as spawn:
            self.core.send_message('local', 'Continue this conversation')
            replacement._thread.join(5)
        self.assertFalse(replacement._thread.is_alive())
        self.assertIn('--resume=' + compacted, spawn.call_args.args[0])
        self.assertEqual(alias, self.core.current_task['local_session'])
        self.assertEqual(['Verified response', 'Resumed response'],
                         [row['content'] for row in self.core.messages(agent='local') if row['role'] == 'assistant'])

    def test_actual_adapter_run_cancellation_receives_the_owned_operation_token(self):
        adapter = self.actual_adapter()
        alias = self.core.create_session('local')
        process = NativeProcessFixture(blocked=True)
        self.addCleanup(process.release.set)
        contract = {'agent': 'local', 'run_id': 'a' * 32, 'correlation_id': 'a' * 32 + ':1:' + 'b' * 32,
                    'task_id': self.task['id'], 'project_id': self.project['id'], 'session_id': alias,
                    'prompt': 'Bounded fixture work', '_dispatch_guard': lambda: None}
        with patch('acw.adapters.hermes.subprocess.Popen', return_value=process):
            receipt = self.core.send_orchestration_message('local', contract['prompt'], contract)
            contract['local_request_id'] = receipt['local_message_id']
            self.assertIsNotNone(self.core._active_requests['local'].get('cancel_token'))
            self.assertTrue(self.core.stop_orchestration_message('local', contract))
            adapter._thread.join(5)
        self.assertFalse(adapter._thread.is_alive())
        self.assertEqual(-15, process.returncode)
        self.assertEqual(['interrupted'], [row['status'] for row in self.core.messages(agent='local')
                                           if row['role'] == 'assistant'])

    def test_actual_adapter_reader_start_failure_releases_process_and_allows_disconnect(self):
        adapter = self.actual_adapter()
        self.core.create_session('local')
        process = NativeProcessFixture(blocked=True)
        try:
            with patch('acw.adapters.hermes.subprocess.Popen', return_value=process), \
                    patch('acw.adapters.hermes.threading.Thread.start',
                          side_effect=RuntimeError('fixture reader startup failure')):
                with self.assertRaisesRegex(RuntimeError, 'reader startup failure'):
                    self.core.send_message('local', 'Bounded fixture work')
            self.assertEqual(-15, process.returncode, 'Accepted child must be terminated when its reader cannot start')
            self.assertIsNone(adapter._process)
            self.assertEqual('Error', adapter.state)
            adapter.disconnect()
            self.assertEqual('Disconnected', adapter.state)
            self.assertEqual(['interrupted'], [row['status'] for row in self.core.messages(agent='local')
                                               if row['role'] == 'assistant'])
        finally:
            # Keep an intentionally failing implementation from breaking test cleanup.
            process.terminate()
            if adapter._thread is not None and adapter._thread.ident is None:
                adapter._thread = None

    def assert_helper_start_failure_is_cleaned_up(self, helper):
        adapter = self.actual_adapter()
        self.core.create_session('local')
        process = NativeProcessFixture(blocked=True)
        original_start = threading.Thread.start

        def start(thread):
            is_stderr = getattr(getattr(thread, '_target', None), '__name__', '') == '_read_stderr'
            is_timer = isinstance(thread, threading.Timer)
            if (helper == 'stderr' and is_stderr) or (helper == 'timer' and is_timer):
                raise RuntimeError('fixture ' + helper + ' startup failure')
            return original_start(thread)

        try:
            with patch('acw.adapters.hermes.subprocess.Popen', return_value=process), \
                    patch('acw.adapters.hermes.threading.Thread.start', autospec=True, side_effect=start):
                self.core.send_message('local', 'Bounded fixture work')
                adapter._thread.join(5)
            self.assertFalse(adapter._thread.is_alive())
            self.assertEqual(-15, process.returncode, 'Accepted child must be terminated when a helper cannot start')
            self.assertIsNone(adapter._process)
            self.assertEqual('Error', adapter.state)
            self.assertIn(helper + ' startup failure', adapter.last_error)
            self.assertEqual(['interrupted'], [row['status'] for row in self.core.messages(agent='local')
                                               if row['role'] == 'assistant'])
        finally:
            process.terminate()

    def test_actual_adapter_stderr_start_failure_releases_process(self):
        self.assert_helper_start_failure_is_cleaned_up('stderr')

    def test_actual_adapter_timeout_timer_start_failure_releases_process(self):
        self.assert_helper_start_failure_is_cleaned_up('timer')

    def test_actual_adapter_timeout_stops_only_owned_process_and_reports_error(self):
        adapter = self.actual_adapter()
        self.core.create_session('local')
        process = NativeProcessFixture(blocked=True)
        self.addCleanup(process.release.set)
        with patch('acw.adapters.hermes.subprocess.Popen', return_value=process):
            self.core.send_message('local', 'Bounded fixture work')
            operation = adapter.active_operation_id()
            self.assertIsNotNone(operation)
            adapter._expire('expired-previous-operation')
            self.assertIsNone(process.returncode)
            adapter._terminate.assert_not_called()
            adapter._expire(operation)
            adapter._thread.join(5)
        self.assertFalse(adapter._thread.is_alive())
        self.assertEqual(-15, process.returncode)
        self.assertEqual('Error', adapter.state)
        self.assertIn('時間上限', adapter.last_error)
        self.assertIsNone(adapter.active_operation_id())
        self.assertEqual(['interrupted'], [row['status'] for row in self.core.messages(agent='local')
                                           if row['role'] == 'assistant'])


if __name__ == '__main__':
    unittest.main()
