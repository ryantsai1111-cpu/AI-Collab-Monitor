"""Codex request-file dispatch through the real Core with isolated synthetic adapters."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acw import playbooks
from acw.core import WorkspaceCore
from test_core import SyntheticAdapter


class CodexRequestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        (self.repo / 'spec.md').write_text('Fixture specification', encoding='utf-8')
        self.monitor = self.root / 'monitor'
        self.monitor.mkdir()
        self.adapter = SyntheticAdapter('codex')
        self.adapter.capabilities.supports_approval = True
        self.adapter.approve = lambda request_id, approved: None
        self.core = WorkspaceCore(self.root / 'data', {'codex': self.adapter})
        self.addCleanup(self.core.close)
        self.core.git_snapshot = lambda *a, **k: {'branch': 'fixture'}
        self.adapter.state = 'Connected'
        self.now = [1000.0]
        self.core.requests.clock = lambda: self.now[0]
        self.core.requests._dirty = lambda path: ''
        self.directory = self.core.data_dir / 'requests'
        self.directory.mkdir(exist_ok=True)

    def request(self, label='c1', **override):
        body = dict(agent='codex', label=label, worktree=str(self.repo), spec='spec.md',
                    prompt='Implement the fixture specification', monitor_root=str(self.monitor))
        body.update(override)
        (self.directory / (label + '.json')).write_text(json.dumps(body), encoding='utf-8')
        self.core.poll_requests()

    def result(self, label='c1'):
        path = self.directory / (label + '.result.json')
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None

    def test_codex_dispatch_composes_playbook_keeps_settings_and_projects_result(self):
        settings = dict(self.adapter.settings)
        self.request(run_budget=99, max_turns=8)
        self.assertIsNone(self.result())
        self.assertEqual('codex', self.core.requests.agent)
        self.assertTrue(self.adapter.sent[0].startswith(playbooks.load(self.core, 'codex')['instructions']))
        self.assertEqual(settings, self.adapter.settings)
        user = self.core.messages(agent='codex')[0]
        self.assertEqual(self.adapter.sent[0], user['content'])
        self.adapter.emit('message_end', content='VERDICT: IMPLEMENTED\nDone', status='complete')
        self.core.poll_requests()
        self.assertIsNone(self.result())
        self.adapter.emit('event', summary='Turn completed', status='completed', turn_id='turn-1')
        self.core.poll_requests()
        self.assertEqual('complete', self.result()['status'])
        self.assertIn('[RESULT exit=0]', (self.monitor / 'logs/codex.log').read_text(encoding='utf-8'))
        self.assertFalse((self.monitor / 'logs/hermes.log').exists())
        self.assertIsNone(self.core.requests.active())

    def test_missing_escaping_and_absolute_specs_are_refused_before_creating_tasks(self):
        for index, spec in enumerate((None, '../outside.md', str(self.repo / 'spec.md'))):
            self.request('bad' + str(index), spec=spec)
            self.assertTrue(self.result('bad' + str(index))['reason'].startswith('no-spec:'))
        self.assertEqual([], self.core.list_projects())
        self.assertEqual([], self.adapter.sent)

    def test_approval_wait_pauses_timeout_and_records_each_transition_once(self):
        self.request(timeout_seconds=10)
        self.now[0] += 2
        self.adapter.emit('approval', request_id='approve-1', details='fixture command')
        self.adapter.emit('approval', request_id='approve-1', details='duplicate')
        self.adapter.emit('approval', request_id='approve-2', details='second command')
        self.now[0] += 100
        self.core.poll_requests()
        self.assertIsNone(self.result())
        self.core.approve('codex', 'approve-1', True)
        self.now[0] += 100
        self.core.poll_requests()
        self.assertIsNone(self.result())
        self.core.approve('codex', 'approve-2', False)
        self.core.poll_requests()
        timeline = (self.monitor / 'logs/timeline.log').read_text(encoding='utf-8')
        self.assertEqual(2, timeline.count('| CODEX | APPROVAL_NEEDED |'))
        self.assertEqual(2, timeline.count('| CODEX | APPROVAL_RESOLVED |'))
        self.now[0] += 8
        self.core.poll_requests()
        self.assertIsNone(self.result())
        self.now[0] += 1
        self.core.poll_requests()
        self.assertEqual('interrupted', self.result()['status'])
        self.assertIn('stop', self.adapter.calls)

    def test_use_playbook_false_sends_body_exactly(self):
        self.request(use_playbook=False)
        self.assertEqual(['Implement the fixture specification'], self.adapter.sent)

    def test_dynamic_instance_uses_own_playbook_and_shared_single_run_slot(self):
        instance = self.core.create_agent_instance('codex', 'Worker two')['id']
        adapter = SyntheticAdapter(instance)
        adapter.state = 'Connected'
        self.core.set_adapter(instance, adapter)
        playbooks.save(self.core, instance, {'instructions': 'Instance instructions', 'limits': {'timeout_seconds': 9}})
        self.request(agent=instance)
        self.assertTrue(adapter.sent[0].startswith('Instance instructions\n\n---\n\n'))
        self.request('c2')
        self.assertEqual([], self.adapter.sent)
        self.now[0] += 10
        self.core.poll_requests()
        self.assertEqual('interrupted', self.result()['status'])
        self.core.poll_requests()
        self.assertEqual(1, len(self.adapter.sent))

    def test_timeout_cancels_with_opaque_native_operation_token_not_turn_id(self):
        token = (7, 2, 'native-thread', 'native-turn', 12345)
        stopped = []
        self.adapter.active_operation_id = lambda: token
        self.adapter.stop_if_owned = lambda expected: stopped.append(expected)
        self.request(timeout_seconds=1)
        self.assertEqual(token, self.core.requests._run['operation'])
        self.now[0] += 2
        self.core.poll_requests()
        self.assertEqual([token], stopped)
        self.assertEqual('interrupted', self.result()['status'])

    def test_unsupported_agent_is_rejected(self):
        self.request(agent='claude')
        self.assertTrue(self.result()['reason'].startswith('bad-request:'))

    def test_full_turn_waits_for_terminal_and_projects_commands_without_output(self):
        self.request()
        self.adapter.set_state('Busy')
        self.adapter.emit('message_start')
        self.adapter.emit('message_delta', content='I will inspect the specification.\n')
        self.adapter.emit('message_end', content='I will inspect the specification.', status='completed')
        self.core.poll_requests()
        self.assertIsNone(self.result())
        self.adapter.emit('command', command='python -m unittest', status='inProgress', output='OUTPUT_CANARY')
        self.adapter.emit('approval', request_id='approval-1', details='fixture')
        self.core.poll_requests()
        self.assertIsNone(self.result())
        self.core.approve('codex', 'approval-1', True)
        self.adapter.emit('command', command='python -m unittest', status='completed', exit_code=0,
                          output='OUTPUT_CANARY', stdout='STDOUT_CANARY', stderr='STDERR_CANARY')
        buffered = list(self.core.requests._buffer)
        self.assertFalse(any(key in event for event in buffered for key in ('output', 'stdout', 'stderr')))
        self.adapter.emit('message_start')
        self.adapter.emit('message_delta', content='Implemented the specification.\nTests passed.')
        self.adapter.emit('message_end', content='Implemented the specification.\nTests passed.', status='completed')
        self.core.poll_requests()
        self.assertIsNone(self.result())
        self.adapter.emit('event', summary='Turn completed', status='completed', turn_id='turn-1')
        self.assertEqual('turn-1', self.core.requests._buffer[-1]['turn_id'])
        self.adapter.set_state('Connected')
        self.core.poll_requests()
        result = self.result()
        self.assertEqual(('complete', 'completed', 2), (result['status'], result['turn_status'], result['messages']))
        log = (self.monitor / 'logs/codex.log').read_text(encoding='utf-8')
        self.assertIn('I will inspect the specification.\n\n', log)
        self.assertIn('Implemented the specification.\nTests passed.\n\n', log)
        self.assertIn('[CMD] python -m unittest', log)
        self.assertIn('[CMD DONE] status=completed exit=0', log)
        self.assertEqual(1, log.count('[RESULT'))
        self.assertIn('[RESULT exit=0] Implemented the specification.', log)
        for canary in ('OUTPUT_CANARY', 'STDOUT_CANARY', 'STDERR_CANARY'):
            self.assertNotIn(canary, log)
        timeline = (self.monitor / 'logs/timeline.log').read_text(encoding='utf-8')
        for marker in ('APPROVAL_NEEDED', 'APPROVAL_RESOLVED', 'TURN_END | completed'):
            self.assertIn(marker, timeline)
        self.assertEqual(1, timeline.count('| TURN_END |'))

    def test_turn_failed_uses_last_error_and_other_terminal_statuses(self):
        for index, terminal in enumerate(('failed', 'unexpected', 'interrupted', 'cancelled')):
            label = 'terminal' + str(index)
            self.request(label)
            self.adapter.emit('error', content='first error')
            self.adapter.emit('error', content='actual last error')
            self.adapter.emit('event', summary='Turn ' + terminal, status=terminal)
            self.core.poll_requests()
            result = self.result(label)
            expected = 'interrupted' if terminal in ('interrupted', 'cancelled') else 'error'
            self.assertEqual(expected, result['status'])
            self.assertEqual(terminal, result['turn_status'])
            if expected == 'error':
                self.assertEqual('actual last error', result['reason'])

    def test_turn_failed_without_error_uses_turn_status(self):
        self.request()
        self.adapter.emit('event', summary='Turn failed', status='failed')
        self.core.poll_requests()
        self.assertEqual('Turn failed', self.result()['reason'])

    def test_busy_connected_fallback_requires_five_seconds_idle(self):
        self.request()
        self.adapter.set_state('Busy')
        self.adapter.emit('message_end', content='Done', status='completed')
        self.adapter.set_state('Connected')
        self.core.poll_requests()
        self.now[0] += 5
        self.core.poll_requests()
        self.assertIsNone(self.result())
        # Unprojected notifications must also extend the quiet period.
        self.adapter.emit('event', summary='unprojected activity')
        self.now[0] += 5
        self.core.poll_requests()
        self.assertIsNone(self.result())
        self.now[0] += 0.1
        self.core.poll_requests()
        self.assertEqual('complete', self.result()['status'])
        self.assertEqual('completed', self.result()['turn_status'])
        timeline = (self.monitor / 'logs/timeline.log').read_text(encoding='utf-8')
        self.assertIn('TURN_END_INFERRED', timeline)
        self.assertIn('TURN_END | completed', timeline)

    def test_fallback_requires_transition_and_no_pending_approvals(self):
        self.request()
        self.adapter.set_state('Connected')
        self.now[0] += 6
        self.core.poll_requests()
        self.assertIsNone(self.result())
        self.adapter.set_state('Busy')
        self.adapter.emit('approval', request_id='pending', details='fixture')
        self.adapter.set_state('Connected')
        self.now[0] += 10000
        self.core.poll_requests()
        self.assertIsNone(self.result())
        self.core.approve('codex', 'pending', False)
        self.core.poll_requests()
        self.assertIsNone(self.result())
        self.now[0] += 6
        self.core.poll_requests()
        self.assertEqual('complete', self.result()['status'])

    def test_projection_masks_metadata_and_omits_diff_and_test_output(self):
        self.request()
        self.adapter.emit('command', command='echo password=COMMAND_SECRET ' + 'x' * 180, status='inProgress')
        self.adapter.emit('file', path='password=PATH_SECRET', action={'type': 'update'})
        self.adapter.emit('diff', diff='diff --git a/a b/a\n+++ b/a\n+PATCH_CANARY\n')
        self.adapter.emit('test', framework='unittest', passed=2, failed=0, skipped=0,
                          exit_code=0, output='TEST_OUTPUT_CANARY', command='COMMAND_CANARY')
        buffered = list(self.core.requests._buffer)
        self.assertNotIn('PATCH_CANARY', json.dumps(buffered))
        self.assertNotIn('TEST_OUTPUT_CANARY', json.dumps(buffered))
        self.adapter.emit('message_end', content='password=REPLY_SECRET\nDone')
        self.adapter.emit('event', summary='Turn completed', status='completed')
        self.core.poll_requests()
        log = (self.monitor / 'logs/codex.log').read_text(encoding='utf-8')
        self.assertIn('[FILE] update', log)
        self.assertIn('[DIFF] 1 files', log)
        self.assertIn('[TEST] unittest passed=2 failed=0 skipped=0 exit_code=0', log)
        self.assertLessEqual(len(next(line for line in log.splitlines() if line.startswith('[CMD] '))[6:]), 120)
        for secret in ('COMMAND_SECRET', 'PATH_SECRET', 'PATCH_CANARY', 'TEST_OUTPUT_CANARY', 'COMMAND_CANARY', 'REPLY_SECRET'):
            self.assertNotIn(secret, log)

    def test_result_retry_does_not_duplicate_turn_projection(self):
        self.request()
        self.adapter.emit('message_end', content='Done')
        self.adapter.emit('event', summary='Turn completed', status='completed')
        with patch.object(self.core.requests, '_write_result', side_effect=OSError('fixture')), patch('acw.requests.time.sleep'):
            self.core.poll_requests()
        self.assertIsNone(self.result())
        self.core.poll_requests()
        self.assertEqual(('completed', 1), (self.result()['turn_status'], self.result()['messages']))
        log = (self.monitor / 'logs/codex.log').read_text(encoding='utf-8')
        self.assertEqual(1, log.count('[RESULT'))

    def test_interrupted_turn_counts_unfinished_message_and_summarizes_latest_text(self):
        self.request()
        self.adapter.emit('message_start')
        self.adapter.emit('message_end', content='Earlier commentary')
        self.adapter.emit('message_start')
        self.adapter.emit('message_delta', content='Latest partial response')
        self.adapter.emit('event', summary='Turn interrupted', status='interrupted')
        self.core.poll_requests()
        self.assertEqual(('interrupted', 2), (self.result()['status'], self.result()['messages']))
        log = (self.monitor / 'logs/codex.log').read_text(encoding='utf-8')
        self.assertIn('[RESULT exit=1] Latest partial response', log)
