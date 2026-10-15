"""Interactive Monitor shell uses existing panels without dispatch side effects."""
import unittest
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMessageBox, QDialog, QLineEdit, QTabWidget
import test_ui_refresh as fixtures


class WorkbenchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.WorkspaceUiRefreshTests.setUpClass()

    def setUp(self):
        self.fixture = fixtures.WorkspaceUiRefreshTests()
        self.fixture.setUp()
        self.window, self.core = self.fixture.window, self.fixture.core
        self.window.resize(1500, 950)
        self.fixture.settle()

    def tearDown(self):
        self.fixture.tearDown()

    def test_workbench_theme_and_focus_rail_are_visible_without_backend_calls(self):
        self.assertIn('CONTROL ROOM', self.window.console_mark.text())
        self.assertIn('#d97757', self.window.styleSheet())
        self.assertNotIn('#a3e635', self.window.styleSheet())
        self.assertTrue(self.window.agent_rail.isVisible())
        self.assertEqual('Workspace', self.window.mode.currentData())
        self.assertEqual('Focus', self.window.layout_mode.currentData())
        self.assertEqual(1, sum(panel.isVisible() for panel in self.window.panels.values()))
        self.fixture.assert_no_adapter_actions()

    def test_focus_parallel_roundtrip_keeps_original_widgets_drafts_and_bindings(self):
        original = dict(self.window.panels)
        bindings = {agent: self.core.agent_task(agent) for agent in original}
        for agent, panel in original.items():
            panel.input.setPlainText(agent + ' retained draft')
        self.window.resize(1800, 1000)
        self.window.layout_mode.setCurrentIndex(self.window.layout_mode.findData('Three panes'))
        self.fixture.settle()
        self.assertTrue(all(panel.isVisible() for panel in original.values()))
        self.assertFalse(self.window.agent_rail.isVisible())
        self.window.open_monitor_role('codex')
        self.fixture.settle()
        self.assertTrue(self.window.agent_rail.isVisible())
        self.assertTrue(self.window.panels['codex'].isVisible())
        self.window.open_monitor_role('codex')
        self.assertEqual('Focus', self.window.layout_mode.currentData())
        for agent, panel in original.items():
            self.assertIs(panel, self.window.panels[agent])
            self.assertEqual(agent + ' retained draft', panel.input.toPlainText())
            self.assertEqual(bindings[agent], self.core.agent_task(agent))
        self.fixture.assert_no_adapter_actions()

    def test_rail_projects_status_and_navigation_are_independent(self):
        other = self.core.create_project('Independent fixture', self.fixture.temp.name)
        self.core.select_agent_project('codex', other['id'])
        self.fixture.adapters['codex'].state = 'Busy'
        self.window.refresh_monitor()
        card, action, status, context, session = self.window.agent_rail.cards['codex']
        self.assertEqual('Independent fixture', context.text())
        self.assertIn('執行中', status.text())
        action.click()
        self.fixture.settle()
        self.assertEqual('codex', self.window._preferred_agent)
        self.assertTrue(card.property('selected'))
        self.fixture.assert_no_adapter_actions()
        self.fixture.adapters['codex'].state = 'Disconnected'

    def test_live_workbench_and_readonly_overview_keep_approval_boundary(self):
        panel = self.fixture.connect_fixture('codex')
        self.window.open_monitor_role('codex')
        self.assertTrue(panel.send_button.isEnabled())
        self.assertFalse(panel.input.isReadOnly())
        self.window.toggle_monitor()
        self.assertTrue(panel.input.isReadOnly())
        self.assertFalse(panel.send_button.isEnabled())
        self.window.toggle_monitor()
        self.assertFalse(panel.input.isReadOnly())
        self.assertTrue(panel.send_button.isEnabled())
        self.fixture.assert_no_adapter_actions()

    def test_narrow_workbench_collapses_rail_without_losing_input_or_drafts(self):
        panel = self.window.panels['claude']
        panel.input.setPlainText('narrow draft')
        self.window.sidebar.hide()
        self.window.resize(650, 800)
        self.fixture.settle()
        self.assertFalse(self.window.agent_rail.isVisible())
        self.assertTrue(panel.input.isVisible())
        self.assertTrue(panel.send_button.isVisible())
        self.assertEqual(0, self.window.workspace_scroll.horizontalScrollBar().maximum())
        self.assertEqual('narrow draft', panel.input.toPlainText())
        self.fixture.assert_no_adapter_actions()

    def test_poll_refreshes_local_status_without_connecting_or_reading_backend(self):
        self.fixture.adapters['codex'].state = 'Connected'
        self.window._monitor_clock = 0
        self.window.poll_events()
        self.assertIn('已連線', self.window.agent_rail.cards['codex'][2].text())
        self.fixture.assert_no_adapter_actions()

    def test_layout_choice_is_saved_without_changing_agent_contexts(self):
        before = {agent: self.core.agent_task(agent) for agent in self.window.agents}
        self.window.layout_mode.setCurrentIndex(self.window.layout_mode.findData('Three panes'))
        self.fixture.settle()
        self.assertEqual('Three panes', self.core.get_setting('ui.layout_mode'))
        self.assertEqual(before, {agent: self.core.agent_task(agent) for agent in self.window.agents})
        self.fixture.assert_no_adapter_actions()

    def test_agent_sidebar_has_one_project_session_scope_and_records_are_separate(self):
        self.assertIs(self.window.sidebar, self.window.navigator.parentWidget())
        self.assertTrue(self.window.sidebar.isAncestorOf(self.window.navigator))
        self.assertFalse(self.window.project_combo.isVisible())
        self.assertFalse(self.window.task_combo.isVisible())
        self.assertFalse(self.window.panels['claude'].task.isVisible())
        self.window.show_records()
        self.fixture.settle()
        self.assertTrue(self.window.project_combo.isVisible())
        self.fixture.assert_no_adapter_actions()

    def test_daily_sidebar_shows_only_selected_agent_and_primary_session_controls(self):
        self.window.records_dialog.close()
        for agent in ('claude', 'codex', 'local'):
            self.window.role_tabs.setCurrentIndex(self.window.agents.index(agent))
            self.fixture.settle()
            panel = self.window.panels[agent]
            self.assertTrue(self.window.sidebar_agent_title.text().startswith(self.window.role_names[agent] + ' · '))
            for control in (panel.project, panel.session_search, panel.session, panel.new_button,
                            panel.resume_button, panel.session_more):
                self.assertTrue(control.isVisible(), control.objectName())
            for control in (panel.task, panel.rename_button, panel.session_details, panel.discover_button,
                            panel.cwd_label, panel.branch_label, panel.current_session_label):
                self.assertFalse(control.isVisible(), control.objectName())
        self.assertFalse(self.window.session_tabs.tabBar().isVisible())
        self.assertFalse(self.window.mode.isVisible())
        self.assertFalse(self.window.project_combo.isVisible())
        self.assertFalse(self.window.task_status.isVisible())
        self.fixture.assert_no_adapter_actions()

    def test_session_menu_preserves_details_and_capability_gates_without_backend_calls(self):
        panel = self.window.panels['codex']
        action, control = panel.session_actions['details']
        self.assertTrue(action.isEnabled())
        with patch('acw.ui.SessionDetailsDialog') as dialog:
            action.trigger()
        self.assertEqual(self.core.agent_task('codex')['codex_session'], dialog.call_args.args[0]['id'])
        self.assertFalse(panel.session_actions['discover'][0].isEnabled())
        self.fixture.connect_fixture('codex')
        self.assertTrue(panel.session_actions['discover'][0].isEnabled())
        panel.set_monitor(True)
        self.assertFalse(panel.session_actions['discover'][0].isEnabled())
        self.assertFalse(panel.session_actions['rename'][0].isEnabled())
        panel.set_monitor(False)
        self.fixture.assert_no_adapter_actions()

    def test_project_information_menu_uses_its_agent_scope(self):
        self.core.select_agent_project('codex', self.fixture.project_b['id'])
        self.window.reload_context()
        panel = self.window.panels['codex']
        action = next(action for action in panel.session_menu.actions() if action.text() == '專案資訊…')
        with patch.object(self.window, 'show_detail') as details:
            action.trigger()
        self.assertEqual(self.fixture.project_b['id'], details.call_args.args[1]['project']['id'])
        self.assertIn(self.fixture.project_b['repo_path'], details.call_args.args[1]['working_directory'])
        self.fixture.assert_no_adapter_actions()

    def test_view_menu_keeps_draft_and_agent_binding_when_returning_from_overview(self):
        panel = self.window.panels['codex']
        self.window.open_monitor_role('codex')
        panel.input.setPlainText('Retain draft while changing view')
        task = self.core.agent_task('codex')
        self.window.view_actions['Monitor'].trigger()
        self.assertTrue(panel.input.isReadOnly())
        self.window.view_actions['Workspace'].trigger()
        self.assertFalse(panel.input.isReadOnly())
        self.assertEqual(task, self.core.agent_task('codex'))
        self.assertEqual('Retain draft while changing view', panel.input.toPlainText())
        self.fixture.assert_no_adapter_actions()

    def test_local_settings_menu_opens_the_selected_instance_without_connecting(self):
        agent = self.window.add_agent_instance('local', 'Local helper', project_id=self.fixture.project_a['id'])
        seen = []
        def inspect(dialog):
            tabs = dialog.findChild(QTabWidget)
            field = tabs.currentWidget().findChild(QLineEdit, 'hermes_provider')
            seen.append(field.property('agent_id'))
            return QDialog.Rejected
        action = next(action for action in self.window.panels[agent].session_menu.actions()
                      if action.text() == 'Hermes 設定…')
        with patch.object(QDialog, 'exec', inspect):
            action.trigger()
        self.assertEqual([agent], seen)
        self.assertEqual('Disconnected', self.core.adapters[agent].state)
        self.fixture.assert_no_adapter_actions()

    def test_record_navigation_does_not_touch_any_busy_agent_or_its_draft(self):
        before = {agent: self.core.agent_task(agent)['id'] for agent in self.window.agents}
        panel = self.window.panels['codex']
        panel.input.setPlainText('independent retained draft')
        self.fixture.adapters['claude'].state = 'Busy'
        self.window.panels['claude'].set_state('Busy')
        with patch.object(self.fixture.adapters['claude'], 'set_project', side_effect=AssertionError('Record navigation must not touch an adapter')):
            self.window.project_combo.setCurrentIndex(self.window.project_combo.findData(self.fixture.project_b['id']))
            self.fixture.settle()
        self.assertEqual(before, {agent: self.core.agent_task(agent)['id'] for agent in self.window.agents})
        self.assertEqual('independent retained draft', panel.input.toPlainText())
        self.assertEqual(self.fixture.project_b['id'], self.core.current_project_id)
        self.fixture.adapters['claude'].state = 'Disconnected'
        self.fixture.assert_no_adapter_actions()

    def test_open_saved_conversation_restores_its_original_history_container(self):
        panel = self.fixture.connect_fixture('codex')
        original_task = self.core.agent_task('codex')
        original_session = original_task['codex_session']
        panel.input.setPlainText('original draft')
        panel.new_session()
        new_task = self.core.agent_task('codex')
        self.assertNotEqual(original_task['id'], new_task['id'])
        self.assertEqual(original_session, self.core.get_task(original_task['id'])['codex_session'])
        panel.session.setCurrentIndex(panel.session.findData(original_session))
        panel.resume_session()
        self.assertEqual(original_task['id'], self.core.agent_task('codex')['id'])
        self.assertEqual('original draft', panel.input.toPlainText())
        self.assertEqual(('resume_session', original_session), self.fixture.adapters['codex'].calls[-1])

    def test_failed_send_restores_text_and_attachments_without_retry(self):
        panel = self.fixture.connect_fixture('codex')
        attachment = Path(self.fixture.project_a['repo_path']) / 'attachment.txt'
        attachment.write_text('fixture', encoding='utf-8')
        panel.input.setPlainText('retained failure prompt')
        panel.add_attachments([str(attachment)])
        with patch.object(self.fixture.adapters['codex'], 'send_message', side_effect=RuntimeError('fixture uncertain delivery')) as send:
            panel.send()
        self.assertEqual(1, send.call_count)
        self.assertEqual('retained failure prompt', panel.input.toPlainText())
        self.assertEqual([str(attachment)], panel.attachments)
        self.assertEqual('delivery_unknown', self.core.messages(agent='codex')[-1]['status'])
        self.assertEqual(['fixture uncertain delivery'], self.window.reported_errors)
        self.window.reported_errors.clear()

    def test_first_send_preparation_preserves_the_next_draft_typed_during_dispatch(self):
        panel = self.fixture.connect_fixture('codex')
        self.core.select_agent_project('codex', self.fixture.project_b['id'])
        self.window.reload_context()
        panel.input.setPlainText('first conversation prompt')
        original = self.fixture.adapters['codex'].send_message
        def send(*args, **kwargs):
            result = original(*args, **kwargs)
            panel.input.setPlainText('next draft typed during dispatch')
            return result
        with patch.object(self.fixture.adapters['codex'], 'send_message', side_effect=send):
            panel.send()
        self.assertEqual('next draft typed during dispatch', panel.input.toPlainText())
        self.assertEqual('first conversation prompt', self.core.messages(agent='codex')[-1]['content'])
        self.assertEqual(self.fixture.project_b['id'], self.core.agent_task('codex')['project_id'])

    def test_open_operations_reserve_only_the_selected_agent(self):
        self.assertTrue(self.window._opening_begin('claude'))
        self.assertTrue(self.window._opening_begin('codex'))
        self.assertFalse(self.window._opening_begin('codex'))
        self.assertFalse(self.window.panels['codex'].project.isEnabled())
        self.assertTrue(self.window.panels['local'].project.isEnabled())
        self.window._opening_done('claude')
        self.assertEqual({'codex'}, self.window._opening_agents)
        self.window._opening_done('codex')
        self.assertFalse(self.window._opening_agents)
        self.fixture.assert_no_adapter_actions()

    def test_details_and_title_follow_selected_agent_instead_of_record_filter(self):
        self.core.select_agent_task('codex', self.fixture.task_c['id'])
        self.window.reload_context()
        self.window.focus_role('codex')
        self.assertEqual(self.fixture.task_c['id'], self.window.view_task()['id'])
        self.assertIn('Codex · Beta', self.window.context_title.text())
        self.window.show_records()
        self.assertEqual(self.fixture.task_a['id'], self.window.view_task()['id'])
        self.window.records_dialog.close()
        self.assertEqual(self.fixture.task_c['id'], self.window.view_task()['id'])
        self.window.show_records()
        self.window.open_monitor_role('codex')
        self.assertFalse(self.window.records_dialog.isVisible())
        self.assertEqual(self.fixture.task_c['id'], self.window.view_task()['id'])

    def test_artifact_import_and_file_open_use_explicit_conversation_project(self):
        self.core.select_agent_task('codex', self.fixture.task_c['id'])
        own = Path(self.fixture.project_b['repo_path']) / 'report.txt'
        other = Path(self.fixture.project_a['repo_path']) / 'report.txt'
        for path in (own, other): path.write_text('fixture report', encoding='utf-8')
        record = self.core.import_artifact(own, task_id=self.fixture.task_c['id'])
        self.assertEqual(self.fixture.task_c['id'], record['task_id'])
        with self.assertRaises(PermissionError):
            self.core.import_artifact(other, task_id=self.fixture.task_c['id'])
        self.assertEqual(own.resolve(), self.core.project_file('report.txt', self.fixture.project_b['id']))

    def test_local_codex_harness_cannot_take_over_a_connected_codex_session(self):
        self.fixture.connect_fixture('codex')
        adapter = self.fixture.adapters['local']
        adapter.local_harness = 'codex'
        adapter.state = 'Connected'
        before = list(adapter.calls)
        with self.assertRaisesRegex(RuntimeError, 'already connected'):
            with self.core._native_session_operation('local', self.fixture.adapters['codex'].session_id):
                self.fail('Conflicting backend session must never be entered')
        self.assertEqual(before, adapter.calls)

    def test_latest_view_restore_wins_over_queued_scroll_callbacks(self):
        self.fixture.add_saved_response(text='\n\n'.join('Long visible fixture paragraph ' * 8 for _ in range(60)))
        panel = self.window.panels['claude']
        self.fixture.settle()
        self.assertGreater(panel.scroll.verticalScrollBar().maximum(), 100)
        panel.restore_view_state({'scroll': 100})
        panel.restore_view_state({'scroll': 40})
        self.assertEqual(40, panel.capture_view_state()['scroll'])
        self.fixture.settle()
        self.assertEqual(40, panel.scroll.verticalScrollBar().value())

    def test_shutdown_stops_dispatch_before_backend_cancellation(self):
        panel = self.fixture.connect_fixture('claude')
        adapter = self.fixture.adapters['claude']
        panel.set_state('Busy')
        adapter.state = 'Busy'
        run = SimpleNamespace(active=True, agents=('claude', 'codex'))
        run.stop = lambda reason: setattr(run, 'active', False)
        self.window.orchestrator = run
        def cancel(**kwargs):
            self.assertFalse(run.active, 'No run may dispatch while cancellation is in flight')
            self.assertTrue(kwargs['confirmed'])
            adapter.state = 'Connected'
            panel.set_state('Connected')
            return {}
        with patch('acw.ui.QMessageBox.question', return_value=QMessageBox.Yes), patch.object(self.core, 'stop_task', side_effect=cancel):
            self.window.closeEvent(QCloseEvent())
            self.fixture.settle()
        self.assertTrue(self.window._closed)
        self.assertFalse(self.window.run_timer.isActive())

    def test_record_navigation_cannot_restore_another_agent_focus(self):
        self.window.focus_role('codex')
        self.core.select_task(self.fixture.task_b['id'])
        self.window.reload_context()
        self.assertEqual('codex', self.window._preferred_agent)
        self.window.focus_role('claude')
        self.core.select_task(self.fixture.task_a['id'])
        self.window.reload_context()
        self.assertEqual('claude', self.window._preferred_agent)
        self.assertEqual('claude', self.core.get_setting('ui.active_agent'))
        self.fixture.assert_no_adapter_actions()


if __name__ == '__main__':
    unittest.main()
