"""The run.sh mutex shared by Workspace: refuse a live holder, replace a dead one,
delete only this launcher's own record. Fixture processes only; no hermes.exe runs."""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from acw.adapters.hermes import (HermesAdapter, HermesLock, LOCK_ENV, lock_path,
                                 pid_alive, read_lock)


HELP_TEXT = ' '.join((
    '--query-file', '--format', 'stream-json', '--resume', '--in',
    '--max-turns', '--run-budget', '--source', '--no-restore-cwd',
))
NATIVE_ID = '20261011_010203_a1b2c3d4'
PACKETS = [
    {'type': 'system', 'subtype': 'init', 'session_id': NATIVE_ID},
    {'type': 'text', 'text': 'Hello'},
    {'type': 'result', 'text': 'Hello', 'session_id': NATIVE_ID, 'exit_code': 0},
]


def run_sh_lock(pid, label='z6-run1'):
    """Exactly what run.sh's printf writes."""
    return ('{"pid": %s, "label": "%s", "worktree": "%s", "hermes_exe": "%s", "started": "%s"}\n'
            % (pid, label, 'C:/Users/ryant/Desktop/kpr-erp-masters', 'hermes.exe',
               '2026-10-15T14:09:29+08:00'))


class FixtureProcess:
    def __init__(self, packets=PACKETS, exit_code=0):
        self.stdout = io.StringIO(''.join(json.dumps(packet) + '\n' for packet in packets))
        self.stderr = io.StringIO()
        self.stdin = None
        self.pid = 999999
        self.returncode = None
        self.exit_code = exit_code

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is None:
            self.returncode = self.exit_code
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9


class BlockingOutput(io.StringIO):
    """stdout that holds the child open until the test releases it."""

    def __init__(self):
        super().__init__()
        self.entered, self.release = threading.Event(), threading.Event()

    def readline(self, size=-1):
        self.entered.set()
        if not self.release.wait(5):
            raise RuntimeError('Fixture barrier expired')
        return ''


class HermesLockAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='acw-hermes-lock-')
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.project = self.directory / 'project'
        self.project.mkdir()
        self.lock = self.directory / 'runs' / 'hermes.lock'
        self.lock.parent.mkdir()
        self.env = patch.dict(os.environ, {LOCK_ENV: str(self.lock)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.spawned = []
        self.adapters = []
        self.process = FixtureProcess()
        for target, options in (
                ('acw.adapters.hermes.subprocess.run', {'return_value': subprocess.CompletedProcess(
                    ['hermes.exe', 'chat', '--help'], 0, HELP_TEXT, '')}),
                ('acw.adapters.hermes.subprocess.Popen', {'side_effect': self.spawn}),
                ('acw.adapters.hermes.time.sleep', {'return_value': None})):
            patcher = patch(target, **options)
            setattr(self, target.rsplit('.', 1)[1], patcher.start())
            self.addCleanup(patcher.stop)
        self.addCleanup(lambda: [adapter.disconnect() for adapter in self.adapters])

    def spawn(self, argv, **kwargs):
        self.spawned.append({'argv': argv, 'lock': self.lock.read_text(encoding='utf-8')
                             if self.lock.exists() else None})
        return self.process

    def ready(self, **settings):
        events = []
        adapter = HermesAdapter(lambda kind, **data: events.append((kind, data)),
                                executable='hermes.exe', **settings)
        adapter.events = events
        self.adapters.append(adapter)
        adapter.set_project(str(self.project))
        adapter.connect()
        adapter.create_session()
        return adapter

    def finish(self, adapter):
        worker = adapter._thread
        self.assertIsNotNone(worker)
        worker.join(5)
        self.assertFalse(worker.is_alive(), 'Hermes worker did not exit')
        self.assertIn('message_end', [kind for kind, _ in adapter.events])

    def test_live_run_sh_lock_refuses_before_any_subprocess(self):
        self.lock.write_text(run_sh_lock(424242, 'z6-run1'), encoding='utf-8')
        adapter = self.ready()
        with patch('acw.adapters.hermes.pid_alive', return_value=True) as alive:
            with self.assertRaisesRegex(RuntimeError, r'^Hermes 正由 run\.sh 的 z6-run1 使用中（pid 424242）$'):
                adapter.send_message('must not start')
        alive.assert_called_once_with(424242)
        self.Popen.assert_not_called()
        self.assertEqual('Connected', adapter.state)
        self.assertEqual(run_sh_lock(424242, 'z6-run1'), self.lock.read_text(encoding='utf-8'))
        self.assertFalse(any(kind == 'message_start' for kind, _ in adapter.events))
        self.assertFalse(adapter.diagnostics()['lock_held'])
        self.assertEqual([], [path for path in self.lock.parent.iterdir() if path != self.lock])

    def test_stale_lock_is_replaced_with_run_sh_compatible_record(self):
        self.lock.write_text(run_sh_lock(424242, 'z5-run1'), encoding='utf-8')
        adapter = self.ready()
        stderr = io.StringIO()
        with patch('acw.adapters.hermes.pid_alive', return_value=False) as alive, \
                contextlib.redirect_stderr(stderr):
            adapter.send_message('start after stale lock')
            self.finish(adapter)
        alive.assert_called_once_with(424242)
        self.Popen.assert_called_once()
        written = self.spawned[0]['lock']
        self.assertIsNotNone(written, 'lock must exist before the child starts')
        self.assertTrue(written.endswith('\n') and written.count('\n') == 1)
        record = json.loads(written)
        self.assertEqual(['pid', 'label', 'worktree', 'hermes_exe', 'started'], list(record))
        self.assertEqual(os.getpid(), record['pid'])
        self.assertEqual('acw:hermes', record['label'])
        self.assertEqual(self.project.resolve().as_posix(), record['worktree'])
        self.assertEqual('hermes.exe', record['hermes_exe'])
        self.assertRegex(record['started'], r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$')
        # run.sh's own sed/grep patterns must recognize the record.
        self.assertRegex(written, r'"pid": %d,' % os.getpid())
        self.assertRegex(written, r'"label": "acw:hermes"')
        diagnostic = stderr.getvalue()
        self.assertIn('z5-run1', diagnostic)
        self.assertIn('424242', diagnostic)
        self.assertFalse(self.lock.exists(), 'own lock is removed once the child ends')
        self.assertEqual([], list(self.lock.parent.iterdir()), 'no stale copies are left behind')

    def test_own_lock_is_removed_after_completion_and_after_cancel(self):
        adapter = self.ready(instance='two')
        adapter.send_message('complete normally')
        self.assertEqual('acw:two', json.loads(self.spawned[0]['lock'])['label'])
        self.finish(adapter)
        self.assertFalse(self.lock.exists())
        output = self.process.stdout = BlockingOutput()
        self.addCleanup(output.release.set)
        operation = adapter.send_message('then cancel')
        self.assertTrue(output.entered.wait(5))
        self.assertTrue(self.lock.exists())
        self.assertTrue(adapter.diagnostics()['lock_held'])
        with patch.object(adapter, '_terminate', side_effect=lambda process: (process.terminate(), output.release.set())):
            self.assertTrue(adapter.stop_if_owned(operation))
            self.finish(adapter)
        self.assertEqual('interrupted', [data for kind, data in adapter.events if kind == 'message_end'][-1]['status'])
        self.assertFalse(self.lock.exists())
        self.assertFalse(adapter.diagnostics()['lock_held'])

    def test_lock_taken_over_by_run_sh_during_the_run_is_not_deleted(self):
        adapter = self.ready()
        def takeover(argv, **kwargs):
            self.spawn(argv, **kwargs)
            # run.sh judged our record stale (e.g. after a crash) and wrote its own.
            self.lock.write_text(run_sh_lock(777, 'z7-run1'), encoding='utf-8')
            return self.process
        self.Popen.side_effect = takeover
        adapter.send_message('finish while someone else holds the lock')
        self.finish(adapter)
        self.assertEqual(run_sh_lock(777, 'z7-run1'), self.lock.read_text(encoding='utf-8'))

    def test_second_instance_in_same_process_is_refused_without_tasklist(self):
        first = self.ready(instance='alpha')
        output = self.process.stdout = BlockingOutput()
        self.addCleanup(output.release.set)
        first.send_message('hold the lock')
        self.assertTrue(output.entered.wait(5))
        second = self.ready(instance='beta')
        with patch('acw.adapters.hermes.pid_alive', side_effect=AssertionError('own pid needs no tasklist')):
            with self.assertRaisesRegex(RuntimeError, r'^Hermes 正由 本程式的 acw:alpha 使用中（pid %d）$' % os.getpid()):
                second.send_message('must wait')
        self.assertEqual(1, self.Popen.call_count)
        self.assertEqual('Connected', second.state)
        output.release.set()
        self.finish(first)
        self.assertFalse(self.lock.exists())
        self.assertEqual('acw:alpha', json.loads(self.spawned[0]['lock'])['label'])

    def test_launch_failure_releases_own_lock(self):
        adapter = self.ready()
        self.Popen.side_effect = OSError('fixture launch failure')
        with self.assertRaisesRegex(OSError, 'fixture launch failure'):
            adapter.send_message('fails to launch')
        self.assertFalse(self.lock.exists())
        self.assertEqual('Connected', adapter.state)
        self.assertFalse(adapter.diagnostics()['lock_held'])

    def test_unreadable_lock_refuses_and_is_left_alone(self):
        self.lock.write_text('{"pid": "not a number"}\n', encoding='utf-8')
        adapter = self.ready()
        with patch('acw.adapters.hermes.pid_alive') as alive:
            with self.assertRaisesRegex(RuntimeError, '鎖檔無法解讀'):
                adapter.send_message('must not start')
        alive.assert_not_called()
        self.Popen.assert_not_called()
        self.assertEqual('{"pid": "not a number"}\n', self.lock.read_text(encoding='utf-8'))

    def test_setting_overrides_environment_and_missing_directory_is_created(self):
        custom = self.directory / 'elsewhere' / 'deeper' / 'hermes.lock'
        adapter = self.ready(lock_file=str(custom))
        self.assertEqual(custom, lock_path(adapter.settings))
        self.assertEqual(str(custom), adapter.diagnostics()['lock_file'])
        seen = {}
        def observe(argv, **kwargs):
            seen['custom'] = custom.read_text(encoding='utf-8') if custom.exists() else None
            seen['env'] = self.lock.exists()
            return self.process
        self.Popen.side_effect = observe
        adapter.send_message('use the configured lock path')
        self.finish(adapter)
        self.assertEqual(os.getpid(), json.loads(seen['custom'])['pid'])
        self.assertFalse(seen['env'])
        self.assertFalse(custom.exists())

    def test_prompt_file_is_cleaned_when_lock_refuses(self):
        self.lock.write_text(run_sh_lock(424242), encoding='utf-8')
        adapter = self.ready()
        created = []
        factory = tempfile.TemporaryDirectory
        def record(**kwargs):
            directory = factory(**kwargs)
            created.append(Path(directory.name))
            return directory
        with patch('acw.adapters.hermes.tempfile.TemporaryDirectory', side_effect=record), \
                patch('acw.adapters.hermes.pid_alive', return_value=True):
            with self.assertRaises(RuntimeError):
                adapter.send_message('refused')
        self.assertTrue(created)
        self.assertFalse(any(path.exists() for path in created))


@unittest.skipUnless(os.name == 'nt', 'tasklist-based liveness is the Windows contract shared with run.sh')
class RealProcessLivenessTests(unittest.TestCase):
    """Real tasklist, real files, no adapter mocks and no hermes.exe."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='acw-hermes-lock-real-')
        self.addCleanup(self.temporary.cleanup)
        self.lock = Path(self.temporary.name) / 'hermes.lock'

    def exited_pid(self):
        child = subprocess.Popen([sys.executable, '-c', 'pass'], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        child.wait(30)
        return child.pid

    def test_pid_alive_matches_only_the_pid_column(self):
        self.assertTrue(pid_alive(os.getpid()))
        self.assertFalse(pid_alive(self.exited_pid()))

    def test_live_holder_refuses_and_dead_holder_is_replaced(self):
        self.lock.write_text(run_sh_lock(os.getpid(), 'z1-run1'), encoding='utf-8')
        lock = HermesLock(self.lock, 'acw:hermes', self.temporary.name, 'C:/x/hermes.exe')
        with self.assertRaisesRegex(RuntimeError, 'z1-run1'):
            lock.acquire()
        self.assertFalse(lock.held)
        self.assertEqual(run_sh_lock(os.getpid(), 'z1-run1'), self.lock.read_text(encoding='utf-8'))
        dead = self.exited_pid()
        self.lock.write_text(run_sh_lock(dead, 'z2-run1'), encoding='utf-8')
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            lock.acquire()
        self.assertTrue(lock.held)
        self.assertIn(str(dead), stderr.getvalue())
        self.assertEqual(os.getpid(), read_lock(self.lock)['pid'])
        self.assertEqual('hermes.exe', read_lock(self.lock)['hermes_exe'])
        with self.assertRaises(RuntimeError):
            HermesLock(self.lock, 'acw:other', self.temporary.name, 'hermes.exe').acquire()
        lock.release()
        self.assertFalse(self.lock.exists())
        lock.release()  # idempotent, and never deletes a file it no longer owns
        self.lock.write_text(run_sh_lock(dead, 'z3-run1'), encoding='utf-8')
        lock.held = True
        lock.release()
        self.assertTrue(self.lock.exists())

    def test_record_survives_run_sh_text_patterns(self):
        lock = HermesLock(self.lock, 'acw:hermes', r'C:\Users\example\work tree', 'hermes.exe')
        lock.acquire()
        text = self.lock.read_bytes().decode('utf-8')
        self.assertNotIn('\r', text, 'binary mode keeps a single LF like run.sh')
        self.assertIsNotNone(re.search(r'"pid": *(\d+)', text))
        self.assertIsNotNone(re.search(r'"label": *"([^"]*)"', text))
        self.assertIn('"worktree": "C:/Users/example/work tree"', text)
        lock.release()


if __name__ == '__main__':
    unittest.main()
