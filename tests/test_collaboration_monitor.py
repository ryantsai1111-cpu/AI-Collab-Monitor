"""Direct delegation, bounded runs and a local-only Monitor, using offline adapters."""
import unittest
from unittest.mock import patch
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from acw.monitor import collect_snapshot
from acw.orchestrator import RunLimits
import test_orchestrator as fixtures


class DirectRunTests(unittest.TestCase):
    setUp = fixtures.OrchestratorTests.setUp
    tearDown = fixtures.OrchestratorTests.tearDown
    build = fixtures.OrchestratorTests.build
    advance = fixtures.OrchestratorTests.advance

    def test_independent_projects_and_sessions_complete_without_shared_record_task(self):
        run = self.build(workflow='direct')
        self.core.enable_agent_independence()
        repo = Path(self.temp.name) / 'worker'
        repo.mkdir()
        project = self.core.create_project('Worker project', repo)
        self.core.select_agent_project('codex', project['id'])
        worker_task = self.core.create_agent_task('codex', 'Independent worker conversation')
        lead_task = self.core.agent_task('claude')
        run.start()
        record_task = self.core.create_task('Unrelated record filter')
        self.assertEqual(record_task['id'], self.core.current_task_id)
        self.advance()
        self.assertEqual('done', run.state)
        self.assertEqual(lead_task['id'], self.core.agent_task('claude')['id'])
        self.assertEqual(worker_task['id'], self.core.agent_task('codex')['id'])
        self.assertEqual(project['id'], self.core.agent_project('codex')['id'])
        worker_messages = self.core.messages(worker_task['id'], 'codex')
        self.assertEqual(['user', 'assistant'], [row['role'] for row in worker_messages])
        self.assertTrue(all(row['session_id'] == self.adapters['codex'].session_id for row in worker_messages))
        self.assertEqual([], self.core.messages(record_task['id']))

    def test_participant_binding_change_pauses_before_next_send(self):
        run = self.build(workflow='direct')
        self.core.enable_agent_independence()
        run.start()
        other = self.core.create_task('Changed worker binding', select=False)
        self.core.select_agent_task('codex', other['id'])
        run.tick()
        self.assertEqual('paused', run.state)
        self.assertIn('Codex', run.reason)
        self.assertEqual([], self.adapters['codex'].sent)

    def test_two_claude_instances_keep_distinct_conversations_through_completion(self):
        self.build(workflow='direct')
        self.core.enable_agent_independence()
        agents = []
        for name, replies in [('Lead', ['VERDICT: PLAN_READY\nplan', 'VERDICT: APPROVED\nverified']),
                              ('Worker', ['VERDICT: IMPLEMENTED\nwork'])]:
            agent = self.core.create_agent_instance('claude', name, project_id=self.core.current_project_id)['id']
            adapter = fixtures.Scripted(agent, replies)
            adapter.core, adapter.state = self.core, 'Connected'
            self.core.set_adapter(agent, adapter)
            self.core.create_agent_task(agent, name + ' conversation')
            agents.append(agent)
        from acw.orchestrator import Orchestrator
        run = Orchestrator(self.core, 'All Claude collaboration', self.run_.dispatch, lead=agents[0], implementer=agents[1])
        self.run_ = run
        before = {agent: self.core.agent_task(agent)['id'] for agent in agents}
        run.start()
        self.advance()
        self.assertEqual('done', run.state)
        self.assertEqual(before, {agent: self.core.agent_task(agent)['id'] for agent in agents})
        self.assertNotEqual(self.core.adapters[agents[0]].session_id, self.core.adapters[agents[1]].session_id)

    def test_direct_run_needs_only_claude_and_codex_and_claude_decides_completion(self):
        run = self.build(workflow='direct')
        self.adapters['dot'].state = self.adapters['local'].state = 'Disconnected'
        self.adapters['dot'].native_room_id = ''
        run.start()
        run.tick()
        self.assertEqual('implement', run.step)
        self.assertEqual('running', run.state)
        self.assertIn('計畫內容 P', self.adapters['codex'].sent[0])
        run.tick()
        self.assertEqual('final_review', run.step)
        self.assertEqual('running', run.state)
        self.assertIn('回報 R', self.adapters['claude'].sent[-1])
        run.tick()
        self.assertEqual('done', run.state)
        self.assertEqual([], self.adapters['dot'].calls)
        self.assertEqual([], self.adapters['dot'].grants)

    def test_claude_changes_go_back_to_codex_and_count_a_round(self):
        run = self.build({'claude': ['VERDICT: PLAN_READY\nplan', 'VERDICT: CHANGES_REQUESTED\nfix accessibility',
                                    'VERDICT: APPROVED\nverified'],
                          'codex': ['VERDICT: IMPLEMENTED\nfirst', 'VERDICT: IMPLEMENTED\nfixed']}, workflow='direct')
        run.start()
        self.advance()
        self.assertEqual(('done', 2), (run.state, run.round))
        self.assertIn('fix accessibility', self.adapters['codex'].sent[1])

    def test_round_limit_cannot_mark_unapproved_work_done(self):
        run = self.build({'claude': ['VERDICT: PLAN_READY\nplan', 'VERDICT: CHANGES_REQUESTED\nfix']},
                         workflow='direct', max_rounds=1)
        run.start()
        self.advance()
        self.assertEqual('paused', run.state)
        self.assertIn('回合上限', run.reason)
        self.assertEqual(1, len(self.adapters['codex'].sent))

    def test_optional_local_failure_still_goes_to_claude(self):
        run = self.build(workflow='direct', local_role='reviewer')
        self.adapters['local'].fail = 'fixture unavailable'
        run.start()
        self.advance()
        self.assertEqual('done', run.state)
        self.assertIn('未提供', self.adapters['claude'].sent[-1])
        self.assertEqual([], self.adapters['dot'].calls)

    def test_local_implementer_keeps_claude_as_reviewer(self):
        run = self.build({'local': ['VERDICT: IMPLEMENTED\nlocal implementation']}, workflow='direct', local_role='implementer')
        self.adapters['codex'].state = 'Disconnected'
        run.start()
        self.advance()
        self.assertEqual('done', run.state)
        self.assertIn('local implementation', self.adapters['claude'].sent[-1])
        self.assertEqual([], self.adapters['codex'].calls)

    def test_step_limit_prevents_next_send(self):
        run = self.build(workflow='direct', max_steps=1)
        run.start()
        self.advance()
        self.assertEqual('paused', run.state)
        self.assertIn('步數上限', run.reason)
        self.assertEqual([], self.adapters['codex'].sent)

    def test_total_budget_stops_even_when_individual_step_has_time(self):
        run = self.build(workflow='direct', max_active_seconds=10)
        run.start()
        self.clock[0] += 11
        run.tick()
        self.assertEqual('paused', run.state)
        self.assertIn('有效時間上限', run.reason)
        self.assertEqual([], self.adapters['codex'].sent)
        snapshot = run.snapshot()
        self.clock[0] += 100
        self.assertEqual(snapshot, run.snapshot())

    def test_human_hold_excluded_from_total_budget_and_no_handoff_during_hold(self):
        run = self.build(workflow='direct', max_active_seconds=30)
        run.start()
        self.clock[0] += 5
        self.approval[0] = True
        run.tick()
        self.clock[0] += 10000
        run.tick()
        self.assertEqual(5, run.snapshot()['elapsed_seconds'])
        self.assertEqual([], self.adapters['codex'].sent)
        self.approval[0] = False
        run.tick()
        self.assertEqual('implement', run.step)
        self.assertEqual(5, run.snapshot()['elapsed_seconds'])

    def test_expired_queued_operation_cannot_contact_backend(self):
        run = self.build(workflow='direct', max_active_seconds=10)
        queue = []
        run.dispatch = lambda *args: queue.append(args)
        run.start()
        self.clock[0] += 11
        operation, done, _ = queue.pop(0)
        result = operation()
        done(result)
        self.assertEqual('paused', run.state)
        self.assertFalse(any(a.calls for a in self.adapters.values()))

    def test_late_native_dispatch_gate_checks_total_budget(self):
        run = self.build(workflow='direct', max_active_seconds=10)
        run.start()
        guard = run._contract['_dispatch_guard']
        self.clock[0] += 11
        with self.assertRaisesRegex(RuntimeError, 'time budget'):
            guard()

    def test_snapshot_does_not_consume_or_mutate_approval_state(self):
        run = self.build(workflow='direct')
        run.start()
        with patch.object(run, 'has_pending_approval', side_effect=AssertionError('No polling from Monitor')):
            before = dict(run.__dict__)
            run.snapshot()
            self.assertEqual(before, run.__dict__)

    def test_limits_reject_invalid_or_unbounded_values(self):
        for limits in ({'max_rounds': 0}, {'max_steps': 101}, {'max_active_seconds': -1}, {'max_steps': True}):
            with self.subTest(limits=limits), self.assertRaises(ValueError):
                RunLimits(**limits)

    def test_both_leads_route_direct_relay_and_optional_roles(self):
        for lead, other in (('claude', 'codex'), ('codex', 'claude')):
            for workflow in ('direct', 'relay'):
                for local_role in (None, 'reviewer', 'implementer'):
                    with self.subTest(lead=lead, workflow=workflow, local_role=local_role):
                        worker = 'local' if local_role == 'implementer' else other
                        script = {lead: ['VERDICT: PLAN_READY\nassigned work', 'VERDICT: APPROVED\nverified'],
                                  worker: ['VERDICT: IMPLEMENTED\nimplementation report']}
                        if local_role == 'reviewer':
                            script['local'] = ['VERDICT: PASS\nsecond opinion']
                        run = self.build(script, lead=lead, workflow=workflow, local_role=local_role)
                        if local_role == 'implementer':
                            self.adapters[other].state = 'Disconnected'
                        run.start()
                        self.advance()
                        self.assertEqual('done', run.state)
                        self.assertEqual(lead, run.steps['plan'][0])
                        self.assertEqual(lead, run.steps['final_review'][0])
                        self.assertEqual(worker, run.steps['implement'][0])
                        self.assertEqual((lead, worker), (run.snapshot()['lead'], run.snapshot()['implementer']))
                        self.assertEqual(2, len(self.adapters[lead].sent))
                        self.assertEqual(1, len(self.adapters[worker].sent))
                        from acw.orchestrator import ROLE_NAMES
                        self.assertIn(ROLE_NAMES[lead], run.reason)
                        if workflow == 'relay':
                            self.assertIn(f'以下是 {ROLE_NAMES[lead]} 的計畫', self.adapters['dot'].sent[0])
                            self.assertIn(f'給實作者 {ROLE_NAMES[worker]}', self.adapters['dot'].sent[0])
                            self.assertIn(f'最終審查者 {ROLE_NAMES[lead]}', self.adapters['dot'].sent[1])
                        else:
                            self.assertEqual([], self.adapters['dot'].calls)

    def test_codex_lead_corrections_and_round_limit(self):
        for rounds, state, count in ((1, 'paused', 1), (2, 'done', 2)):
            with self.subTest(rounds=rounds):
                run = self.build({'codex': ['VERDICT: PLAN_READY\nplan', 'VERDICT: CHANGES_REQUESTED\nfix tests',
                                           'VERDICT: APPROVED\nverified'],
                                  'claude': ['VERDICT: IMPLEMENTED\nfirst', 'VERDICT: IMPLEMENTED\nfixed']},
                                 workflow='direct', lead='codex', max_rounds=rounds)
                run.start()
                self.advance()
                self.assertEqual(state, run.state)
                self.assertEqual(count, len(self.adapters['claude'].sent))
                if count == 2:
                    self.assertIn('fix tests', self.adapters['claude'].sent[1])

    def test_implementer_cannot_declare_final_approval_for_codex_lead(self):
        run = self.build({'codex': ['VERDICT: PLAN_READY\nplan'], 'claude': ['VERDICT: APPROVED\ndone']},
                         workflow='direct', lead='codex')
        run.start()
        self.advance()
        self.assertEqual('paused', run.state)
        self.assertIn('沒有可用的判定', run.reason)

    def test_invalid_lead_rejected_without_dispatch(self):
        with self.assertRaises(ValueError):
            self.build(lead='unknown')
        self.assertFalse(any(a.calls for a in self.adapters.values()))


class MonitorTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.WindowRunTests.setUpClass.__func__)
    setUp = fixtures.WindowRunTests.setUp
    tearDown = fixtures.WindowRunTests.tearDown

    def test_direct_ui_start_keeps_workbench_available_without_dot_grants(self):
        self.adapters['dot'].state = 'Disconnected'
        self.window.run_auto_collab('offline task', 3)
        self.window.run_timer.stop()
        self.assertEqual('direct', self.window.orchestrator.workflow)
        self.assertEqual('Workspace', self.window.mode.currentData())
        self.assertIs(self.window.stack.currentWidget(), self.window.chat_workspace)
        self.assertFalse(self.window.panels['claude'].send_button.isEnabled())
        self.assertTrue(self.window.panels['local'].project.isEnabled())
        self.assertEqual([], self.grants)
        self.window.stop_auto_collab()

    def test_relay_still_requires_explicit_run_consent(self):
        self.window.run_auto_collab('offline task', 3, workflow='relay')
        self.assertIsNone(self.window.orchestrator)
        self.assertEqual([], self.grants)

    def test_codex_lead_updates_completion_rules_and_role_cards(self):
        self.adapters['codex'].replies = ['VERDICT: PLAN_READY\nplan', 'VERDICT: APPROVED\nverified']
        self.adapters['claude'].replies = ['VERDICT: IMPLEMENTED\nwork']
        self.window.run_auto_collab('reverse delegation', 3, lead='codex')
        self.window.run_timer.stop()
        self.window.tick_auto_collab()
        self.window.tick_auto_collab()
        dashboard = self.window.monitor_dashboard
        self.assertEqual('Codex 已確認完成', dashboard.phase.text())
        self.assertIn('Codex 決定完成', dashboard.rules.text())
        self.assertIn('派工 / 驗收', dashboard.cards['codex'].duty.text())
        self.assertIn('實作 / 回報', dashboard.cards['claude'].duty.text())
        self.assertEqual([], self.grants)

    def test_dialog_passes_selected_lead_and_preview_tracks_local_replacement(self):
        from PySide6.QtWidgets import QComboBox, QDialog, QLabel, QPlainTextEdit
        self.window._preferred_agent = 'codex'
        def inspect(dialog):
            lead = dialog.findChild(QComboBox, 'auto_lead')
            preview = dialog.findChild(QLabel, 'auto_flow_preview')
            local = dialog.findChild(QComboBox, 'auto_local_role')
            self.assertEqual('codex', lead.currentData())
            self.assertIn('Codex 派工 → Claude 實作 → Codex 驗收', preview.text())
            local.setCurrentIndex(local.findData('implementer'))
            self.assertIn('Codex 派工 → Hermes 實作 → Codex 驗收', preview.text())
            dialog.findChild(QPlainTextEdit, 'auto_task').setPlainText('fixture task')
            return QDialog.Accepted
        with patch('acw.ui.QDialog.exec', inspect), patch.object(self.window, 'run_auto_collab') as start:
            self.window.start_auto_collab()
        self.assertEqual('codex', start.call_args.kwargs['lead'])
        self.assertEqual('implementer', start.call_args.kwargs['local_role'])

    def test_dialog_defaults_to_direct_and_requires_consent_only_for_relay(self):
        from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QDialogButtonBox, QPlainTextEdit
        def inspect(dialog):
            workflow = dialog.findChild(QComboBox, 'auto_workflow')
            consent = dialog.findChild(QCheckBox, 'auto_consent')
            task = dialog.findChild(QPlainTextEdit, 'auto_task')
            start = dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok)
            self.assertEqual('direct', workflow.currentData())
            self.assertFalse(start.isEnabled())
            task.setPlainText('fixture task')
            self.assertTrue(start.isEnabled())
            self.assertTrue(consent.isHidden())
            workflow.setCurrentIndex(workflow.findData('relay'))
            self.assertFalse(start.isEnabled())
            self.assertFalse(consent.isHidden())
            consent.setChecked(True)
            self.assertTrue(start.isEnabled())
            return QDialog.Rejected
        with patch('acw.ui.QDialog.exec', inspect):
            self.window.start_auto_collab()
        self.assertIsNone(self.window.orchestrator)

    def test_previous_run_is_not_relabelled_as_a_new_project(self):
        self.window.run_auto_collab('offline task', 3)
        self.window.run_timer.stop()
        self.window.stop_auto_collab()
        project = self.core.create_project('Another project', self.temp.name)
        self.core.select_project(project['id'], sync=False)
        data = collect_snapshot(self.core, self.window.panels, self.window.orchestrator)
        self.assertEqual('Auto', data['project'])

    def test_close_stops_sync_and_run_timers_before_store_is_closed(self):
        self.window.close()
        self.assertFalse(self.window.timer.isActive())
        self.assertFalse(self.window.sync_timer.isActive())
        self.assertFalse(self.window.run_timer.isActive())
        with patch.object(self.core, 'agent_task', side_effect=AssertionError('Closed window must not read store')):
            self.window.sync_local_conversations()

    def test_refresh_is_read_only_and_shows_each_roles_own_project(self):
        other = self.core.create_project('Independent', self.temp.name)
        self.core.select_agent_project('codex', other['id'])
        calls = {agent: list(a.calls) for agent, a in self.adapters.items()}
        with patch.object(self.core, '_record', side_effect=AssertionError('Monitor must not write events')):
            self.window.refresh_monitor()
            data = collect_snapshot(self.core, self.window.panels)
        self.assertEqual('Independent', next(r['project'] for r in data['roles'] if r['agent'] == 'codex'))
        self.assertEqual('Auto', next(r['project'] for r in data['roles'] if r['agent'] == 'claude'))
        self.assertEqual(calls, {agent: a.calls for agent, a in self.adapters.items()})

    def test_pending_approval_is_visible_and_role_link_only_navigates(self):
        self.window.panels['codex'].pending_approval_events['fixture'] = {'id': 'fixture'}
        self.window.mode.setCurrentIndex(self.window.mode.findData('Monitor'))
        card = self.window.monitor_dashboard.cards['codex']
        self.assertIn('1 待核准', card.status.text())
        card.action.click()
        self.assertEqual('Workspace', self.window.mode.currentData())
        self.assertEqual('codex', self.window._preferred_agent)
        self.assertNotIn('approve', [c[0] for a in self.adapters.values() for c in a.calls])
        self.window.panels['codex'].pending_approval_events.clear()

    def test_readonly_transcript_view_remains_available(self):
        self.window.mode.setCurrentIndex(self.window.mode.findData('Monitor'))
        self.window.monitor_dashboard.open_transcripts.emit()
        self.assertEqual(0, self.window.stack.currentIndex())
        self.assertTrue(self.window.panels['codex'].monitor)
        self.window.toggle_monitor()
        self.assertIs(self.window.stack.currentWidget(), self.window.monitor_dashboard)

    def test_recent_history_stays_newest_first_and_no_active_run_is_invented(self):
        for index in range(12):
            self.core._record('orchestration', content=f'fixture step {index}')
        data = collect_snapshot(self.core, self.window.panels)
        self.assertIsNone(data['run'])
        self.assertEqual(10, len(data['events']))
        self.assertEqual('fixture step 11', data['events'][0]['summary'])
        self.window.refresh_monitor()
        self.assertIn('未自動恢復', self.window.monitor_dashboard.timeline.text())

    def test_snapshot_validates_each_playbook_once_until_the_setting_changes(self):
        from acw import playbooks
        agents = list(self.window.panels)
        collect_snapshot(self.core, self.window.panels)  # warm the per-agent cache
        with patch.object(playbooks, '_normalize', wraps=playbooks._normalize) as normalize:
            for _ in range(10):
                data = collect_snapshot(self.core, self.window.panels)
            self.assertEqual(0, normalize.call_count)
            self.core.set_setting('playbook.codex', {'role': 'Edited role'})
            data = collect_snapshot(self.core, self.window.panels)
            self.assertEqual(1, normalize.call_count)
            self.assertEqual('Edited role', next(r for r in data['roles'] if r['agent'] == 'codex')['role'])
            saved = dict(playbooks.load(self.core, 'codex'), role='Saved role')
            playbooks.save(self.core, 'codex', saved)
            data = collect_snapshot(self.core, self.window.panels)
            self.assertEqual('Saved role', next(r for r in data['roles'] if r['agent'] == 'codex')['role'])
        self.assertTrue(agents)

    def test_dashboard_reflows_and_treats_html_as_plain_text(self):
        dashboard = self.window.monitor_dashboard
        self.window.mode.setCurrentIndex(self.window.mode.findData('Monitor'))
        self.window.sidebar.hide()
        self.window.show()
        for width, expected in ((1500, 4), (900, 2), (650, 2)):
            self.window.resize(width, 850)
            QApplication.processEvents()
            dashboard.reflow()
            self.assertEqual(expected, dashboard.columns)
            self.assertEqual(0, dashboard.horizontalScrollBar().maximum())
        self.window.sidebar.show()
        QApplication.processEvents()
        dashboard.reflow()
        self.assertEqual(1, dashboard.columns)
        self.assertEqual(Qt.PlainText, dashboard.task.textFormat())
