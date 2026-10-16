"""Offline tests for acw/requests.py: run.sh hands a Hermes step to the open workspace as a request file."""
import json
import os
import re
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from datetime import datetime
from unittest.mock import patch

from acw.core import WorkspaceCore
from acw.playbooks import compose_prompt
from acw.requests import MonitorProjection
from acw.security import sanitize
from acw.adapters.hermes import HermesAdapter
from tests.test_hermes_core import HermesFixture, NativeProcessFixture

PROMPT = 'Read PROGRESS.md and do the step it points to.'


class RecordingHermes(HermesFixture):
    """Contract double that records what a real adapter would see at send time."""
    def __init__(self):
        super().__init__()
        self.settings = {'run_budget': 600, 'max_turns': 60, 'instance': 'fixture'}
        self.fail_send = ''
        self.limits_at_send = None
        self.stopped = []

    def send_message(self, content, **kwargs):
        if self.fail_send:
            raise RuntimeError(self.fail_send)
        self.limits_at_send = (self.settings.get('run_budget'), self.settings.get('max_turns'))
        self.emit('message_start', role='assistant')
        return super().send_message(content, **kwargs)

    def stop_if_owned(self, expected):
        self.stopped.append(expected)
        return True


def git(repo, *args):
    subprocess.run(['git', '-C', str(repo), '-c', 'user.name=t', '-c', 'user.email=t@example.com', *args],
                   check=True, capture_output=True, stdin=subprocess.DEVNULL)


class RequestDispatcherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='acw-requests-')
        self.root = Path(self.temp.name)
        self.lock_env = patch.dict(os.environ, {'ACW_HERMES_LOCK': str(self.root / 'hermes.lock')})
        self.lock_env.start()
        self.repo = self.root / 'work-tree'
        (self.repo / 'docs' / 'briefs' / 't').mkdir(parents=True)
        (self.repo / 'docs' / 'briefs' / 't' / 'PROGRESS.md').write_text('step: A1\n', encoding='utf-8')
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True, stdin=subprocess.DEVNULL)
        git(self.repo, 'add', '-A')
        git(self.repo, 'commit', '-q', '-m', 'init')
        self.monitor = self.root / 'monitor'
        (self.monitor / 'logs').mkdir(parents=True)
        self.adapter = RecordingHermes()
        self.core = WorkspaceCore(self.root / 'data', {'local': self.adapter})
        self.core.git_snapshot = lambda *args, **kwargs: {'branch': 'fixture'}  # the real one shells out to git several times
        self.adapter.state = 'Connected'
        self.requests = Path(self.core.data_dir) / 'requests'
        self.requests.mkdir(parents=True, exist_ok=True)
        self.now = [1000.0]
        self.core.requests.clock = lambda: self.now[0]

    def tearDown(self):
        if not self.core._closed:
            self.core.close()
        self.lock_env.stop()
        self.temp.cleanup()

    # -- helpers
    def request(self, label='r1', **override):
        body = {'label': label, 'worktree': str(self.repo), 'briefs': 'docs/briefs/t', 'prompt': PROMPT,
                'run_budget': 600, 'max_turns': 60, 'allow_dirty': False, 'monitor_root': str(self.monitor),
                'created': '2026-10-15T14:00:00+08:00'}
        body.update(override)
        (self.requests / (label + '.json')).write_text(json.dumps(body), encoding='utf-8')

    def result(self, label='r1'):
        path = self.requests / (label + '.result.json')
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None

    def say(self, kind, **payload):
        self.adapter.emit(kind, **payload)

    def hermes_log(self):
        return (self.monitor / 'logs' / 'hermes.log').read_bytes()

    def timeline(self):
        path = self.monitor / 'logs' / 'timeline.log'
        return path.read_text(encoding='utf-8') if path.exists() else ''

    def assertRejected(self, label, code):
        result = self.result(label)
        self.assertIsNotNone(result)
        self.assertEqual('rejected', result['status'])
        self.assertTrue(result['reason'].startswith(code + ':'), result['reason'])
        self.assertEqual(1, result['exit_code'])
        self.assertEqual([], self.adapter.sent)
        return result

    def start_run(self, label='r1', **override):
        self.request(label, **override)
        self.core.poll_requests()
        self.assertIsNone(self.result(label), 'a started run has no result yet')
        self.assertEqual([compose_prompt(self.core, 'local', PROMPT)], self.adapter.sent)

    def test_active_snapshot_is_detached_and_cleared_after_completion(self):
        self.assertIsNone(self.core.requests.active())
        self.start_run('named-run')
        active = self.core.requests.active()
        self.assertEqual({'label', 'worktree', 'task_id', 'started'}, set(active))
        self.assertEqual('named-run', active['label'])
        self.assertEqual(str(self.repo), active['worktree'])
        self.assertEqual(self.core.agent_task('local')['id'], active['task_id'])
        self.assertIsNotNone(datetime.fromisoformat(active['started']).tzinfo)
        active['label'] = 'tampered'
        self.assertEqual('named-run', self.core.requests.active()['label'])
        self.say('message_end', content='done', status='complete')
        self.core.poll_requests()
        self.assertIsNone(self.core.requests.active())

    # -- rejections
    def test_invalid_label_is_rejected(self):
        for label in ('bad label', 'x' * 65, 'a.result'):
            self.request(label)
            self.core.poll_requests()
        self.assertRejected('bad label', 'bad-label')
        self.assertRejected('x' * 65, 'bad-label')
        self.assertEqual([], self.core.list_projects())

    def test_missing_progress_file_is_rejected(self):
        self.request(briefs='docs/briefs/missing')
        self.core.poll_requests()
        self.assertRejected('r1', 'no-progress')

    def test_missing_worktree_is_rejected(self):
        self.request(worktree=str(self.root / 'nowhere'))
        self.core.poll_requests()
        self.assertRejected('r1', 'no-worktree')

    def test_dirty_worktree_is_rejected_unless_allowed(self):
        (self.repo / 'half-done.txt').write_text('x', encoding='utf-8')
        self.request()
        self.core.poll_requests()
        self.assertRejected('r1', 'dirty-worktree')
        self.start_run('r2', allow_dirty=True)

    def test_busy_or_unreconnectable_local_agent_is_rejected_without_side_effects(self):
        self.adapter.state = 'Busy'
        self.request()
        self.core.poll_requests()
        self.assertRejected('r1', 'local-not-connected')
        self.assertEqual([], self.core.list_projects())
        self.adapter.state = 'Disconnected'
        reconnects = []
        self.core.connect = lambda agent: reconnects.append(agent)   # the attempt does not help
        self.request('r2')
        self.core.poll_requests()
        self.assertRejected('r2', 'local-not-connected')
        self.assertEqual(['local'], reconnects, 'only the Disconnected agent was reconnected, once')
        self.assertEqual([], self.core.list_projects())

    def test_an_adapter_in_error_is_reconnected_once_before_the_request_is_judged(self):
        self.adapter.state = 'Error'
        reconnects = []
        def reconnect(agent):
            reconnects.append(agent)
            self.adapter.state = 'Connected'
        self.core.connect = reconnect
        self.start_run()
        self.assertEqual(['local'], reconnects)

    def test_relative_worktree_is_rejected(self):
        self.request(worktree='work-tree')
        self.core.poll_requests()
        self.assertRejected('r1', 'no-worktree')

    def test_a_label_may_not_start_with_a_dot(self):
        from acw.requests import LABEL
        self.assertIsNone(LABEL.fullmatch('.hidden'))
        self.assertIsNotNone(LABEL.fullmatch('a.b-c_1'))

    def test_a_withdrawn_request_is_skipped_quietly(self):
        self.assertEqual('retry', self.core.requests._begin(self.requests / 'gone.json', ('gone.json', 0)))
        self.assertEqual([], self.core.poll_requests())

    def test_heartbeat_is_written_before_the_slow_git_guard(self):
        seen = []
        real = self.core.requests._dirty
        def spy(worktree):
            beat = self.requests / '.dispatcher.json'
            seen.append(json.loads(beat.read_text(encoding='utf-8')) if beat.exists() else None)
            return real(worktree)
        beat = self.requests / '.dispatcher.json'
        self.core.requests._dirty = spy
        self.request()
        original = self.core.requests._heartbeat
        calls = []
        self.core.requests._heartbeat = lambda busy=None: (calls.append(busy), original(busy))[1]
        self.core.poll_requests()
        self.assertTrue(seen and seen[0] and seen[0]['busy'] is True, seen)
        self.assertGreaterEqual(calls.count(True), 4)   # git guard, launch start, prepare, send

    def test_monitor_root_of_the_wrong_type_is_ignored_not_fatal(self):
        self.start_run(monitor_root=123)
        self.say('message_end', content='done', status='complete')
        self.core.poll_requests()
        self.assertEqual('complete', self.result()['status'])
        self.assertFalse((self.monitor / 'logs' / 'hermes.log').exists())

    def test_an_exception_while_building_the_run_restores_settings_and_is_not_retried(self):
        self.request(run_budget=999, max_turns=9)
        with patch('acw.requests.MonitorProjection', side_effect=TypeError('boom')):
            self.core.poll_requests()
            self.core.poll_requests()
        self.assertRejected('r1', 'prepare-failed')
        self.assertEqual((600, 60), (self.adapter.settings['run_budget'], self.adapter.settings['max_turns']))
        self.assertEqual(1, len(self.core.store.query('SELECT id FROM tasks')), 'one task, no retry loop')
        self.assertIsNone(self.core.requests._run)
        self.assertIsNone(self.core.requests._active_task)

    def test_a_result_file_that_cannot_be_written_is_retried_on_the_next_poll(self):
        self.start_run()
        real = self.core.requests._write_result
        attempts = []
        def flaky(*args, **kwargs):
            attempts.append(1)
            if len(attempts) <= 3:
                raise OSError('locked')
            return real(*args, **kwargs)
        self.core.requests._write_result = flaky
        self.say('message_end', content='done', status='complete')
        with patch('acw.requests.time.sleep'):
            self.assertEqual([], self.core.poll_requests())
            self.assertEqual(3, len(attempts))
            self.assertIsNotNone(self.core.requests._run, 'the run is kept until its result is written')
            self.assertEqual((600, 60), (self.adapter.settings['run_budget'], self.adapter.settings['max_turns']))
            self.core.poll_requests()
        self.assertEqual('complete', self.result()['status'])
        self.assertIsNone(self.core.requests._run)

    def test_send_failure_is_rejected_and_limits_are_restored(self):
        self.adapter.fail_send = 'boom'
        self.request(run_budget=999, max_turns=9)
        self.core.poll_requests()
        result = self.assertRejected('r1', 'send-failed')
        self.assertIn('boom', result['reason'])
        self.assertEqual((600, 60), (self.adapter.settings['run_budget'], self.adapter.settings['max_turns']))
        # the dispatcher is free again
        self.adapter.fail_send = ''
        self.request('r2')
        self.core.poll_requests()
        self.assertEqual([compose_prompt(self.core, 'local', PROMPT)], self.adapter.sent)

    def test_bad_budget_is_rejected(self):
        self.request(run_budget='lots')
        self.core.poll_requests()
        self.assertRejected('r1', 'bad-request')

    def test_a_request_that_run_sh_has_stopped_waiting_for_is_expired(self):
        self.request(run_budget=10)
        path = self.requests / 'r1.json'
        old = path.stat().st_mtime - 3600
        os.utime(path, (old, old))
        self.core.poll_requests()
        self.assertRejected('r1', 'expired')

    # -- the normal flow
    def test_request_becomes_project_session_messages_and_a_complete_result(self):
        self.start_run(run_budget=1234, max_turns=42)
        projects = self.core.list_projects()
        self.assertEqual(1, len(projects))
        self.assertEqual('work-tree', projects[0]['name'])
        self.assertEqual(projects[0]['id'], self.core.agent_project('local')['id'])
        task = self.core.agent_task('local')
        self.assertEqual('Hermes · r1', task['title'])
        self.assertTrue(task['local_session'])
        self.assertIsNotNone(self.core.store.get('sessions', {'agent': 'local', 'id': task['local_session']}))
        self.assertEqual((1234, 42), self.adapter.limits_at_send)
        self.assertEqual((1234, 42), (self.adapter.settings['run_budget'], self.adapter.settings['max_turns']))

        self.say('message_delta', content='Starting the step.\n')
        self.say('message_delta', content='[DECISION NEEDED] 測試用\n')
        self.core.poll_requests()
        self.say('tool_start', name='terminal', tool_id='c1', input={'command': 'cat .env'})
        self.say('tool_result', name='terminal', tool_id='c1', content='API_KEY=sk-test-123456789\nTOOL_OUTPUT_MARKER',
                 is_error=False, duration_ms=12)
        self.say('message_delta', content='half a li')
        self.say('message_delta', content='ne\nRepetition Detected, stopping.\n')
        self.say('message_end', content='done', status='complete')
        self.core.poll_requests()

        result = self.result()
        self.assertEqual('complete', result['status'])
        self.assertEqual(0, result['exit_code'])
        self.assertEqual(task['id'], result['task_id'])
        self.assertEqual(task['local_session'], result['session_id'])
        self.assertEqual('r1', result['label'])
        self.assertTrue(result['started'] and result['ended'])
        self.assertFalse(list(self.requests.glob('*.tmp')))
        self.assertEqual((600, 60), (self.adapter.settings['run_budget'], self.adapter.settings['max_turns']))

        raw = self.hermes_log()
        self.assertFalse(raw.startswith(b'\xef\xbb\xbf'))
        self.assertNotIn(b'\n', raw.replace(b'\r\n', b''))
        lines = raw.decode('utf-8').split('\r\n')[:-1]
        self.assertEqual([
            'Starting the step.',
            '[DECISION NEEDED] 測試用',
            '[TOOL] terminal {"command": "cat .env"}',
            '[TOOL DONE] terminal 12ms error=false',
            'half a line',
            'Repetition Detected, stopping.',
            '[RESULT exit=0] done',
        ], lines)
        text = raw.decode('utf-8')
        self.assertNotIn('TOOL_OUTPUT_MARKER', text)
        self.assertNotIn('sk-test-123456789', text)

        events = [line.split(' | ') for line in self.timeline().splitlines()]
        self.assertEqual(['DECISION_NEEDED', 'REPETITION_DETECTED'], [e[3] for e in events])
        self.assertTrue(all(e[1] == 'r1' and e[2] == 'HERMES' for e in events))
        self.assertRegex(events[0][0], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$')
        self.assertIn('[DECISION NEEDED]', events[0][4])
        self.assertNotIn('RUN_STARTED', self.timeline())
        self.assertNotIn('RUN_ENDED', self.timeline())

        messages = self.core.messages(task['id'], 'local')
        self.assertEqual({'user', 'assistant', 'tool'}, {m['role'] for m in messages})
        stored = [e['type'] for e in self.core.events(task['id'], 'local')]
        self.assertIn('prompt_sent', stored)
        self.assertIn('message_end', stored)

    def test_a_second_request_for_the_same_worktree_reuses_the_project_but_gets_a_new_session(self):
        self.start_run('r1')
        first = self.core.agent_task('local')
        self.say('message_end', content='done', status='complete')
        self.core.poll_requests()
        self.assertEqual('complete', self.result('r1')['status'])
        self.adapter.sent.clear()
        self.start_run('r2')
        self.assertEqual(1, len(self.core.list_projects()))
        second = self.core.agent_task('local')
        self.assertNotEqual(first['id'], second['id'])
        self.assertNotEqual(first['local_session'], second['local_session'])

    def test_only_one_run_at_a_time(self):
        self.start_run('r1')
        self.request('r2')
        self.core.poll_requests()
        self.assertIsNone(self.result('r2'))
        self.assertEqual([compose_prompt(self.core, 'local', PROMPT)], self.adapter.sent)
        self.say('message_end', content='done', status='complete')
        self.core.poll_requests()
        self.assertEqual('complete', self.result('r1')['status'])
        self.core.poll_requests()
        self.assertEqual([compose_prompt(self.core, 'local', PROMPT)] * 2, self.adapter.sent)

    def test_without_a_monitor_root_nothing_is_projected(self):
        self.start_run(monitor_root='')
        self.say('message_delta', content='hello\n')
        self.say('message_end', content='done', status='complete')
        self.core.poll_requests()
        self.assertEqual('complete', self.result()['status'])
        self.assertFalse((self.monitor / 'logs' / 'hermes.log').exists())

    def test_interrupted_message_end_becomes_interrupted_after_one_grace_poll(self):
        self.start_run()
        self.say('message_end', content='', status='interrupted')
        self.core.poll_requests()
        self.assertIsNone(self.result())
        self.core.poll_requests()
        result = self.result()
        self.assertEqual('interrupted', result['status'])
        self.assertEqual(1, result['exit_code'])
        self.assertIn('[RESULT exit=1]', self.hermes_log().decode('utf-8'))

    def test_failure_after_start_is_an_error_result(self):
        self.start_run()
        self.say('message_end', content='', status='interrupted')
        self.say('error', content='Hermes 工作失敗（exit 1/1）')
        self.core.poll_requests()
        result = self.result()
        self.assertEqual('error', result['status'])
        self.assertIn('Hermes 工作失敗', result['reason'])
        self.assertEqual(1, result['exit_code'])
        self.assertIn('[ERROR] Hermes 工作失敗', self.hermes_log().decode('utf-8'))

    def test_a_run_without_a_completion_event_times_out_as_interrupted(self):
        self.start_run(run_budget=100)
        self.now[0] += 100 + 120
        self.core.poll_requests()
        self.assertIsNone(self.result())
        self.now[0] += 1
        self.core.poll_requests()
        result = self.result()
        self.assertEqual('interrupted', result['status'])
        self.assertEqual(['synthetic-send-result'], self.adapter.stopped)
        self.assertEqual((600, 60), (self.adapter.settings['run_budget'], self.adapter.settings['max_turns']))
        self.assertIn('[ERROR]', self.hermes_log().decode('utf-8'))

    def test_closing_the_core_answers_a_running_request_as_interrupted(self):
        self.start_run()
        self.core.close()
        result = self.result()
        self.assertEqual('interrupted', result['status'])
        self.assertEqual(['synthetic-send-result'], self.adapter.stopped)
        self.assertEqual((600, 60), (self.adapter.settings['run_budget'], self.adapter.settings['max_turns']))

    def test_every_poll_writes_a_heartbeat_that_reports_whether_a_run_is_active(self):
        heartbeat = self.requests / '.dispatcher.json'
        self.core.poll_requests()
        beat = json.loads(heartbeat.read_text(encoding='utf-8'))
        self.assertEqual(os.getpid(), beat['pid'])
        self.assertFalse(beat['busy'])
        self.assertRegex(beat['at'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$')
        self.start_run()
        self.assertTrue(json.loads(heartbeat.read_text(encoding='utf-8'))['busy'])
        self.say('message_end', content='done', status='complete')
        self.core.poll_requests()
        self.assertFalse(json.loads(heartbeat.read_text(encoding='utf-8'))['busy'])
        self.assertFalse(list(self.requests.glob('.dispatcher*.tmp')))
        self.assertFalse((self.requests / '.dispatcher.result.json').exists(), 'the heartbeat is not a request')
        self.core.close()
        self.assertFalse(heartbeat.exists(), 'closing the workspace withdraws the heartbeat')

    def test_a_failing_heartbeat_write_never_breaks_polling(self):
        with patch('acw.requests.os.replace', side_effect=OSError('disk full')):
            self.assertEqual([], self.core.poll_requests())

    def test_request_is_not_processed_twice_and_a_reused_label_runs_again(self):
        self.request()
        self.adapter.fail_send = 'nope'
        self.core.poll_requests()
        self.assertEqual('rejected', self.result()['status'])
        (self.requests / 'r1.result.json').unlink()
        self.core.poll_requests()
        self.assertIsNone(self.result(), 'the same request file must not be replayed')
        self.adapter.fail_send = ''
        self.request()
        path = self.requests / 'r1.json'
        later = path.stat().st_mtime + 5
        os.utime(path, (later, later))
        self.core.poll_requests()
        self.assertEqual([compose_prompt(self.core, 'local', PROMPT)], self.adapter.sent)


class MonitorProjectionTests(unittest.TestCase):
    """The Monitor projection must never print a secret that only becomes recognisable after later deltas."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='acw-projection-')
        self.root = Path(self.temp.name)
        (self.root / 'logs').mkdir()
        self.projection = MonitorProjection('p1', str(self.root))
        self.accumulated = ''

    def tearDown(self):
        self.temp.cleanup()

    def feed(self, *chunks):
        """Deliver deltas the way the core does: every event carries the whole redacted text so far."""
        for chunk in chunks:
            self.accumulated += chunk
            self.projection.event({'type': 'message_delta', 'content': sanitize(self.accumulated)}, 0)

    def written(self):
        path = self.root / 'logs' / 'hermes.log'
        return path.read_bytes().decode('utf-8') if path.exists() else ''

    def test_secret_prefix_split_across_deltas_is_never_printed(self):
        self.feed('key is sk-abcd', 'efghijkl rest\n')
        self.projection.flush()
        self.assertNotIn('sk-abcd', self.written())
        self.assertIn('rest', self.written())

    def test_secret_one_character_short_of_recognition_is_never_printed(self):
        self.feed('sk-abcdefg', 'h tail\n')
        self.projection.flush()
        self.assertNotIn('sk-abcd', self.written())
        self.assertIn('tail', self.written())

    def test_secret_in_an_unfinished_last_line_is_masked_on_flush(self):
        self.feed('sk-abcdefg', 'hijk')
        self.assertEqual('', self.written(), 'an unfinished line waits')
        self.projection.flush()
        self.assertNotIn('sk-abcd', self.written())
        self.assertTrue(self.written().strip())

    def test_flushed_partial_line_is_not_repeated_when_it_finishes(self):
        self.feed('first line\nhalf a li')
        self.projection.event({'type': 'tool_start', 'name': 'terminal', 'input': {'command': 'ls'}}, 0)
        self.feed('ne\nlast\n')
        self.projection.flush()
        self.assertEqual(['first line', 'half a li', '[TOOL] terminal {"command": "ls"}', 'ne', 'last'],
                         self.written().split('\r\n')[:-1])

    def test_every_projected_line_gets_the_direct_paths_masking(self):
        self.feed('curl --password hunter2x xoxb-1234567890-abcdef\n')
        self.projection.event({'type': 'tool_start', 'name': 'terminal', 'input': {'command': 'mysql -u root -pSECRETPW'}}, 0)
        self.projection.event({'type': 'message_end', 'content': 'Token abcdefghijk1 and mysecret=zzz'}, 0)
        self.projection.event({'type': 'error', 'content': 'AIza' + 'A' * 30}, 1)
        text = self.written()
        for leaked in ('hunter2x', 'xoxb-1234567890', 'SECRETPW', 'abcdefghijk1', 'zzz', 'AIzaAAAA'):
            self.assertNotIn(leaked, text)


class RealAdapterRequestTests(unittest.TestCase):
    """The same flow through the real HermesAdapter with only the child process replaced."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='acw-requests-real-')
        self.root = Path(self.temp.name)
        self.lock_env = patch.dict(os.environ, {'ACW_HERMES_LOCK': str(self.root / 'hermes.lock')})
        self.lock_env.start()
        self.repo = self.root / 'work-tree'
        (self.repo / 'briefs').mkdir(parents=True)
        (self.repo / 'briefs' / 'PROGRESS.md').write_text('step: A1\n', encoding='utf-8')
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True, stdin=subprocess.DEVNULL)
        git(self.repo, 'add', '-A')
        git(self.repo, 'commit', '-q', '-m', 'init')
        self.monitor = self.root / 'monitor'
        (self.monitor / 'logs').mkdir(parents=True)
        self.core = WorkspaceCore(self.root / 'data')
        self.core.git_snapshot = lambda *args, **kwargs: {'branch': 'fixture'}
        # subprocess.Popen is patched below for the child process; the dispatcher's own git call must not see it.
        self.core.requests._dirty = lambda worktree: ''
        self.adapter = HermesAdapter(lambda *args, **kwargs: None, executable='fixture-hermes.exe', run_budget=600, max_turns=60)
        self.core.set_adapter('local', self.adapter)
        self.adapter.state = 'Connected'

    def tearDown(self):
        self.adapter.disconnect()
        self.core.close()
        self.lock_env.stop()
        self.temp.cleanup()

    def test_real_adapter_run_is_projected_and_answered(self):
        events = [
            {'type': 'system', 'subtype': 'init', 'session_id': '20261011_010203_a1b2c3d4'},
            {'type': 'text', 'text': 'Starting the step.\n[DECISION NEEDED] question\n'},
            {'type': 'tool_use', 'name': 'terminal', 'tool_call_id': 'c1', 'input': {'command': 'cat .env'}},
            {'type': 'tool_result', 'name': 'terminal', 'tool_call_id': 'c1', 'output': 'TOOL_OUTPUT_MARKER password=hunter2',
             'duration_ms': 7, 'is_error': False},
            {'type': 'text', 'text': 'Finished.'},
            {'type': 'result', 'session_id': '20261011_010203_a1b2c3d4', 'text': 'All done.', 'exit_code': 0},
        ]
        requests = Path(self.core.data_dir) / 'requests'
        requests.mkdir(parents=True)
        (requests / 'real1.json').write_text(json.dumps({
            'label': 'real1', 'worktree': str(self.repo), 'briefs': 'briefs', 'prompt': PROMPT, 'run_budget': 1234,
            'max_turns': 42, 'allow_dirty': False, 'monitor_root': str(self.monitor),
            'created': '2026-10-15T14:00:00+08:00'}), encoding='utf-8')
        with patch('acw.adapters.hermes.subprocess.Popen', return_value=NativeProcessFixture(events)) as popen:
            self.core.poll_requests()
            argv = popen.call_args[0][0]
            self.assertEqual('1234', argv[argv.index('--run-budget') + 1])
            self.assertEqual('42', argv[argv.index('--max-turns') + 1])
            result = None
            deadline = time.time() + 10
            while result is None and time.time() < deadline:
                time.sleep(0.1)
                self.core.poll_requests()
                path = requests / 'real1.result.json'
                result = json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
        self.assertEqual('complete', result['status'], result)
        self.assertEqual((600, 60), (self.adapter.settings['run_budget'], self.adapter.settings['max_turns']))
        text = (self.monitor / 'logs' / 'hermes.log').read_text(encoding='utf-8')
        self.assertIn('Starting the step.', text)
        self.assertIn('[TOOL] terminal {"command": "cat .env"}', text)
        self.assertIn('[TOOL DONE] terminal 7ms error=false', text)
        self.assertIn('[RESULT exit=0] All done.', text)
        self.assertNotIn('TOOL_OUTPUT_MARKER', text)
        self.assertNotIn('hunter2', text)
        self.assertIn('DECISION_NEEDED', (self.monitor / 'logs' / 'timeline.log').read_text(encoding='utf-8'))
        self.assertEqual(result['session_id'], self.core.agent_task('local')['local_session'])
        self.assertFalse((self.root / 'hermes.lock').exists(), 'the adapter must release its lock')


if __name__ == '__main__':
    unittest.main()
