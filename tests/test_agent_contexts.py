"""Role-local projects, sessions, histories and concurrent event routing; no live I/O."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
from acw.core import AGENTS, WorkspaceCore
from tests.test_ui_refresh import OfflineAdapter, OfflineWindow


class AgentContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.adapters = {agent: OfflineAdapter(agent) for agent in AGENTS}
        self.core = WorkspaceCore(self.root / 'data', self.adapters)
        self.addCleanup(lambda: self.core.close())
        self.git = patch.object(self.core, 'git_snapshot', return_value={'branch': 'fixture'})
        self.git.start()
        self.addCleanup(self.git.stop)
        self.guard = patch('subprocess.Popen', side_effect=AssertionError('No backend process allowed'))
        self.guard.start()
        self.addCleanup(self.guard.stop)
        self.projects = {}
        self.tasks = {}
        for agent in AGENTS:
            repo = self.root / agent
            repo.mkdir()
            project = self.core.create_project(agent + ' project', repo)
            self.projects[agent] = project
            self.tasks[agent] = self.core.create_task(agent + ' task', project['id'], select=False)
        self.core.select_task(self.tasks['claude']['id'])

    def select_all(self):
        for agent in AGENTS:
            self.core.select_agent_task(agent, self.tasks[agent]['id'])

    def connect_session(self, agent):
        self.core.connect(agent)
        if agent == 'dot':
            sid = self.adapters[agent].target
            self.core.resume_session(agent, sid)
            return sid
        return self.core.create_session(agent)['id']

    def window(self):
        window = OfflineWindow(self.core)
        def close():
            for panel in window.panels.values(): panel.set_state('Disconnected')
            window.close()
        self.addCleanup(close)
        return window

    def test_all_roles_connect_and_map_sessions_to_their_own_projects(self):
        self.select_all()
        for agent in AGENTS:
            sid = self.connect_session(agent)
            task = self.core.agent_task(agent)
            self.assertEqual(self.tasks[agent]['id'], task['id'])
            self.assertEqual(sid, task[agent + '_session'])
            saved = self.core.store.get('sessions', {'id': sid, 'agent': agent})
            self.assertEqual(self.projects[agent]['id'], saved['project_id'])
            self.assertEqual(task['id'], saved['task_id'])
            self.assertEqual('' if agent == 'dot' else self.projects[agent]['repo_path'], self.adapters[agent].cwd)
        self.assertEqual(self.tasks['claude']['id'], self.core.current_task_id)

    def test_switching_codex_preserves_other_roles_and_their_event_contexts(self):
        self.select_all()
        for agent in AGENTS: self.connect_session(agent)
        self.core.send_message('claude', 'Claude prompt')
        self.adapters['claude'].state = 'Busy'
        self.core.ingest_event('claude', 'message_start')
        before = {agent: (self.core.agent_task(agent)['id'], self.adapters[agent].cwd,
                          self.adapters[agent].session_id, dict(self.core._context(agent)))
                  for agent in ('claude', 'dot', 'local')}
        self.core.select_agent_project('codex', self.projects['local']['id'])
        task = self.core.create_agent_task('codex', 'Another Codex task')
        self.core.create_session('codex')
        self.core.ingest_event('claude', 'message_end', content='Claude answer')
        for agent, expected in before.items():
            actual = (self.core.agent_task(agent)['id'], self.adapters[agent].cwd,
                      self.adapters[agent].session_id, dict(self.core._context(agent)))
            self.assertEqual(expected, actual)
        self.assertEqual(task['id'], self.core.agent_task('codex')['id'])
        self.assertEqual('Claude answer', self.core.messages(agent='claude')[-1]['content'])
        self.assertEqual(self.tasks['claude']['id'], self.core.messages(agent='claude')[-1]['task_id'])

    def test_busy_role_cannot_switch_itself_but_another_role_can(self):
        self.select_all()
        for state in ('Busy', 'Connecting'):
            self.adapters['codex'].state = state
            with self.assertRaises(RuntimeError):
                self.core.select_agent_project('codex', self.projects['local']['id'])
            self.core.select_agent_task('local', self.tasks['local']['id'])
            self.assertEqual(self.tasks['codex']['id'], self.core.agent_task('codex')['id'])

    def test_project_without_task_cannot_send_to_the_global_task(self):
        self.connect_session('codex')
        self.core.select_agent_project('codex', self.projects['codex']['id'])
        self.assertIsNone(self.core.agent_task('codex'))
        with self.assertRaises(ValueError): self.core.send_message('codex', 'Wrong target')
        self.assertEqual([], self.core.messages(agent='codex'))
        self.assertEqual([], self.core.events(agent='codex'))

    def test_selected_contexts_survive_restart_without_connecting_or_resuming(self):
        self.select_all()
        for agent in AGENTS: self.connect_session(agent)
        self.core.close()
        adapters = {agent: OfflineAdapter(agent) for agent in AGENTS}
        self.core = WorkspaceCore(self.root / 'data', adapters)
        for agent in AGENTS:
            self.assertEqual(self.projects[agent]['id'], self.core.agent_project(agent)['id'])
            self.assertEqual(self.tasks[agent]['id'], self.core.agent_task(agent)['id'])
            self.assertEqual([], adapters[agent].calls)
            self.assertEqual('', adapters[agent].session_id)

    def test_global_navigation_does_not_replace_an_independent_role(self):
        self.core.select_agent_task('codex', self.tasks['codex']['id'])
        self.connect_session('codex')
        self.core.select_project(self.projects['local']['id'])
        self.core.select_task(self.tasks['local']['id'])
        self.assertEqual(self.tasks['codex']['id'], self.core.agent_task('codex')['id'])
        self.assertEqual(self.projects['codex']['repo_path'], self.adapters['codex'].cwd)
        self.assertEqual(self.tasks['local']['id'], self.core.agent_task('claude')['id'])

    def test_resume_rejects_a_session_from_another_project_before_backend_call(self):
        self.select_all()
        sid = self.connect_session('codex')
        self.core.select_agent_task('codex', self.tasks['local']['id'])
        calls = list(self.adapters['codex'].calls)
        with self.assertRaises(ValueError): self.core.resume_session('codex', sid)
        self.assertEqual(calls, self.adapters['codex'].calls)

    def test_discovery_and_native_preview_use_the_agent_project(self):
        self.select_all()
        self.core.connect('codex')
        row = {'id': 'fixture-native', 'cwd': self.projects['codex']['repo_path']}
        with patch.object(self.adapters['codex'], 'list_sessions', return_value=[row]), \
             patch.object(self.adapters['codex'], 'native_history_capability', create=True,
                          return_value={'supported': True}), \
             patch.object(self.adapters['codex'], 'get_history', return_value=['fixture']) as history:
            self.assertEqual([row], self.core.discover_sessions('codex'))
            self.assertEqual(['fixture'], self.core.native_history('codex', row['id']))
        history.assert_called_once_with('fixture-native', native=True, limit=200, offset=0)

    def test_attachment_scope_follows_the_sending_role(self):
        self.select_all()
        self.connect_session('codex')
        own = Path(self.projects['codex']['repo_path']) / 'fixture.txt'
        other = Path(self.projects['claude']['repo_path']) / 'fixture.txt'
        for path in (own, other): path.write_text('fixture', encoding='utf-8')
        self.core.send_message('codex', 'Own attachment', attachments=[str(own)])
        with self.assertRaises((ValueError, PermissionError)):
            self.core.send_message('codex', 'Other attachment', attachments=[str(other)])

    def test_handoff_targets_selected_role_task_and_detects_target_changes(self):
        self.select_all()
        for agent in ('claude', 'codex'): self.connect_session(agent)
        self.core.ingest_event('claude', 'message_end', content='Source answer')
        source = self.core.messages(agent='claude')[-1]
        preview = self.core.prepare_handoff(source['id'], 'codex')
        self.assertEqual(self.tasks['codex']['id'], preview['metadata']['target_task_id'])
        self.core.send_handoff(preview)
        self.assertEqual(self.tasks['codex']['id'], self.core.messages(agent='codex')[-1]['task_id'])
        other = self.core.prepare_handoff(source['id'], 'codex')
        self.core.select_agent_task('codex', self.tasks['local']['id'])
        with self.assertRaises(ValueError): self.core.send_handoff(other)

    def test_panel_project_and_task_selectors_only_change_the_selected_role(self):
        window = self.window()
        panel = window.panels['codex']
        panel.project.setCurrentIndex(panel.project.findData(self.projects['codex']['id']))
        self.assertIsNone(self.core.agent_task('codex'))
        panel.task.setCurrentIndex(panel.task.findData(self.tasks['codex']['id']))
        self.assertEqual(self.tasks['codex']['id'], self.core.agent_task('codex')['id'])
        for agent in ('claude', 'dot', 'local'):
            self.assertEqual(self.tasks['claude']['id'], self.core.agent_task(agent)['id'])
        self.assertIn('codex project', panel.context_button.text())
        self.assertEqual([], window.reported_errors)

    def test_role_switch_preserves_other_drafts_and_restores_its_own_draft(self):
        window = self.window()
        for agent in AGENTS: window.panels[agent].input.setPlainText(agent + ' draft')
        panel = window.panels['codex']
        panel.project.setCurrentIndex(panel.project.findData(self.projects['codex']['id']))
        self.assertEqual('', panel.input.toPlainText())
        for agent in ('claude', 'dot', 'local'):
            self.assertEqual(agent + ' draft', window.panels[agent].input.toPlainText())
        self.core.select_agent_task('codex', self.tasks['claude']['id'])
        window.reload_context()
        self.assertEqual('codex draft', panel.input.toPlainText())

    def test_concurrent_outputs_are_displayed_in_their_own_panels(self):
        self.select_all()
        for agent in AGENTS: self.connect_session(agent)
        window = self.window()
        self.core.drain_events()
        for agent in AGENTS:
            self.core.ingest_event(agent, 'message_end', content=agent + ' answer')
        window.poll_events()
        for agent in AGENTS:
            contents = [card.message['content'] for card in window.panels[agent].cards.values()]
            self.assertEqual([agent + ' answer'], contents)
        self.assertEqual([], window.reported_errors)

    def test_other_busy_role_does_not_block_project_choice_in_ui(self):
        window = self.window()
        window.panels['claude'].set_state('Busy')
        self.adapters['claude'].state = 'Busy'
        panel = window.panels['codex']
        panel.project.setCurrentIndex(panel.project.findData(self.projects['codex']['id']))
        self.assertEqual(self.projects['codex']['id'], self.core.agent_project('codex')['id'])
        self.assertEqual([], window.reported_errors)

    def test_opening_codex_native_session_preserves_another_busy_role(self):
        self.select_all()
        for agent in AGENTS: self.connect_session(agent)
        window = self.window()
        self.adapters['claude'].state = 'Busy'
        window.panels['claude'].set_state('Busy')
        before = list(self.adapters['claude'].calls)
        sid = '11111111-2222-4333-8444-555555555555'
        record = {'agent': 'codex', 'id': sid, 'cwd': self.projects['codex']['repo_path'], 'title': 'Chosen Codex thread'}
        with patch('acw.desktop_sessions.read_history', return_value=[]):
            window.open_desktop_session(record, resume=True)
        self.assertEqual(sid, self.core.agent_task('codex')['codex_session'])
        self.assertIn(('resume_session', sid), self.adapters['codex'].calls)
        self.assertEqual(before, self.adapters['claude'].calls)
        self.assertEqual(self.tasks['claude']['id'], self.core.agent_task('claude')['id'])
        self.assertEqual(self.tasks['claude']['id'], self.core.current_task_id)
        self.assertEqual([], window.reported_errors)

    def test_real_codex_adapter_protocol_uses_its_own_project_for_new_and_resume(self):
        from tests.test_codex import ProtocolTestAdapter
        adapter = ProtocolTestAdapter()
        adapter.capabilities.supports_sessions = True
        self.core.set_adapter('codex', adapter)
        self.core.select_agent_task('codex', self.tasks['codex']['id'])
        cwd = self.projects['codex']['repo_path']
        adapter.responses['thread/start'] = {'thread': {'id': 'fixture-thread', 'cwd': cwd}}
        self.assertEqual('fixture-thread', self.core.create_session('codex'))
        self.assertIn(('thread/start', {'cwd': cwd, 'approvalsReviewer': 'user'}), adapter.requests)
        adapter.responses['thread/read'] = {'thread': {'id': 'fixture-thread', 'cwd': cwd}}
        adapter.responses['thread/resume'] = {'thread': {'id': 'fixture-thread', 'cwd': cwd}}
        self.assertEqual('fixture-thread', self.core.resume_session('codex', 'fixture-thread'))
        self.assertEqual(self.tasks['codex']['id'], self.core.agent_task('codex')['id'])
        self.assertEqual(self.projects['claude']['id'], self.core.current_project_id)

    def test_auto_collaboration_rejects_different_role_tasks_before_any_send(self):
        from acw.orchestrator import Orchestrator
        self.select_all()
        for agent in AGENTS: self.connect_session(agent)
        run = Orchestrator(self.core, 'fixture', lambda *args: self.fail('No dispatch expected'))
        with self.assertRaises(ValueError): run.start()
        self.assertEqual('idle', run.state)
        self.assertFalse(any(call[0] == 'send' for adapter in self.adapters.values() for call in adapter.calls))

    def test_git_poll_does_not_overwrite_another_project_branch_label(self):
        self.select_all()
        window = self.window()
        panel = window.panels['codex']
        panel.branch_label.setText('Codex branch fixture')
        window._git_clock = 99
        window.poll_events()
        self.assertEqual('Codex branch fixture', panel.branch_label.text())

    def test_real_worker_blocks_its_role_and_shared_navigation_until_finished(self):
        from acw.ui import MainWindow
        window = self.window()
        started, release = threading.Event(), threading.Event()
        def operation():
            started.set()
            release.wait(5)
        try:
            MainWindow.run(window, operation, agent='codex')
            self.assertTrue(started.wait(2))
            self.assertFalse(window.panels['codex'].project.isEnabled())
            self.assertTrue(window.panels['claude'].project.isEnabled())
            self.assertFalse(window.confirm_context_change())
            self.assertFalse(window.confirm_agent_context_change('codex'))
            self.assertTrue(window.confirm_agent_context_change('claude'))
        finally:
            release.set()
            deadline = time.monotonic() + 3
            while window.workers and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.01)
        self.assertFalse(window.workers)
        self.assertTrue(window.panels['codex'].project.isEnabled())


if __name__ == '__main__':
    unittest.main()
