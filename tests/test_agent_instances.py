"""Independent same-provider instances, persistent bindings and offline UI routing."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QDialog, QLineEdit

from acw.core import WorkspaceCore
from acw.orchestrator import Orchestrator
from acw.agents import load_instances
from test_ui_refresh import OfflineAdapter, OfflineWindow
from test_orchestrator import Scripted


class AgentInstanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.core = WorkspaceCore(Path(self.temp.name) / 'data')
        self.core.git_snapshot = lambda *_: {'branch': '', 'status': '', 'diff': '', 'log': '', 'is_git': False}
        for agent in self.core.agent_ids:
            self.core.set_adapter(agent, OfflineAdapter(agent))
        self.project = self.core.create_project('Instance project', self.temp.name)
        self.core.select_project(self.project['id'], sync=False)
        self.task = self.core.create_task('Shared task')
        self.window = None

    def tearDown(self):
        if self.window:
            self.window.timer.stop()
            self.window.sync_timer.stop()
            self.window.close()
        self.core.close()
        self.temp.cleanup()

    def add(self, provider='claude', name='Worker'):
        record = self.core.create_agent_instance(provider, name, project_id=self.project['id'])
        agent = record['id']
        self.core.set_adapter(agent, OfflineAdapter(agent))
        self.core.select_agent_task(agent, self.task['id'])
        self.core.connect(agent)
        self.core.create_session(agent)
        return agent

    def test_creation_constructs_distinct_disconnected_adapters_without_side_effects(self):
        self.core.set_setting('agent.claude', {'default_model': 'fixture-model-a'})
        a = self.core.create_agent_instance('claude', 'Research')['id']
        b = self.core.create_agent_instance('claude', 'Build')['id']
        self.assertNotEqual(a, b)
        self.assertIsNot(self.core.adapters[a], self.core.adapters[b])
        self.assertEqual('Disconnected', self.core.adapters[a].state)
        self.assertIsNone(self.core.agent_project(a))
        self.assertIsNone(self.core.agent_task(a))
        self.assertFalse(self.core.messages(agent=a))
        self.assertEqual([], self.core.adapters['claude'].calls)
        self.core.set_setting('agent.' + a, {'default_model': 'changed'})
        self.assertEqual('fixture-model-a', self.core.get_setting('agent.' + b)['default_model'])

    def test_same_task_keeps_separate_bindings_and_interleaved_streams(self):
        a, b = self.add(), self.add()
        sid_a = self.core.agent_task(a)[a + '_session']
        sid_b = self.core.agent_task(b)[b + '_session']
        self.assertNotEqual(sid_a, sid_b)
        for agent, content in ((a, 'Alpha'), (b, 'Beta')):
            self.core.ingest_event(agent, 'message_start')
            self.core.ingest_event(agent, 'message_delta', delta=content)
        self.core.ingest_event(b, 'message_end')
        self.core.ingest_event(a, 'message_end')
        self.assertEqual(['Alpha'], [m['content'] for m in self.core.messages(agent=a)])
        self.assertEqual(['Beta'], [m['content'] for m in self.core.messages(agent=b)])
        self.assertEqual(sid_a, self.core.messages(agent=a)[0]['session_id'])

    def test_binding_and_profile_survive_restart_without_schema_changes(self):
        schema = self.core.store.query('PRAGMA table_info(tasks)')
        a = self.add('local', 'Local research')
        sid = self.core.agent_task(a)[a + '_session']
        folder = self.core.data_dir
        self.core.close()
        self.core = WorkspaceCore(folder)
        self.assertEqual('local', self.core.provider(a))
        self.assertEqual('Local research', self.core.agent_name(a))
        self.assertEqual(sid, self.core.agent_task(a)[a + '_session'])
        self.assertEqual({}, self.core.adapters)
        self.assertEqual(schema, self.core.store.query('PRAGMA table_info(tasks)'))

    def test_another_instance_cannot_resume_a_connected_native_session(self):
        a, b = self.add(), self.add()
        adapter = self.core.adapters[b]
        adapter.calls.clear()
        with self.assertRaisesRegex(RuntimeError, 'already connected'):
            self.core.resume_session(b, self.core.adapters[a].session_id)
        self.assertFalse(any(call[0] == 'resume_session' for call in adapter.calls))

    def test_concurrent_resume_reserves_native_identity_before_backend_reply(self):
        a, b = self.add(), self.add()
        entered, release = threading.Event(), threading.Event()
        errors = []
        original = self.core.adapters[a].resume_session
        def blocked(session_id):
            entered.set()
            if not release.wait(5):
                raise TimeoutError('Fixture did not release resume')
            return original(session_id)
        def resume():
            try:
                self.core.resume_session(a, 'shared-native')
            except Exception as exc:
                errors.append(exc)
        with patch.object(self.core.adapters[a], 'resume_session', blocked):
            thread = threading.Thread(target=resume)
            thread.start()
            try:
                self.assertTrue(entered.wait(5))
                with self.assertRaisesRegex(RuntimeError, 'in use'):
                    self.core.resume_session(b, 'shared-native')
            finally:
                release.set()
                thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual([], errors)

    def test_refused_duplicate_send_records_failure_without_backend_dispatch(self):
        a, b = self.add(), self.add()
        session = self.core.adapters[a].session_id
        self.core.adapters[b].session_id = session
        self.core._set_task_session(self.task['id'], b, session)
        with self.assertRaisesRegex(RuntimeError, 'already connected'):
            self.core.send_message(b, 'Must not reach backend')
        self.assertFalse(any(call[0] == 'send' for call in self.core.adapters[b].calls))
        self.assertEqual('failed', self.core.messages(agent=b)[-1]['status'])

    def test_change_one_project_does_not_move_another_instance(self):
        a, b = self.add(), self.add()
        self.core.adapters[a].state = 'Busy'
        other = self.core.create_project('Other', self.temp.name)
        self.core.select_agent_project(b, other['id'])
        self.assertEqual(self.project['id'], self.core.agent_project(a)['id'])
        self.assertEqual(other['id'], self.core.agent_project(b)['id'])
        self.core.adapters[a].state = 'Connected'

    def test_all_claude_run_routes_to_two_instances_and_lead_verifies(self):
        a, b = self.add(), self.add()
        for agent, replies in ((a, ['VERDICT: PLAN_READY\nplan', 'VERDICT: APPROVED\nverified']),
                               (b, ['VERDICT: IMPLEMENTED\nimplementation'])):
            adapter = Scripted(agent, replies)
            adapter.core = self.core
            adapter.state = 'Connected'
            self.core.set_adapter(agent, adapter)
            self.core.create_session(agent)
        def dispatch(operation, done, failed):
            try:
                result = operation()
            except Exception as exc:
                failed(str(exc))
            else:
                done(result)
        run = Orchestrator(self.core, 'Implement and verify', dispatch, lead=a, implementer=b)
        run.start()
        for _ in range(5):
            run.tick()
        self.assertEqual('done', run.state, run.reason)
        self.assertEqual({a, b}, set(run.agents))
        self.assertEqual(2, len(self.core.adapters[a].sent))
        self.assertEqual(1, len(self.core.adapters[b].sent))
        self.assertFalse(self.core.adapters['codex'].calls)

    def test_lead_and_worker_must_be_distinct_instances(self):
        a = self.add()
        with self.assertRaises(ValueError):
            Orchestrator(self.core, 'task', lambda *_: None, lead=a, implementer=a)

    def test_add_panel_preserves_drafts_and_monitor_navigation(self):
        self.window = OfflineWindow(self.core)
        self.window.panels['claude'].input.setPlainText('Unsent original draft')
        a = self.window.add_agent_instance('claude', 'Claude reviewer', project_id=self.project['id'])
        self.assertIn(a, self.window.panels)
        self.assertEqual('claude', self.window.panels[a].provider)
        self.assertEqual('Unsent original draft', self.window.panels['claude'].input.toPlainText())
        self.assertEqual('', self.window.panels[a].input.toPlainText())
        self.assertEqual('Claude reviewer', self.window.monitor_dashboard.cards[a].title.text())
        self.window.mode.setCurrentIndex(self.window.mode.findData('Monitor'))
        self.window.monitor_dashboard.cards[a].action.click()
        self.assertEqual(a, self.window._preferred_agent)
        self.assertEqual('Workspace', self.window.mode.currentData())

    def test_local_settings_editors_are_independent(self):
        self.window = OfflineWindow(self.core)
        a = self.window.add_agent_instance('local', 'Local A')
        b = self.window.add_agent_instance('local', 'Local B')
        def edit(dialog):
            providers = dialog.findChildren(QLineEdit, 'hermes_provider')
            self.assertEqual(3, len(providers))
            for field in providers:
                name = 'provider-a' if field.property('agent_id') == a else 'provider-b' if field.property('agent_id') == b else 'provider-default'
                field.setText(name)
            return QDialog.Accepted
        with patch('acw.ui.QDialog.exec', edit):
            self.window.settings()
        self.assertEqual('provider-a', self.core.get_setting('agent.' + a)['provider'])
        self.assertEqual('provider-b', self.core.get_setting('agent.' + b)['provider'])

    def test_instance_registry_rejects_unsafe_or_duplicate_ids(self):
        for value in ({}, [{'id': '../bad', 'provider': 'claude', 'name': 'bad'}]):
            with self.assertRaises(ValueError):
                load_instances(value)
