"""Hermes subprocess contracts with fixture streams and no live inference."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from acw.adapters.hermes import HermesAdapter, hermes_settings


HELP_TEXT = ' '.join((
    '--query-file', '--format', 'stream-json', '--resume', '--in',
    '--max-turns', '--run-budget', '--source', '--no-restore-cwd',
))
NATIVE_ID = '20261011_010203_a1b2c3d4'


class FixtureProcess:
    """A completed fixture stream whose process exit is independently chosen."""

    def __init__(self, packets=(), exit_code=0):
        self.stdout = io.StringIO(''.join(json.dumps(packet) + '\n' for packet in packets))
        self.stderr = io.StringIO()
        self.stdin = None
        self.pid = 999999
        self.returncode = None
        self.exit_code = exit_code
        self.terminated = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is None:
            self.returncode = self.exit_code
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.terminated = True
        self.returncode = -9


class HermesAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        # The shared run.sh mutex is redirected so fixtures never touch the machine lock.
        self.lock_env = patch.dict(os.environ, {'ACW_HERMES_LOCK': str(self.directory / 'hermes.lock')})
        self.lock_env.start()
        self.addCleanup(self.lock_env.stop)
        self.events = []
        self.completed = threading.Event()
        self.spawned = []
        self.adapters = []
        self.process = FixtureProcess()
        self.probe = patch('acw.adapters.hermes.subprocess.run', return_value=
                           subprocess.CompletedProcess(['hermes.exe', 'chat', '--help'], 0, HELP_TEXT, ''))
        self.popen = patch('acw.adapters.hermes.subprocess.Popen', side_effect=self.spawn)
        self.run = self.probe.start()
        self.launch = self.popen.start()
        self.addCleanup(self.probe.stop)
        self.addCleanup(self.popen.stop)
        self.addCleanup(self.cleanup_adapters)

    def cleanup_adapters(self):
        for adapter in self.adapters:
            adapter.disconnect()

    def emit(self, kind, **data):
        self.events.append((kind, data))
        if kind == 'message_end':
            self.completed.set()

    def spawn(self, argv, **kwargs):
        prompt = Path(argv[argv.index('--query-file') + 1])
        self.spawned.append({'argv': argv, 'kwargs': kwargs, 'prompt': prompt,
                             'content': prompt.read_text(encoding='utf-8')})
        return self.process

    def adapter(self, **settings):
        adapter = HermesAdapter(self.emit, executable='hermes.exe', **settings)
        self.adapters.append(adapter)
        adapter.set_project(str(self.directory))
        return adapter

    def ready(self, **settings):
        adapter = self.adapter(**settings)
        adapter.connect()
        self.assertEqual('Connected', adapter.state)
        adapter.create_session()
        return adapter

    def finish(self, adapter):
        self.assertTrue(self.completed.wait(5), 'Hermes fixture did not finish')
        worker = getattr(adapter, '_thread', None)
        if worker is not None:
            worker.join(5)
            self.assertFalse(worker.is_alive(), 'Hermes worker did not exit')

    def packets(self, **result):
        return [
            {'type': 'system', 'subtype': 'init', 'session_id': NATIVE_ID},
            {'type': 'text', 'text': 'Hello '},
            {'type': 'text', 'text': 'world'},
            {'type': 'result', 'text': 'Hello world', 'session_id': NATIVE_ID,
             'exit_code': 0, **result},
        ]

    def test_construction_and_new_session_never_launch_inference(self):
        adapter = self.adapter()
        self.run.assert_not_called()
        self.launch.assert_not_called()
        adapter.connect()
        self.assertEqual(['hermes.exe', 'chat', '--help'], self.run.call_args.args[0])
        alias = adapter.create_session()
        self.assertTrue(alias.startswith('hermes-'))
        self.assertEqual(alias, adapter.session_id)
        self.launch.assert_not_called()
        self.assertEqual('hermes', adapter.local_harness)
        self.assertEqual('local', adapter.agent)

    def test_unicode_prompt_is_file_backed_and_shell_metacharacters_stay_literal(self):
        self.process = FixtureProcess(self.packets())
        adapter = self.ready(run_budget=600, max_turns=60, provider='fixture-provider', model='fixture-model')
        prompt = 'Unicode \u6e2c\u8a66 "quoted" `literal` $(literal)\nsecond line'
        adapter.send_message(prompt)
        self.finish(adapter)
        spawned = self.spawned[0]
        argv = spawned['argv']
        self.assertEqual(prompt, spawned['content'])
        self.assertNotIn(prompt, argv)
        self.assertFalse(spawned['kwargs'].get('shell', False))
        self.assertEqual('stream-json', argv[argv.index('--format') + 1])
        self.assertEqual(str(self.directory), argv[argv.index('--in') + 1])
        self.assertEqual('tool', argv[argv.index('--source') + 1])
        self.assertEqual('600', argv[argv.index('--run-budget') + 1])
        self.assertEqual('60', argv[argv.index('--max-turns') + 1])
        self.assertIn('--no-restore-cwd', argv)
        self.assertIn('-Q', argv)
        self.assertNotIn('--yolo', argv)
        self.assertNotIn('--resume', argv)
        self.assertFalse(spawned['prompt'].exists(), 'Prompt file survived completed inference')

    def test_native_session_events_preserve_workspace_alias(self):
        self.process = FixtureProcess(self.packets())
        adapter = self.ready()
        alias = adapter.session_id
        adapter.send_message('fixture')
        self.finish(adapter)
        self.assertEqual(alias, adapter.session_id)
        sessions = [data for kind, data in self.events if kind == 'session' and data.get('native_session_id')]
        self.assertTrue(sessions)
        self.assertEqual(NATIVE_ID, sessions[-1]['native_session_id'])
        self.assertEqual(alias, sessions[-1]['session_id'])
        endings = [data for kind, data in self.events if kind == 'message_end']
        self.assertEqual(1, len(endings))
        self.assertEqual('Hello world', endings[0]['content'])
        self.assertEqual('complete', endings[0]['status'])

    def test_result_packet_cannot_hide_nonzero_process_exit(self):
        self.process = FixtureProcess(self.packets(), exit_code=2)
        adapter = self.ready()
        adapter.send_message('fixture')
        self.finish(adapter)
        endings = [data for kind, data in self.events if kind == 'message_end']
        self.assertEqual(1, len(endings))
        self.assertEqual('interrupted', endings[0]['status'])

    def test_zero_process_exit_cannot_hide_failed_result_packet(self):
        self.process = FixtureProcess(self.packets(exit_code=1))
        adapter = self.ready()
        adapter.send_message('fixture')
        self.finish(adapter)
        endings = [data for kind, data in self.events if kind == 'message_end']
        self.assertEqual(1, len(endings))
        self.assertEqual('interrupted', endings[0]['status'])
        self.assertEqual('Error', adapter.state)

    def test_clean_process_exit_without_result_is_not_success(self):
        self.process = FixtureProcess([{'type': 'text', 'text': 'incomplete'}])
        adapter = self.ready()
        adapter.send_message('fixture')
        self.finish(adapter)
        endings = [data for kind, data in self.events if kind == 'message_end']
        self.assertEqual(1, len(endings))
        self.assertEqual('interrupted', endings[0]['status'])

    def test_legacy_settings_are_normalized_without_mutating_saved_data(self):
        legacy = {'harness': 'claude', 'base_url': 'http://localhost:1234',
                  'api_key_env': 'LOCAL_FIXTURE_KEY', 'model': 'old-model',
                  'provider': 'old-provider', 'executable': 'claude.exe'}
        before = dict(legacy)
        result = hermes_settings(legacy)
        self.assertEqual(before, legacy)
        self.assertEqual('hermes', result['harness'])
        self.assertEqual(600, result['run_budget'])
        self.assertEqual(60, result['max_turns'])
        self.assertEqual('', result['executable'])
        self.assertEqual('', result['provider'])
        self.assertEqual('', result['model'])
        self.assertNotIn('base_url', result)
        self.assertNotIn('api_key_env', result)
        custom = {'harness': 'hermes', 'model': 'configured-model',
                  'provider': 'configured-provider', 'executable': 'custom-hermes.exe',
                  'run_budget': 300, 'max_turns': 20}
        self.assertEqual(custom, hermes_settings(custom))

    def test_probe_requires_all_protocol_flags_and_never_runs_inference(self):
        for missing in ('--query-file', '--format', 'stream-json', '--resume',
                        '--no-restore-cwd', '--run-budget', '--max-turns'):
            with self.subTest(missing=missing):
                self.run.return_value.stdout = HELP_TEXT.replace(missing, '')
                adapter = self.adapter()
                with self.assertRaises(RuntimeError):
                    adapter.connect()
                self.assertEqual('Error', adapter.state)
        self.launch.assert_not_called()

    def test_invalid_limits_fail_before_any_subprocess(self):
        for key, bad_values in (('run_budget', [0, -1, True, '1.5', 86401]),
                                ('max_turns', [0, -1, False, 'many', 1001])):
            for value in bad_values:
                with self.subTest(key=key, value=value):
                    with self.assertRaises(ValueError):
                        self.adapter(**{key: value}).probe()
        self.run.assert_not_called()
        self.launch.assert_not_called()

    def test_shell_wrappers_are_rejected_before_probe(self):
        for executable in ('hermes.cmd', 'hermes.bat', 'hermes.ps1'):
            with self.subTest(executable=executable):
                adapter = self.adapter()
                adapter.executable = executable
                with self.assertRaises(ValueError):
                    adapter.probe()
        self.run.assert_not_called()
        self.launch.assert_not_called()

    def test_restored_native_session_is_resumed_without_changing_project(self):
        self.process = FixtureProcess(self.packets())
        adapter = self.ready()
        alias = 'hermes-' + '1' * 32
        adapter.restore_session_metadata(alias, {'cwd': str(self.directory), 'native_session_id': NATIVE_ID})
        self.assertEqual(alias, adapter.resume_session(alias))
        self.launch.assert_not_called()
        adapter.send_message('continue')
        self.finish(adapter)
        self.assertIn('--resume=' + NATIVE_ID, self.spawned[0]['argv'])
        self.assertIn('--no-restore-cwd', self.spawned[0]['argv'])
        self.assertEqual(alias, adapter.session_id)
        self.assertEqual(str(self.directory), self.spawned[0]['kwargs']['cwd'])

    def test_legacy_and_foreign_project_sessions_are_rejected_without_subprocess(self):
        adapter = self.ready()
        for alias, metadata in (
            ('legacy-claude-session', {'cwd': str(self.directory)}),
            ('hermes-' + '1' * 32, {'cwd': str(self.directory), 'native_session_id': '--yolo'}),
            ('hermes-' + '2' * 32, {'cwd': str(self.directory / 'other'), 'native_session_id': NATIVE_ID}),
        ):
            with self.subTest(alias=alias), self.assertRaises(ValueError):
                adapter.restore_session_metadata(alias, metadata)
        self.launch.assert_not_called()

    def test_model_and_provider_options_do_not_become_extra_cli_flags(self):
        self.process = FixtureProcess(self.packets())
        adapter = self.ready(provider='--yolo', model='model with spaces')
        adapter.send_message('fixture')
        self.finish(adapter)
        argv = self.spawned[0]['argv']
        self.assertIn('--provider=--yolo', argv)
        self.assertIn('--model=model with spaces', argv)
        self.assertNotIn('--yolo', argv)

    def test_inherited_execution_flags_are_removed_only_from_child_environment(self):
        self.process = FixtureProcess(self.packets())
        inherited = {'HERMES_YOLO_MODE': '1', 'HERMES_ACCEPT_HOOKS': '1',
                     'HERMES_SESSION_ID': 'ambient-session', 'HERMES_KANBAN_JOB': 'ambient-job',
                     'HERMES_TURN_ID': 'ambient-turn', 'UNRELATED_FIXTURE': 'keep'}
        with patch.dict(os.environ, inherited):
            before = dict(os.environ)
            adapter = self.ready()
            adapter.send_message('fixture')
            self.finish(adapter)
            self.assertEqual(before, dict(os.environ))
        environment = self.spawned[0]['kwargs']['env']
        self.assertEqual('keep', environment['UNRELATED_FIXTURE'])
        self.assertTrue(all(name not in environment for name in inherited if name != 'UNRELATED_FIXTURE'))

    def test_tool_events_are_visible_but_private_reasoning_is_not_persisted(self):
        packets = self.packets()
        packets[1:1] = [
            {'type': 'reasoning', 'text': 'private-reasoning-canary'},
            {'type': 'tool_use', 'name': 'terminal', 'tool_call_id': 'tool-fixture',
             'input': {'command': 'fixture-command'}},
            {'type': 'tool_result', 'name': 'terminal', 'tool_call_id': 'tool-fixture',
             'output': 'fixture-output', 'is_error': True},
        ]
        self.process = FixtureProcess(packets)
        adapter = self.ready()
        adapter.send_message('fixture')
        self.finish(adapter)
        starts = [data for kind, data in self.events if kind == 'tool_start']
        results = [data for kind, data in self.events if kind == 'tool_result']
        self.assertEqual('tool-fixture', starts[0]['tool_id'])
        self.assertEqual('terminal', starts[0]['name'])
        self.assertEqual({'command': 'fixture-command'}, starts[0]['input'])
        self.assertEqual('fixture-output', results[0]['content'])
        self.assertTrue(results[0]['is_error'])
        self.assertNotIn('private-reasoning-canary', json.dumps(self.events))

    def test_protocol_errors_interrupt_and_cleanup_prompt(self):
        streams = (
            'not-json\n',
            '[]\n',
            json.dumps({'type': 'text', 'text': 17}) + '\n',
            json.dumps({'type': 'result', 'text': 'broken', 'exit_code': True, 'session_id': NATIVE_ID}) + '\n',
            json.dumps({'type': 'system', 'subtype': 'init', 'session_id': 'invalid'}) + '\n',
            ''.join(json.dumps(packet) + '\n' for packet in self.packets()) + '{}\n',
        )
        for stream in streams:
            with self.subTest(stream=stream[:80]):
                self.events.clear()
                self.completed.clear()
                self.process = FixtureProcess()
                self.process.stdout = io.StringIO(stream)
                adapter = self.ready()
                adapter.send_message('fixture')
                self.finish(adapter)
                endings = [data for kind, data in self.events if kind == 'message_end']
                self.assertEqual(1, len(endings))
                self.assertEqual('interrupted', endings[0]['status'])
                self.assertEqual('Error', adapter.state)
                self.assertFalse(self.spawned[-1]['prompt'].exists())

    def test_late_dispatch_guard_blocks_subprocess_and_removes_prompt(self):
        adapter = self.ready()
        temporary_paths = []
        directory_factory = tempfile.TemporaryDirectory
        def temporary_directory(**kwargs):
            directory = directory_factory(**kwargs)
            temporary_paths.append(Path(directory.name))
            return directory
        def refuse(**kwargs):
            self.assertEqual({'final': True}, kwargs)
            raise RuntimeError('fixture dispatch expired')
        with patch('acw.adapters.hermes.tempfile.TemporaryDirectory', side_effect=temporary_directory):
            with self.assertRaisesRegex(RuntimeError, 'dispatch expired'):
                adapter.send_message('must not send', dispatch_guard=refuse)
        self.launch.assert_not_called()
        self.assertEqual('Connected', adapter.state)
        self.assertTrue(temporary_paths)
        self.assertTrue(all(not path.exists() for path in temporary_paths))

    def test_launch_failure_removes_prompt_and_never_marks_adapter_busy(self):
        adapter = self.ready()
        def fail(argv, **kwargs):
            self.spawn(argv, **kwargs)
            raise OSError('fixture launch failure')
        self.launch.side_effect = fail
        with self.assertRaisesRegex(OSError, 'fixture launch failure'):
            adapter.send_message('fixture')
        self.assertEqual('Connected', adapter.state)
        self.assertFalse(self.spawned[0]['prompt'].exists())
        self.assertFalse(any(kind == 'message_start' for kind, _ in self.events))

    def test_owned_stop_rejects_wrong_token_and_interrupts_only_current_process(self):
        entered, release = threading.Event(), threading.Event()
        fixture = self.process = FixtureProcess()
        class BlockingOutput(io.StringIO):
            def readline(self, size=-1):
                entered.set()
                if not release.wait(5):
                    raise RuntimeError('Fixture cancellation barrier expired')
                return ''
        fixture.stdout = BlockingOutput()
        def terminate(process):
            self.assertIs(fixture, process)
            process.terminate()
            release.set()
        self.addCleanup(release.set)
        adapter = self.ready()
        with patch.object(adapter, '_terminate', side_effect=terminate) as stop:
            operation = adapter.send_message('fixture')
            self.assertTrue(entered.wait(5))
            self.assertTrue(callable(adapter.active_operation_id), 'Core requires a callable operation identity')
            self.assertEqual(operation, adapter.active_operation_id())
            self.assertFalse(adapter.stop_if_owned('not-the-operation'))
            stop.assert_not_called()
            with self.assertRaises(RuntimeError):
                adapter.send_message('duplicate')
            self.assertEqual(1, self.launch.call_count)
            self.assertTrue(adapter.stop_if_owned(operation))
            self.finish(adapter)
            stop.assert_called_once_with(fixture)
        ending = [data for kind, data in self.events if kind == 'message_end'][-1]
        self.assertEqual('interrupted', ending['status'])
        self.assertEqual('Connected', adapter.state)
        self.assertIsNone(adapter.active_operation_id())
        self.assertFalse(adapter.stop_if_owned(operation))
        self.assertFalse(self.spawned[0]['prompt'].exists())


@unittest.skipUnless(os.name == 'nt', 'Windows owned process-tree cancellation')
class HermesWindowsCancellationTests(unittest.TestCase):
    def test_real_taskkill_ends_owned_tree_and_preserves_unrelated_process(self):
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
        kernel.TerminateProcess.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.CloseHandle.restype = wintypes.BOOL
        wait_timeout = 258
        child_handle = None
        parent = control = None
        fixture = 'import time; time.sleep(120)'
        parent_source = '''import subprocess, sys, time
from pathlib import Path
child = subprocess.Popen([sys.executable, '-c', sys.argv[2]],
    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    creationflags=subprocess.CREATE_NO_WINDOW)
pending = Path(sys.argv[1] + '.tmp')
pending.write_text(str(child.pid), encoding='ascii')
pending.replace(sys.argv[1])
time.sleep(120)
'''
        options = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        with tempfile.TemporaryDirectory(prefix='acw-hermes-cancel-test-') as temporary:
            ready = Path(temporary) / 'child-ready.txt'
            try:
                control = subprocess.Popen([sys.executable, '-c', fixture], cwd=temporary, **options)
                parent = subprocess.Popen([sys.executable, '-c', parent_source, str(ready), fixture],
                                          cwd=temporary, **options)
                deadline = time.monotonic() + 10
                while not ready.exists() and parent.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(ready.exists(), 'Synthetic parent did not publish its descendant')
                child_pid = int(ready.read_text(encoding='ascii'))
                # Holding the exact process object prevents PID reuse from affecting
                # verification or the fallback cleanup of this synthetic descendant.
                child_handle = kernel.OpenProcess(0x00100000 | 0x1000 | 0x0001, False, child_pid)
                self.assertTrue(child_handle, f'OpenProcess failed: {ctypes.get_last_error()}')
                self.assertIsNone(parent.poll())
                self.assertIsNone(control.poll())
                self.assertEqual(wait_timeout, kernel.WaitForSingleObject(child_handle, 0))

                HermesAdapter._terminate(parent)

                self.assertIsNotNone(parent.poll(), 'Owned parent survived cancellation')
                self.assertEqual(0, kernel.WaitForSingleObject(child_handle, 5000),
                                 'Owned descendant survived taskkill /T')
                self.assertIsNone(control.poll(), 'Cancellation reached an unrelated fixture process')
            finally:
                try:
                    if parent is not None and parent.poll() is None:
                        try:
                            HermesAdapter._terminate(parent)
                        finally:
                            if parent.poll() is None:
                                parent.kill()
                                parent.wait(timeout=5)
                finally:
                    try:
                        if child_handle:
                            try:
                                if kernel.WaitForSingleObject(child_handle, 0) == wait_timeout:
                                    kernel.TerminateProcess(child_handle, 1)
                                    kernel.WaitForSingleObject(child_handle, 5000)
                            finally:
                                kernel.CloseHandle(child_handle)
                    finally:
                        if control is not None and control.poll() is None:
                            control.kill()
                            control.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()
