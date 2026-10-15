"""Fourth-role UI acceptance using the established offline substitutes."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QLabel, QLineEdit, QMenu, QPushButton, QSpinBox, QTabWidget

from acw.core import WorkspaceCore
from acw.store import now
from acw.ui import AGENTS, MessageCard
from tests.test_hermes_core import NativeProcessFixture
from tests.test_ui_refresh import OfflineAdapter, OfflineWindow


def offline_window(root):
    adapters = {agent: OfflineAdapter(agent) for agent in AGENTS}
    core = WorkspaceCore(root / 'data', adapters)
    core.git_snapshot = lambda *args, **kwargs: {
        'branch': 'fixture-branch', 'dirty': False, 'ahead': 0, 'behind': 0,
        'status': '', 'diff': '', 'log': '', 'is_git': False, 'error': ''}
    project = core.create_project('Offline UI acceptance', root)
    core.select_project(project['id'], sync=False)
    core.create_task('Local LLM panel acceptance')
    core.drain_events()
    return core, adapters, OfflineWindow(core)


class LocalUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.guards = [patch(target, side_effect=AssertionError('External I/O forbidden'))
                       for target in ('subprocess.Popen', 'socket.socket.connect', 'urllib.request.urlopen')]
        for guard in self.guards:
            guard.start()
        self.temp = tempfile.TemporaryDirectory()
        # The shared run.sh mutex is redirected so fixtures never touch the machine lock.
        self.lock_env = patch.dict(os.environ, {'ACW_HERMES_LOCK': str(Path(self.temp.name) / 'hermes.lock')})
        self.lock_env.start()
        self.core, self.adapters, self.window = offline_window(Path(self.temp.name))
        self.window.show()
        self.settle()

    def tearDown(self):
        self.window.timer.stop()
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.core.close()
        self.lock_env.stop()
        self.temp.cleanup()
        for guard in reversed(self.guards):
            guard.stop()

    def settle(self):
        for _ in range(4):
            self.app.processEvents()
        QTest.qWait(10)

    def test_startup_and_event_poll_never_call_local_adapter(self):
        self.assertEqual([], self.adapters['local'].calls)
        self.window.poll_events()
        self.settle()
        self.assertEqual([], self.adapters['local'].calls)
        self.assertEqual('Hermes', self.window.session_tabs.tabText(3))
        self.assertIn('Hermes', self.window.role_tabs.tabText(3))
        panel = self.window.panels['local']
        self.assertIn('工具權限由 Hermes 管理', panel.notice.text())
        self.assertTrue(panel.connect_button.isEnabled())
        self.assertTrue(panel.approval_button.isHidden())
        self.assertFalse(panel.approval_button.isEnabled())
        self.assertFalse(any(action.text() == '核准方式' for action in panel.more_button.menu().actions()))

    def test_unavailable_local_adapter_does_not_break_legacy_feedback_detection(self):
        adapter = self.core.adapters.pop('local')
        try:
            self.assertIsNone(self.core.legacy_local_conversation('local'))
            self.window.panels['local'].update_controls()
            self.assertEqual('', self.window.panels['local'].send_feedback.text())
        finally:
            self.core.adapters['local'] = adapter

    def test_auto_layout_four_visible_wide_one_visible_narrow_without_scroll(self):
        self.window.layout_mode.setCurrentIndex(self.window.layout_mode.findData('Auto'))
        self.window.resize(1900, 950)
        self.settle()
        self.window.update_workspace_layout()
        self.assertEqual(4, sum(panel.isVisible() for panel in self.window.panels.values()))
        for panel in self.window.panels.values():
            self.assertGreaterEqual(panel.width(), 300)
            self.assertTrue(panel.title.isVisible())
            self.assertTrue(panel.input.isVisible())
        self.window.resize(760, 720)
        self.settle()
        self.window.update_workspace_layout()
        self.assertEqual(1, sum(panel.isVisible() for panel in self.window.panels.values()))
        self.assertEqual(0, self.window.workspace_scroll.horizontalScrollBar().maximum())
        self.window.role_tabs.setCurrentIndex(3)
        self.settle()
        self.assertTrue(self.window.panels['local'].isVisible())
        self.assertEqual(0, self.window.workspace_scroll.horizontalScrollBar().maximum())

    def test_forward_menu_contains_local_and_flow_still_has_two_steps(self):
        panel = self.window.panels['claude']
        card = MessageCard({'id': 'fixture-message', 'role': 'assistant', 'content': 'Fixture response'}, panel)
        labels = [action.text() for action in card.forward_button.menu().actions()]
        self.assertEqual(['G8毛', 'Codex', 'Hermes'], labels)
        menu = QMenu(self.window)
        self.window.populate_flow_menu(menu)
        self.assertEqual(4, len(menu.actions()))
        self.assertIn('Claude', menu.actions()[0].text())
        self.assertIn('G8毛', menu.actions()[1].text())
        self.assertFalse(any('Hermes' in action.text() for action in menu.actions()))

    def test_local_connect_does_not_resume_a_missing_saved_session(self):
        self.core.set_setting('agent.local', {'base_url': 'http://localhost:1234', 'model': 'fixture-local'})
        self.core.create_session('local')
        task = self.core.agent_task('local')
        sid = task['local_session']
        self.adapters['local'].calls.clear()
        self.window.refresh_agent('local')
        self.window.panels['local'].connect_agent()
        self.assertEqual([('connect',)], self.adapters['local'].calls)
        self.assertEqual('Connected', self.window.panels['local'].connection_state)
        self.assertEqual(sid, self.core.get_task(task['id'])['local_session'])

    def test_cli_probe_checks_unsaved_values_without_saving_or_connecting(self):
        before = self.core.get_setting('agent.local', {})
        def inspect(dialog):
            dialog.findChild(QLineEdit, 'executable_local').setText('C:/fixture/hermes.exe')
            dialog.findChild(QLineEdit, 'hermes_provider').setText('fixture-provider')
            dialog.findChild(QLineEdit, 'hermes_model').setText('fixture-model')
            trigger = dialog.findChild(QPushButton, 'hermes_probe')
            trigger.click()
            output = dialog.findChild(QLabel, 'hermes_probe_result')
            self.assertIn('Missing required CLI options', output.text())
            self.assertTrue(trigger.isEnabled())
            return QDialog.Rejected
        with patch('acw.adapters.hermes.HermesAdapter.probe', autospec=True,
                   side_effect=RuntimeError('Missing required CLI options')) as probe, \
             patch.object(QDialog, 'exec', inspect):
            self.window.settings(agent='local')
        probe.assert_called_once()
        candidate = probe.call_args.args[0]
        self.assertEqual('C:/fixture/hermes.exe', candidate.executable)
        self.assertEqual('fixture-provider', candidate.settings['provider'])
        self.assertEqual('fixture-model', candidate.settings['model'])
        self.assertEqual(before, self.core.get_setting('agent.local', {}))
        self.assertEqual([], self.adapters['local'].calls)

    def test_settings_save_hermes_options_without_old_endpoint_controls(self):
        def accept(dialog):
            tabs = dialog.findChild(QTabWidget)
            self.assertIn('Hermes', [tabs.tabText(i) for i in range(tabs.count())])
            self.assertIsNone(dialog.findChild(QComboBox, 'local_harness'))
            self.assertIsNone(dialog.findChild(QLineEdit, 'local_base_url'))
            self.assertIsNone(dialog.findChild(QLineEdit, 'local_api_key_env'))
            for name, value in (('hermes_provider', 'fixture-provider'), ('hermes_model', 'fixture-model')):
                dialog.findChild(QLineEdit, name).setText(value)
            budget = dialog.findChild(QSpinBox, 'hermes_run_budget')
            turns = dialog.findChild(QSpinBox, 'hermes_max_turns')
            self.assertEqual((1, 86400, 600), (budget.minimum(), budget.maximum(), budget.value()))
            self.assertEqual((1, 1000, 60), (turns.minimum(), turns.maximum(), turns.value()))
            budget.setValue(3000)
            turns.setValue(150)
            self.assertEqual('', dialog.findChild(QLineEdit, 'executable_local').text())
            return QDialog.Accepted
        with patch.object(QDialog, 'exec', accept):
            self.window.settings()
        saved = self.core.get_setting('agent.local')
        self.assertEqual('hermes', saved['harness'])
        self.assertEqual('fixture-provider', saved['provider'])
        self.assertEqual('fixture-model', saved['model'])
        self.assertEqual('fixture-model', saved['default_model'])
        self.assertEqual((3000, 150), (saved['run_budget'], saved['max_turns']))
        self.assertTrue(self.window.panels['local'].connect_button.isEnabled())
        self.assertIn('Hermes', self.window.panels['local'].notice.text())
        self.assertEqual([], self.adapters['local'].calls)

    def test_legacy_local_settings_are_not_presented_as_hermes_or_saved_on_cancel(self):
        legacy = {'harness': 'claude', 'executable': 'C:/fixture/claude.exe',
                  'model': 'legacy-model', 'base_url': 'http://localhost:1234',
                  'api_key_env': 'LEGACY_MODEL_KEY'}
        self.core.set_setting('agent.local', legacy)
        def inspect(dialog):
            for name in ('executable_local', 'hermes_provider', 'hermes_model'):
                self.assertEqual('', dialog.findChild(QLineEdit, name).text(), name)
            return QDialog.Rejected
        with patch.object(QDialog, 'exec', inspect):
            self.window.settings(agent='local')
        self.assertEqual(legacy, self.core.get_setting('agent.local'))
        self.assertEqual([], self.adapters['local'].calls)

    def test_blank_provider_and_model_keep_hermes_defaults_available(self):
        with patch.object(QDialog, 'exec', return_value=QDialog.Accepted):
            self.window.settings(agent='local')
        settings = self.core.get_setting('agent.local')
        self.assertEqual(('hermes', '', ''), (settings['harness'], settings['provider'], settings['model']))
        self.assertTrue(self.window.panels['local'].connect_button.isEnabled())
        self.assertEqual([], self.adapters['local'].calls)

    def test_clearing_hermes_overrides_refreshes_capabilities_only_after_reconnect(self):
        from acw.adapters.hermes import DETAIL, HermesAdapter
        self.core.set_setting('agent.local', {'harness': 'hermes', 'provider': 'fixture-provider',
                                              'model': 'fixture-model', 'default_model': 'fixture-model'})
        self.core.set_adapter('local', HermesAdapter(self.core.make_emitter('local')))
        panel = self.window.panels['local']

        def probe(adapter):
            adapter.executable = 'C:/fixture/hermes.exe'
            return {'detail': DETAIL, 'executable': adapter.executable}

        def clear_overrides(dialog):
            dialog.findChild(QLineEdit, 'hermes_provider').clear()
            dialog.findChild(QLineEdit, 'hermes_model').clear()
            return QDialog.Accepted

        with patch.object(HermesAdapter, 'probe', autospec=True, side_effect=probe) as checked:
            panel.connect_agent()
            original = self.core.adapters['local']
            self.assertEqual('Connected', panel.connection_state)
            self.assertEqual('fixture-model', panel.model.currentData())
            self.assertTrue(panel.model.isEnabled())
            with patch.object(QDialog, 'exec', clear_overrides):
                self.window.settings(agent='local')
            self.assertIs(original, self.core.adapters['local'])
            self.assertEqual('fixture-provider', original.settings['provider'])
            self.assertEqual('fixture-model', panel.model.currentData())
            checked.assert_called_once()

            panel.connect_agent()
            self.assertEqual('Disconnected', panel.connection_state)
            panel.connect_agent()
            self.assertEqual(2, checked.call_count)
            replacement = self.core.adapters['local']
            self.assertIsNot(original, replacement)
            self.assertEqual(('', ''), (replacement.settings['provider'], replacement.settings['model']))
            self.assertEqual('Connected', panel.connection_state)
            self.assertFalse(panel.capabilities['supports_model_selection'])
            self.assertIsNone(panel.model.currentData())
            self.assertFalse(panel.model.isEnabled())
            self.assertFalse(panel.effort.isEnabled())
            self.assertIn('後端預設', panel.model.currentText())
            self.assertIn('本視窗無法逐次核准', panel.notice.toolTip())
        self.assertEqual([], self.adapters['local'].calls)

    def test_local_history_filter_uses_local_id_and_branch_label_updates(self):
        self.window.show_history('local')
        self.assertEqual('local', self.window.history_agent.currentData())
        self.assertEqual('Hermes', self.window.history_agent.currentText())
        self.core.git_snapshot = lambda: {'branch': 'fixture-branch', 'is_git': True, 'dirty': False}
        self.window._git_clock = 100
        self.window.poll_events()
        self.assertIn('fixture-branch', self.window.panels['local'].branch_label.text())

    def connect_hermes_with_saved_conversation(self, metadata, session_id='11111111-2222-4333-8444-555555555555'):
        """Restore a saved Workspace fixture without invoking a real Hermes CLI."""
        from acw.adapters.hermes import DETAIL, HermesAdapter
        task = self.core.agent_task('local')
        project = self.core.agent_project('local')
        self.core.store.insert('sessions', {
            'agent': 'local', 'id': session_id, 'task_id': task['id'],
            'project_id': project['id'], 'title': 'Saved local conversation',
            'cwd': project['repo_path'], 'created_at': now(), 'updated_at': now(),
            'metadata': metadata,
        })
        self.core._set_task_session(task['id'], 'local', session_id)
        self.core.store.insert('messages', {
            'id': 'saved-message-' + session_id, 'task_id': task['id'],
            'agent': 'local', 'session_id': session_id, 'role': 'assistant',
            'content': 'Saved local response remains available.', 'timestamp': now(),
            'status': 'complete', 'metadata': {'fixture': True},
        })
        self.core.set_adapter('local', HermesAdapter(self.core.make_emitter('local')))
        panel = self.window.panels['local']
        self.window.refresh_agent('local')

        def probe(adapter):
            adapter.executable = 'C:/fixture/hermes.exe'
            return {'detail': DETAIL, 'executable': adapter.executable}

        with patch.object(HermesAdapter, 'probe', autospec=True, side_effect=probe):
            panel.connect_agent()
        self.assertEqual('Connected', panel.connection_state)
        self.assertEqual([], self.window.reported_errors)
        return panel, self.core.adapters['local'], self.core.get_task(task['id'])

    def test_sending_legacy_local_conversation_creates_hermes_task_and_preserves_history(self):
        panel, adapter, legacy_task = self.connect_hermes_with_saved_conversation({'local_harness': 'claude'})
        legacy_id = legacy_task['local_session']
        saved = self.core.store.get('sessions', {'agent': 'local', 'id': legacy_id})
        history = self.core.messages(task_id=legacy_task['id'], agent='local')
        tasks = self.core.list_tasks()
        self.assertEqual({'task_id': legacy_task['id'], 'session_id': legacy_id, 'harness': 'claude'},
                         self.core.legacy_local_conversation('local'))
        self.assertEqual('新對話並傳送', panel.send_button.text())
        self.assertIn('Hermes', panel.send_feedback.text())
        self.window.reload_context()
        self.assertEqual(tasks, self.core.list_tasks(), 'Rendering and connecting must preserve the old task')
        self.assertEqual(saved, self.core.store.get('sessions', {'agent': 'local', 'id': legacy_id}))
        native = '20261011_010203_a1b2c3d4'
        process = NativeProcessFixture([
            {'type': 'system', 'subtype': 'init', 'session_id': native},
            {'type': 'result', 'session_id': native, 'text': 'New Hermes response', 'exit_code': 0},
        ], blocked=True)
        try:
            with patch('acw.adapters.hermes.subprocess.Popen', return_value=process) as spawn:
                panel.input.setPlainText('Start a new Hermes conversation.')
                panel.send()
                spawn.assert_called_once()
                self.assertFalse(any(arg.startswith('--resume') for arg in spawn.call_args.args[0]))
                process.release.set()
                adapter._thread.join(5)
            self.assertFalse(adapter._thread.is_alive())
            self.assertEqual('Connected', adapter.state, adapter.last_error)
            self.assertEqual([], self.window.reported_errors)
            current = self.core.agent_task('local')
            self.assertNotEqual(legacy_task['id'], current['id'])
            self.assertRegex(current['local_session'], r'^hermes-[0-9a-f]{32}$')
            self.assertEqual(legacy_task, self.core.get_task(legacy_task['id']))
            self.assertEqual(saved, self.core.store.get('sessions', {'agent': 'local', 'id': legacy_id}))
            self.assertEqual(history, self.core.messages(task_id=legacy_task['id'], agent='local'))
            messages = self.core.messages(task_id=current['id'], agent='local')
            self.assertEqual(['Start a new Hermes conversation.', 'New Hermes response'],
                             [row['content'] for row in messages])
            self.assertIsNone(self.core.legacy_local_conversation('local'))
        finally:
            process.release.set()
            if adapter._thread:
                adapter._thread.join(5)
            self.window.refresh_agent('local')

    def test_hermes_send_failure_retains_inline_error_and_draft_after_refresh(self):
        panel, adapter, legacy_task = self.connect_hermes_with_saved_conversation({'local_harness': 'codex'})
        original = self.core.messages(task_id=legacy_task['id'], agent='local')
        with patch('acw.adapters.hermes.subprocess.Popen', side_effect=FileNotFoundError('Fixture Hermes executable missing')) as spawn:
            panel.input.setPlainText('Keep this unsent draft.')
            panel.send()
        spawn.assert_called_once()
        self.assertEqual(['Fixture Hermes executable missing'], self.window.reported_errors)
        self.assertEqual('Keep this unsent draft.', panel.input.toPlainText())
        self.assertIn('傳送失敗', panel.send_feedback.text())
        self.assertIn('Fixture Hermes executable missing', panel.send_feedback.text())
        self.assertFalse(panel.send_feedback.isHidden())
        new_task = self.core.agent_task('local')
        self.assertNotEqual(legacy_task['id'], new_task['id'])
        self.window.reload_context()
        self.window.refresh_agent('local')
        self.assertEqual('Keep this unsent draft.', panel.input.toPlainText())
        self.assertIn('Fixture Hermes executable missing', panel.send_feedback.text())
        self.assertEqual(new_task['id'], self.core.agent_task('local')['id'])
        self.assertEqual(legacy_task, self.core.get_task(legacy_task['id']))
        self.assertEqual(original, self.core.messages(task_id=legacy_task['id'], agent='local'))
        self.core.select_agent_task('local', legacy_task['id'])
        self.window.reload_context()
        self.assertEqual('', panel.send_error)
        self.assertNotIn('傳送失敗', panel.send_feedback.text())
        self.assertIn('舊紀錄保留', panel.send_feedback.text())
        self.core.select_agent_task('local', new_task['id'])
        self.window.reload_context()
        self.assertEqual('Keep this unsent draft.', panel.input.toPlainText())
        self.assertIn('Fixture Hermes executable missing', panel.send_feedback.text())
        self.window.reported_errors.clear()

    def test_unknown_or_corrupt_saved_conversation_does_not_start_new_hermes_session(self):
        cases = (
            ({}, '22222222-2222-4333-8444-555555555555'),
            ({'local_harness': 'unrecognized'}, '33333333-2222-4333-8444-555555555555'),
            ({'local_harness': 'hermes', 'native_session_id': 'corrupted-id'}, 'hermes-' + 'a' * 32),
        )
        for metadata, session_id in cases:
            with self.subTest(metadata=metadata):
                self.core.create_agent_task('local', 'Saved metadata fixture')
                panel, adapter, task = self.connect_hermes_with_saved_conversation(metadata, session_id)
                tasks = self.core.list_tasks()
                self.assertIsNone(self.core.legacy_local_conversation('local'))
                self.assertNotEqual('新對話並傳送', panel.send_button.text())
                with patch('acw.adapters.hermes.subprocess.Popen') as spawn:
                    panel.input.setPlainText('Do not silently replace this session.')
                    panel.send()
                spawn.assert_not_called()
                self.assertTrue(self.window.reported_errors)
                self.assertIn('傳送失敗', panel.send_feedback.text())
                self.assertEqual('Do not silently replace this session.', panel.input.toPlainText())
                self.assertEqual(task['id'], self.core.agent_task('local')['id'])
                self.assertEqual(tasks, self.core.list_tasks())
                self.window.reported_errors.clear()
                adapter.disconnect()

    def test_explicit_open_of_legacy_local_conversation_remains_rejected(self):
        panel, adapter, task = self.connect_hermes_with_saved_conversation({'local_harness': 'claude'})
        tasks = self.core.list_tasks()
        with patch('acw.adapters.hermes.subprocess.Popen') as spawn:
            with self.assertRaisesRegex(ValueError, '舊紀錄仍保留'):
                self.core.open_saved_conversation('local', task['local_session'])
        spawn.assert_not_called()
        self.assertEqual(tasks, self.core.list_tasks())
        self.assertEqual(task, self.core.agent_task('local'))

    def test_legacy_session_with_mismatched_saved_scope_cannot_start_new_hermes_task(self):
        panel, adapter, task = self.connect_hermes_with_saved_conversation({'local_harness': 'claude'})
        other_root = Path(self.temp.name) / 'other-project'
        other_root.mkdir()
        other_project = self.core.create_project('Other project fixture', other_root)
        other_task = self.core.create_task('Other task fixture', other_project['id'], select=False)
        saved_identity = {'agent': 'local', 'id': task['local_session']}
        cases = (
            {'task_id': other_task['id'], 'project_id': task['project_id']},
            {'task_id': task['id'], 'project_id': other_project['id']},
        )
        for fields in cases:
            with self.subTest(fields=fields):
                self.core.store.update('sessions', saved_identity, fields)
                tasks = self.core.list_tasks()
                self.assertIsNone(self.core.legacy_local_conversation('local'))
                self.window.refresh_agent('local')
                self.assertNotEqual('新對話並傳送', panel.send_button.text())
                with patch('acw.adapters.hermes.subprocess.Popen') as spawn:
                    panel.input.setPlainText('Do not migrate a mismatched saved session.')
                    panel.send()
                spawn.assert_not_called()
                self.assertTrue(self.window.reported_errors)
                self.assertEqual(tasks, self.core.list_tasks())
                self.assertEqual(task['id'], self.core.agent_task('local')['id'])
                self.assertEqual('Do not migrate a mismatched saved session.', panel.input.toPlainText())
                self.window.reported_errors.clear()

    def test_missing_native_hermes_session_is_not_retried_as_new_conversation(self):
        native = '20261011_010203_a1b2c3d4'
        alias = 'hermes-' + 'b' * 32
        panel, adapter, task = self.connect_hermes_with_saved_conversation(
            {'local_harness': 'hermes', 'native_session_id': native}, alias)
        task_ids = [row['id'] for row in self.core.list_tasks()]
        process = NativeProcessFixture([
            {'type': 'result', 'session_id': native, 'text': '', 'exit_code': 1,
             'error': 'Fixture native session does not exist'},
        ], blocked=True)
        try:
            with patch('acw.adapters.hermes.subprocess.Popen', return_value=process) as spawn:
                panel.input.setPlainText('Resume the existing Hermes session.')
                panel.send()
                spawn.assert_called_once()
                self.assertIn('--resume=' + native, spawn.call_args.args[0])
                process.release.set()
                adapter._thread.join(5)
            self.assertFalse(adapter._thread.is_alive())
            self.assertEqual('Error', adapter.state)
            self.assertIn('native session does not exist', adapter.last_error)
            self.assertEqual(task_ids, [row['id'] for row in self.core.list_tasks()])
            self.assertEqual(task['id'], self.core.agent_task('local')['id'])
            self.assertEqual(alias, self.core.agent_task('local')['local_session'])
            self.assertEqual([alias], [row['id'] for row in self.core.sessions('local')])
        finally:
            process.release.set()
            if adapter._thread:
                adapter._thread.join(5)
            self.window.refresh_agent('local')


def capture_native_evidence(target):
    """Opt-in visible Windows Qt screenshot; no inference or adapter operation."""
    app = QApplication.instance() or QApplication([])
    if app.platformName() != 'windows':
        raise RuntimeError('Native screenshot requires the Windows Qt platform, not offscreen')
    app.setStyle('Fusion')
    with tempfile.TemporaryDirectory() as temporary:
        core, adapters, window = offline_window(Path(temporary))
        try:
            window.resize(1900, 950)
            window.move(0, 0)
            window.show()
            window.raise_()
            QTest.qWait(600)
            app.processEvents()
            window.update_workspace_layout()
            app.processEvents()
            if window.size().width() != 1900 or window.size().height() != 950:
                raise AssertionError('Windows did not preserve the requested 1900x950 client size')
            for panel in window.panels.values():
                if not (panel.isVisible() and panel.title.isVisible() and panel.input.isVisible()):
                    raise AssertionError('All four native panel headings and inputs must be visible')
            if any(adapter.calls for adapter in adapters.values()):
                raise AssertionError('Native screenshot must not call any adapter')
            target = Path(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            screenshot = window.screen().grabWindow(int(window.winId()))
            if screenshot.isNull() or not screenshot.save(str(target)):
                raise RuntimeError('Windows native window capture failed')
            print(f'PASS native Windows screenshot: {screenshot.width()}x{screenshot.height()}, '
                  f'platform={app.platformName()}, font={app.font().family()}, four panels visible, no adapter calls')
        finally:
            window.close()
            core.close()


if __name__ == '__main__':
    unittest.main()
