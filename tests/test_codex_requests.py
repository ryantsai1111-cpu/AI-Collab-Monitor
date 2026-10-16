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
