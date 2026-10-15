"""Independent source-refresh regressions. Run with:

    QT_QPA_PLATFORM=offscreen ../.venv/bin/python -m unittest discover -s tests -v

All data is temporary. The real WorkspaceCore/SQLite store is exercised with
instrumented in-memory adapters; sockets, HTTP and subprocess launches are denied.
These checks do not claim the unavailable legacy tests or live backend/EXE pass.
"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QInputMethodEvent, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QLabel, QMenu, QMessageBox, QPushButton, QToolButton

from acw.adapters.base import Adapter, Capabilities
from acw.core import WorkspaceCore
from acw.store import now
from acw.ui import AGENTS, EventCard, MainWindow, MessageCard, PromptEdit


class OfflineAdapter(Adapter):
    """No external library/client is imported and no credential path is read."""
    def __init__(self, agent):
        super().__init__(lambda *args, **kwargs: None)
        self.agent = agent
        self.calls = []
        self.manual_actions = []
        self.target = "fixture-dot-native-id" if agent == "dot" else ""
        self.target_name = "G8毛" if agent == "dot" else ""
        self.capabilities = Capabilities(
            supports_model_selection=agent != "dot", supports_effort=agent != "dot",
            supports_sessions=True, supports_create_session=agent != "dot",
            supports_files=agent != "dot", supports_tools=agent != "dot",
            supports_project=agent != "dot", supports_cancel=agent != "dot",
            supports_streaming=agent != "dot", supports_history=True,
            supports_approval=agent != "dot",
            models=[{"id": "fixture-model-a", "displayName": "Fixture model A"},
                    {"id": "fixture-model-b", "displayName": "Fixture model B"}]
            if agent != "dot" else [],
            efforts=["low", "high"] if agent != "dot" else [],
            detail="OFFLINE fixture; no live backend")

    def connect(self):
        self.calls.append(("connect",))
        self.set_state("Connected")
        return self.capabilities.to_dict()

    def disconnect(self):
        self.calls.append(("disconnect",))
        self.set_state("Disconnected")

    def create_session(self):
        self.calls.append(("create_session",))
        self.session_id = self.agent + "-created-offline"
        return {"id": self.session_id}

    def resume_session(self, session_id):
        self.calls.append(("resume_session", session_id))
        self.session_id = session_id
        return {"id": session_id}

    def send_message(self, content, model=None, effort=None, attachments=None):
        self.calls.append(("send", content, model, effort, attachments))
        return {"accepted": True, "offline": True}

    def stop(self):
        self.calls.append(("stop",))
        self.set_state("Connected")

    def approve(self, request_id, approved):
        self.calls.append(("approve", request_id, approved))
        return {"request_id": request_id, "approved": approved}

    def list_sessions(self, **kwargs):
        self.calls.append(("discover",))
        return []

    def get_history(self, session_id=None):
        self.calls.append(("history", session_id))
        return []

    def refresh_messages(self, older=False):
        self.calls.append(("read", older))
        return []

    def authorize_manual_action(self, action):
        self.manual_actions.append(action)

    def discover_targets(self):
        self.calls.append(("targets",))
        return [{"id": self.target, "name": self.target_name}]

    def configure_target(self, target, name):
        self.target, self.target_name = target, name
        self.calls.append(("configure_target", target, name))

    def set_project(self, path, metadata=None):
        # This is local context metadata only, deliberately not a backend call.
        self.cwd = path


class OfflineWindow(MainWindow):
    """Deterministic UI command dispatch; still exercises real Core operations."""
    def __init__(self, core):
        self.reported_errors = []
        super().__init__(core)
        self.timer.stop()

    def run(self, operation, callback=None, agent=None, on_error=None):
        try:
            result = operation()
            if callback:
                callback(result)
            return result
        except Exception as exc:
            if agent:
                self.panels[agent].set_state("Error")
            if on_error:
                on_error(str(exc))
            self.show_error(str(exc), False)
            return None

    def show_error(self, message, modal=True):
        self.reported_errors.append(str(message))
        if hasattr(self, "footer"):
            self.footer.setText("Error · " + str(message))


class WorkspaceUiRefreshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.guard = []
        self.qt_exceptions = []
        self.exception_hook = patch("sys.excepthook", side_effect=lambda kind, value, tb: self.qt_exceptions.append(str(value)))
        self.exception_hook.start()
        self.guard.append(self.exception_hook)
        for target in ("socket.create_connection", "socket.socket.connect",
                       "urllib.request.urlopen", "subprocess.Popen", "acw.ui.QMessageBox.question"):
            blocker = patch(target, side_effect=AssertionError("External I/O forbidden: " + target))
            blocker.start()
            self.guard.append(blocker)
        self.temp = tempfile.TemporaryDirectory(prefix="acw-ui-refresh-")
        self.root = Path(self.temp.name)
        self.adapters = {agent: OfflineAdapter(agent) for agent in AGENTS}
        self.core = WorkspaceCore(self.root / "data", self.adapters)
        # No git process, real repo, HOME path, or installed data is used.
        self.core.desktop_sessions = lambda agent: []
        self.core.git_snapshot = lambda *args, **kwargs: {
            "branch": "fixture-branch", "dirty": False, "ahead": 0, "behind": 0,
            "status": "", "diff": "", "log": "", "is_git": False, "error": ""}
        for name in ("alpha", "beta"):
            (self.root / name).mkdir()
        self.project_a = self.core.create_project("Alpha", self.root / "alpha")
        self.project_b = self.core.create_project("Beta", self.root / "beta")
        self.core.select_project(self.project_a["id"], sync=False)
        self.task_a = self.core.create_task("Alpha task")
        self.task_b = self.core.create_task("Second Alpha task")
        self.core.select_project(self.project_b["id"], sync=False)
        self.task_c = self.core.create_task("Beta task")
        for task in (self.task_a, self.task_b, self.task_c):
            project = self.core.get_project(task["project_id"])
            for agent in AGENTS:
                sid = agent + "-" + task["id"]
                self.core.store.insert("sessions", {
                    "id": sid, "agent": agent, "task_id": task["id"],
                    "project_id": project["id"], "title": task["title"] + " chat",
                    "cwd": "" if agent == "dot" else project["repo_path"],
                    "created_at": now(), "updated_at": now(), "metadata": {}})
                self.core.store.update("tasks", {"id": task["id"]}, {agent + "_session": sid})
        self.core.select_task(self.task_a["id"])
        self.core.drain_events()
        self.window = OfflineWindow(self.core)
        self.window.show()
        self.settle()
        self.assertEqual([], self.window.reported_errors, "Fixture construction must not hide UI errors")
        self.adapters_clear_calls()

    def tearDown(self):
        for panel in self.window.panels.values():
            panel.set_state("Disconnected")
        self.window.timer.stop()
        self.window.hide()
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.core.close()
        self.temp.cleanup()
        for blocker in reversed(self.guard):
            blocker.stop()
        self.assertEqual([], self.qt_exceptions, "Unhandled exception in Qt callback")
        self.assertEqual([], self.window.reported_errors, "Unexpected UI error hidden by deterministic test dispatch")

    def settle(self):
        for _ in range(3):
            self.app.processEvents()
        QTest.qWait(1)

    def adapters_clear_calls(self):
        for adapter in self.adapters.values():
            adapter.calls.clear()

    def assert_no_adapter_actions(self):
        self.assertEqual({agent: [] for agent in AGENTS},
                         {agent: adapter.calls for agent, adapter in self.adapters.items()})

    def connect_fixture(self, agent="claude"):
        adapter = self.adapters[agent]
        adapter.state = "Connected"
        adapter.cwd = "" if agent == "dot" else self.core.current_project["repo_path"]
        adapter.session_id = self.core.current_task[agent + "_session"]
        if agent == "dot":
            adapter.target = adapter.session_id
        self.window.refresh_agent(agent)
        self.settle()
        return self.window.panels[agent]

    def choose_enum(self, combo, value):
        index = combo.findData(value)
        self.assertGreaterEqual(index, 0, "Missing internal enum value: " + str(value))
        combo.setCurrentIndex(index)

    def choose_task(self, task):
        # Cache regressions explicitly bind every fixture Agent to the chosen container.
        # Record-page navigation alone now leaves all Agent contexts unchanged.
        for agent in AGENTS: self.core.select_agent_task(agent, task['id'])
        index = self.window.task_combo.findData(task["id"])
        self.assertGreaterEqual(index, 0)
        self.window.task_combo.blockSignals(True)
        self.window.task_combo.setCurrentIndex(index)
        self.window.task_combo.blockSignals(False)
        self.core.select_task(task['id'])
        self.window.reload_context()
        self.settle()
        self.assertEqual(task["id"], self.core.current_task_id)

    def choose_project(self, project):
        for agent in AGENTS: self.core.select_agent_project(agent, project['id'])
        index = self.window.project_combo.findData(project["id"])
        self.assertGreaterEqual(index, 0)
        self.window.project_combo.blockSignals(True)
        self.window.project_combo.setCurrentIndex(index)
        self.window.project_combo.blockSignals(False)
        self.core.select_project(project['id'])
        self.window.reload_context()
        self.settle()
        self.assertEqual(project["id"], self.core.current_project_id)

    def add_saved_response(self, agent="claude", text="Offline saved response", mid="fixture-response"):
        self.core.store.insert("messages", {
            "id": mid, "task_id": self.core.current_task_id, "agent": agent,
            "session_id": self.core.current_task[agent + "_session"], "role": "assistant",
            "content": text, "timestamp": now(), "status": "complete", "metadata": {}})
        self.window.reload_context()
        self.settle()
        return self.core.store.get("messages", {"id": mid})

    def test_startup_and_poll_do_not_connect_read_send_or_discover(self):
        self.window.poll_events()
        self.window.reload_context()
        self.window.poll_events()
        self.settle()
        self.assert_no_adapter_actions()
        self.assertEqual("Workspace", self.window.mode.currentData())
        self.assertEqual("assisted", self.window.handoff_mode.currentData())

    def test_primary_labels_are_traditional_chinese_with_stable_internal_enums(self):
        self.assertEqual(["Monitor 工作台", "協作總覽（唯讀）", "時間線", "歷史"],
                         [self.window.mode.itemText(i) for i in range(self.window.mode.count())])
        self.assertEqual(["Workspace", "Monitor", "Timeline", "History"],
                         [self.window.mode.itemData(i) for i in range(self.window.mode.count())])
        self.assertEqual(["自動布局", "並排", "專注"],
                         [self.window.layout_mode.itemText(i) for i in range(self.window.layout_mode.count())])
        self.assertEqual(["Auto", "Three panes", "Focus"],
                         [self.window.layout_mode.itemData(i) for i in range(self.window.layout_mode.count())])
        self.assertEqual("工作詳情", self.window.details_toggle.text())
        self.assertEqual(["預覽後傳送", "手動直接傳送"],
                         [self.window.handoff_mode.itemText(i) for i in range(self.window.handoff_mode.count())])
        self.assertEqual(["assisted", "manual"],
                         [self.window.handoff_mode.itemData(i) for i in range(self.window.handoff_mode.count())])
        for panel in self.window.panels.values():
            for control, title in ((panel.connect_button, "連線"), (panel.send_button, "傳送"),
                    (panel.stop_button, "停止"), (panel.attach_button, "附件"), (panel.new_button, "新對話"),
                    (panel.resume_button, "開啟對話"), (panel.rename_button, "重新命名"),
                    (panel.discover_button, "探索原生對話…")):
                self.assertEqual(title, control.text())
            self.assertEqual("未連線", panel.state.text())
        self.assertEqual("由 ChatGPT 管理", self.window.panels["dot"].model.currentText())
        self.assertEqual("由 ChatGPT 管理", self.window.panels["dot"].effort.currentText())
        self.assert_no_adapter_actions()

    def test_localized_task_status_persists_internal_status_enum(self):
        self.choose_enum(self.window.task_status, "PLANNING")
        self.assertEqual("PLANNING", self.core.current_task["status"])
        self.assertEqual("規劃中", self.window.task_status.currentText())
        self.window.reload_context()
        self.settle()
        self.assertEqual("PLANNING", self.window.task_status.currentData())
        self.assertEqual("規劃中", self.window.task_status.currentText())
        self.assertLess(self.window.task_status.findData("APPROVED"), 0)
        self.assert_no_adapter_actions()

    def test_independent_agent_panels_and_flexible_roles(self):
        self.assertEqual(set(AGENTS), set(self.window.panels))
        self.assertEqual(4, self.window.role_tabs.count())
        labels = [self.window.role_tabs.tabText(i) for i in range(3)]
        self.assertIn("Claude", labels[0])
        self.assertIn("G8毛", labels[1])
        self.assertIn("Codex", labels[2])
        self.assertIn("Hermes", self.window.role_tabs.tabText(3))
        role_text = [self.window.panels[a].title.toolTip().casefold() + " " +
                     " ".join(l.text() for l in self.window.panels[a].findChildren(QLabel)).casefold()
                     for a in AGENTS]
        self.assertIn("協作 agent", role_text[0])
        self.assertTrue("relay" in role_text[1] or "轉" in role_text[1] or "secondary" in role_text[1], role_text[1])
        self.assertIn("協作 agent", role_text[2])
        self.assert_no_adapter_actions()

    def test_agent_selectors_and_sidebar_follow_the_same_agent(self):
        self.window.resize(1800, 1000)
        self.window.layout_mode.setCurrentIndex(self.window.layout_mode.findData('Focus'))
        self.settle()
        self.assertTrue(self.window.agent_rail.isVisible())
        self.assertFalse(self.window.role_tabs.isVisible())
        self.window.agent_rail.open_role.emit('codex')
        self.assertEqual('codex', self.window._preferred_agent)
        self.assertEqual('codex', self.window.navigator.agent)
        self.assertEqual(self.window.agents.index('codex'), self.window.session_tabs.currentIndex())
        self.assertTrue(self.window.context_title.text().startswith('Codex'))
        self.assertEqual('專案與對話…', self.window.panels['codex'].context_button.text())
        self.assertIn(self.window.panels['codex'].state.text(), self.window.sidebar_agent_title.text())
        self.window.layout_mode.setCurrentIndex(self.window.layout_mode.findData('Three panes'))
        self.settle()
        self.assertFalse(self.window.agent_rail.isVisible())
        self.assertTrue(self.window.role_tabs.isVisible())
        self.window.sidebar.hide()
        self.window.resize(650, 900)
        self.settle()
        self.assertTrue(self.window.role_tabs.isVisible(), 'Narrow windows need a visible selector')
        self.assertFalse(self.window.agent_rail.isVisible())
        self.assert_no_adapter_actions()

    def test_navigator_handles_unsupported_providers_and_additional_instances(self):
        nav = self.window.navigator
        self.window.focus_role('local')
        self.assertIn('沒有本機歷史對話', nav.empty.text())
        self.assertTrue(nav.empty.isVisible())
        self.assertFalse(nav.tree.isVisible())
        self.window.focus_role('claude')
        self.assertTrue(nav.tree.isVisible())
        self.assertFalse(nav.empty.isVisible())
        extra = self.window.add_agent_instance('codex', 'Second Codex', project_id=self.project_b['id'])
        self.assertEqual('codex', nav.agent)
        self.assertEqual(extra, nav._agent)
        self.assertTrue(nav.tree.isVisible())
        nav.set_sessions('codex', [dict(id='fixture-native', agent='codex', cwd=self.project_b['repo_path'],
            title='Second instance history', cwd_exists=True, archived=False, created=now(), last_activity=now())])
        nav.tree.setCurrentItem(nav.tree.topLevelItem(0).child(0))
        with patch.object(self.window, 'open_desktop_session') as opened:
            nav.open_selected(False)
        self.assertEqual(extra, opened.call_args.args[0]['agent'])
        with patch.object(self.window, 'new_desktop_conversation') as created:
            nav.new_conversation()
        self.assertEqual(extra, created.call_args.args[1])

    def test_navigator_discards_stale_provider_rows_during_async_load(self):
        nav = self.window.navigator
        nav.sessions['codex'] = None
        pending = []
        with patch.object(self.window, 'run', side_effect=lambda operation, callback, **kwargs: pending.append(callback)):
            self.window.focus_role('codex')
            self.assertEqual(0, nav.tree.topLevelItemCount())
            self.window.focus_role('local')
            pending[0]([])
        self.assertFalse(nav.tree.isVisible())
        self.assertEqual('', nav.status.text())
        self.window.focus_role('claude')
        self.assertTrue(nav.tree.isVisible())

    def test_navigator_filters_exact_bound_directory_before_repository_grouping(self):
        nav = self.window.navigator
        def row(sid, project):
            return dict(id=sid, agent='claude', cwd=project['repo_path'], title=sid,
                        project_key='same-repository-origin', project='shared origin', cwd_exists=True,
                        archived=False, created=now(), last_activity=now())
        nav.set_sessions('claude', [row('alpha', self.project_a), row('beta', self.project_b)])
        self.assertTrue(nav.nav_all_projects.isEnabled())
        self.assertFalse(nav.nav_all_projects.isChecked())
        self.assertEqual(1, nav.tree.topLevelItemCount())
        self.assertEqual(1, nav.tree.topLevelItem(0).childCount())
        self.assertEqual('alpha', nav.tree.topLevelItem(0).child(0).data(0, Qt.UserRole)['id'])
        nav.nav_all_projects.setChecked(True)
        self.assertEqual(2, nav.tree.topLevelItem(0).childCount())
        rows = [row('alpha', self.project_a), row('beta', self.project_b)]
        for item in rows:
            item.pop('project_key')
        nav.set_sessions('claude', rows)
        self.assertEqual(2, nav.tree.topLevelItemCount())
        nav.nav_all_projects.setChecked(False)
        self.core.select_agent_project('claude', self.project_b['id'])
        self.window.reload_context()
        self.assertEqual('beta', nav.tree.topLevelItem(0).child(0).data(0, Qt.UserRole)['id'])

    def test_visible_view_switch_returns_from_timeline_and_readonly_transcripts(self):
        self.window.mode.setCurrentIndex(self.window.mode.findData('Timeline'))
        QTest.mouseClick(self.window.workspace_views, Qt.LeftButton, pos=self.window.workspace_views.tabRect(0).center())
        self.assertEqual('Workspace', self.window.mode.currentData())
        self.window.mode.setCurrentIndex(self.window.mode.findData('Monitor'))
        self.window.show_monitor_transcripts()
        self.assertEqual(0, self.window.stack.currentIndex())
        QTest.mouseClick(self.window.workspace_views, Qt.LeftButton, pos=self.window.workspace_views.tabRect(1).center())
        self.assertIs(self.window.stack.currentWidget(), self.window.monitor_dashboard)
        self.assertEqual('Monitor', self.window.mode.currentData())

    def test_records_dialog_keeps_global_navigation_and_agent_binding_separate(self):
        bindings = {agent: self.core.agent_project(agent) for agent in self.window.agents}
        self.window.show_records()
        self.settle()
        self.assertTrue(self.window.records_dialog.isVisible())
        self.assertTrue(self.window.project_combo.isVisible())
        self.assertTrue(self.window.task_combo.isVisible())
        self.assertTrue(self.window.records_dialog.isAncestorOf(self.window.project_combo))
        self.assertTrue(self.window.records_dialog.isAncestorOf(self.window.task_combo))
        self.window.project_combo.setCurrentIndex(self.window.project_combo.findData(self.project_b['id']))
        self.assertEqual(self.project_b['id'], self.core.current_project_id)
        self.assertEqual(bindings, {agent: self.core.agent_project(agent) for agent in self.window.agents})
        self.window.records_dialog.close()
        self.assertTrue(self.window.context_title.text().startswith('Claude'))

    def test_sidebar_contains_project_task_and_every_session_control(self):
        sidebar = self.window.sidebar
        self.assertTrue(self.window.records_dialog.isAncestorOf(self.window.project_combo))
        self.assertTrue(self.window.records_dialog.isAncestorOf(self.window.task_combo))
        for agent, panel in self.window.panels.items():
            self.assertTrue(sidebar.isAncestorOf(panel.session_controls), agent)
            for control in (panel.session, panel.session_search, panel.session_details,
                            panel.new_button, panel.resume_button, panel.rename_button,
                            panel.discover_button):
                self.assertTrue(panel.session_controls.isAncestorOf(control), control.objectName())
            if agent == "dot":
                for control in (panel.dot_select, panel.dot_refresh, panel.dot_older):
                    self.assertTrue(panel.session_controls.isAncestorOf(control))

    def test_sidebar_toggle_retains_widgets_selection_and_draft(self):
        panel = self.window.panels["claude"]
        panel.input.setPlainText("Keep this draft")
        selected = panel.session.currentData()
        QTest.mouseClick(self.window.sidebar_toggle, Qt.LeftButton)
        self.settle()
        self.assertFalse(self.window.sidebar.isVisible())
        QTest.mouseClick(self.window.sidebar_toggle, Qt.LeftButton)
        self.settle()
        self.assertTrue(self.window.sidebar.isVisible())
        self.assertEqual("Keep this draft", panel.input.toPlainText())
        self.assertEqual(selected, panel.session.currentData())
        self.assert_no_adapter_actions()

    def test_composer_keeps_model_effort_send_stop_accessible(self):
        panel = self.connect_fixture()
        self.assertTrue(panel.isAncestorOf(panel.model))
        self.assertTrue(panel.isAncestorOf(panel.effort))
        self.assertTrue(panel.model.isEnabled())
        self.assertTrue(panel.effort.isEnabled())
        self.assertTrue(panel.send_button.isVisible())
        self.assertTrue(panel.stop_button.isVisible())
        self.assertEqual("fixture-model-a", panel.model.currentData())
        self.assertEqual("low", panel.effort.currentData())

    def test_ctrl_enter_sends_exact_content_once_only_after_explicit_input(self):
        panel = self.connect_fixture()
        panel.input.setPlainText("  exact draft\n中文  ")
        panel.input.setFocus()
        QTest.keyClick(panel.input, Qt.Key_Return, Qt.ControlModifier)
        self.settle()
        self.assertEqual([("send", "  exact draft\n中文  ", "fixture-model-a", "low", None)],
                         self.adapters["claude"].calls)
        self.assertEqual("", panel.input.toPlainText())
        QTest.keyClick(panel.input, Qt.Key_Return, Qt.ControlModifier)
        self.assertEqual(1, len(self.adapters["claude"].calls))

    def test_plain_enter_is_newline_and_never_submits(self):
        panel = self.connect_fixture()
        panel.input.setPlainText("line")
        panel.input.moveCursor(QTextCursor.End)
        QTest.keyClick(panel.input, Qt.Key_Return)
        self.assertEqual("line\n", panel.input.toPlainText())
        self.assert_no_adapter_actions()

    def test_ctrl_enter_does_not_submit_during_ime_preedit(self):
        panel = self.connect_fixture()
        panel.input.setPlainText("draft before composition")
        panel.input.setFocus()
        self.app.sendEvent(panel.input, QInputMethodEvent("注音", []))
        QTest.keyClick(panel.input, Qt.Key_Return, Qt.ControlModifier)
        self.settle()
        self.assert_no_adapter_actions()
        self.assertEqual("draft before composition", panel.input.toPlainText())
        self.app.sendEvent(panel.input, QInputMethodEvent("", []))
        QTest.keyClick(panel.input, Qt.Key_Return, Qt.ControlModifier)
        self.assertEqual("send", self.adapters["claude"].calls[0][0])

    def test_disconnected_ctrl_enter_retains_draft_and_does_not_send(self):
        panel = self.window.panels["claude"]
        panel.input.setPlainText("unsent offline")
        QTest.keyClick(panel.input, Qt.Key_Return, Qt.ControlModifier)
        self.assertEqual("unsent offline", panel.input.toPlainText())
        self.assert_no_adapter_actions()

    def test_minimum_width_keeps_sidebar_and_focused_composer_without_horizontal_overflow(self):
        self.window.resize(640, 720)
        self.choose_enum(self.window.layout_mode, "Auto")
        self.window.update_workspace_layout()
        self.settle()
        self.assertTrue(self.window.sidebar.isVisible())
        self.assertEqual(0, self.window.workspace_scroll.horizontalScrollBar().maximum())
        self.assertEqual(1, sum(panel.isVisible() for panel in self.window.panels.values()))
        self.assertTrue(self.window.panels["claude"].send_button.isVisible())

    def test_details_expansion_keeps_a_usable_transcript_at_compact_height(self):
        self.window.resize(800, 600)
        self.window.update_workspace_layout()
        self.settle()
        self.window.toggle_details()
        self.settle()
        panel = next(panel for panel in self.window.panels.values() if panel.isVisible())
        self.assertGreaterEqual(panel.scroll.height(), 100)
        self.assertTrue(panel.send_button.isVisible())
        self.assertEqual(0, self.window.workspace_scroll.horizontalScrollBar().maximum())

    def test_explicit_connect_restores_only_bound_session_and_disconnect_does_not_read_history(self):
        panel = self.window.panels["claude"]
        QTest.mouseClick(panel.connect_button, Qt.LeftButton)
        self.settle()
        sid = self.core.agent_task('claude')['claude_session']
        self.assertEqual([("connect",), ('resume_session', sid)], self.adapters["claude"].calls)
        self.assertEqual("Connected", panel.connection_state)
        self.assertEqual(sid, self.adapters["claude"].session_id)
        QTest.mouseClick(panel.connect_button, Qt.LeftButton)
        self.settle()
        self.assertEqual([("connect",), ('resume_session', sid), ("disconnect",)], self.adapters["claude"].calls)
        self.assertEqual("Disconnected", panel.connection_state)

    def test_new_session_requires_click_and_does_not_send_existing_draft(self):
        panel = self.connect_fixture("claude")
        old_session = self.core.current_task["claude_session"]
        panel.input.setPlainText("original native session draft")
        self.assert_no_adapter_actions()
        QTest.mouseClick(panel.new_button, Qt.LeftButton)
        self.settle()
        self.assertEqual([("create_session",)], self.adapters["claude"].calls)
        self.assertEqual("claude-created-offline", self.core.agent_task('claude')["claude_session"])
        self.assertEqual(old_session, self.core.current_task['claude_session'])
        self.assertEqual("", panel.input.toPlainText())
        self.core.select_agent_task('claude', self.task_a['id'])
        self.window.reload_context()
        self.settle()
        self.assertEqual("original native session draft", panel.input.toPlainText())

    def test_local_rename_preserves_native_id_and_never_calls_backend(self):
        panel = self.window.panels["claude"]
        sid = panel.session.currentData()
        self.assertTrue(sid)
        with patch("acw.ui.QInputDialog.getText", return_value=("New local label", True)):
            panel.rename_session()
        self.settle()
        self.assertEqual("New local label", self.core.store.get("sessions", {"agent": "claude", "id": sid})["title"])
        self.assertEqual(sid, panel.session.currentData())
        self.assertEqual(sid, self.core.current_task["claude_session"])
        self.assert_no_adapter_actions()

    def test_explicit_stop_uses_only_supported_adapter_cancellation(self):
        panel = self.connect_fixture("claude")
        self.adapters["claude"].state = "Busy"
        panel.set_state("Busy")
        self.assertTrue(panel.stop_button.isEnabled())
        QTest.mouseClick(panel.stop_button, Qt.LeftButton)
        self.window.poll_events()
        self.settle()
        self.assertEqual([("stop",)], self.adapters["claude"].calls)
        self.assertEqual("Connected", panel.connection_state)
        self.assertEqual([], self.adapters["dot"].calls)
        self.assertEqual([], self.adapters["codex"].calls)

    def test_ime_commit_is_sent_exactly_once_after_preedit_finishes(self):
        panel = self.connect_fixture("claude")
        panel.input.setPlainText("draft")
        panel.input.moveCursor(QTextCursor.End)
        self.app.sendEvent(panel.input, QInputMethodEvent("文", []))
        QTest.keyClick(panel.input, Qt.Key_Return, Qt.ControlModifier)
        self.assert_no_adapter_actions()
        committed = QInputMethodEvent("", [])
        committed.setCommitString("文")
        self.app.sendEvent(panel.input, committed)
        self.assertEqual("draft文", panel.input.toPlainText())
        QTest.keyClick(panel.input, Qt.Key_Return, Qt.ControlModifier)
        self.assertEqual([("send", "draft文", "fixture-model-a", "low", None)], self.adapters["claude"].calls)

    def test_narrow_auto_layout_has_one_reachable_role_and_no_horizontal_clipping(self):
        self.window.resize(760, 720)
        self.choose_enum(self.window.layout_mode, "Auto")
        self.window.update_workspace_layout()
        self.settle()
        self.assertEqual(1, sum(panel.isVisible() for panel in self.window.panels.values()))
        self.assertTrue(self.window.role_tabs.isVisible())
        self.assertTrue(self.window.sidebar_toggle.isVisible())
        self.assertEqual(0, self.window.workspace_scroll.horizontalScrollBar().maximum())
        visible = next(p for p in self.window.panels.values() if p.isVisible())
        self.assertTrue(visible.send_button.isVisible())
        self.assertTrue(visible.input.isVisible())
        self.assertGreater(visible.scroll.height(), 80)

    def test_wide_auto_layout_shows_all_three_transcripts(self):
        self.window.resize(1650, 950)
        self.choose_enum(self.window.layout_mode, "Auto")
        self.window.update_workspace_layout()
        self.settle()
        self.assertTrue(all(panel.isVisible() for panel in self.window.panels.values()))
        for panel in self.window.panels.values():
            self.assertGreater(panel.scroll.height(), 140)
        self.assert_no_adapter_actions()

    def test_role_tabs_focus_each_panel_without_touching_drafts(self):
        self.choose_enum(self.window.layout_mode, "Focus")
        for agent, panel in self.window.panels.items():
            panel.input.setPlainText(agent + " independent draft")
        for index, agent in enumerate(AGENTS):
            self.window.role_tabs.setCurrentIndex(index)
            self.window.update_workspace_layout()
            self.settle()
            self.assertTrue(self.window.panels[agent].isVisible())
            self.assertEqual(1, sum(p.isVisible() for p in self.window.panels.values()))
        self.choose_enum(self.window.layout_mode, "Three panes")
        self.window.resize(1650, 950)
        self.window.update_workspace_layout()
        self.settle()
        for agent, panel in self.window.panels.items():
            self.assertEqual(agent + " independent draft", panel.input.toPlainText())
        self.assert_no_adapter_actions()

    def test_focus_roundtrip_preserves_prompt_selection_and_scroll(self):
        panel = self.window.panels["claude"]
        for number in range(24):
            panel.add_message({"id": "scroll-message-" + str(number), "role": "assistant",
                               "content": "line " * 50, "timestamp": now()})
        self.settle()
        bar = panel.scroll.verticalScrollBar()
        self.assertGreater(bar.maximum(), 100)
        bar.setValue(80)
        panel.input.setPlainText("keep selection here")
        cursor = panel.input.textCursor()
        cursor.setPosition(2)
        cursor.setPosition(8, QTextCursor.KeepAnchor)
        panel.input.setTextCursor(cursor)
        self.window.focus_agent("codex")
        self.settle()
        self.window.focus_agent(None)
        self.settle()
        self.assertEqual("ep sel", panel.input.textCursor().selectedText())
        self.assertEqual(80, bar.value())
        self.assert_no_adapter_actions()

    def test_task_roundtrip_preserves_all_three_independent_drafts(self):
        for agent, panel in self.window.panels.items():
            panel.input.setPlainText(agent + " alpha draft")
        with patch("acw.ui.QMessageBox.question", side_effect=AssertionError("Preserved drafts must not ask to discard")):
            self.choose_task(self.task_b)
            for agent, panel in self.window.panels.items():
                self.assertEqual(agent + " alpha draft" if agent == "dot" else "", panel.input.toPlainText())
                panel.input.setPlainText(agent + " beta draft")
            self.choose_task(self.task_a)
            for agent, panel in self.window.panels.items():
                self.assertEqual(agent + (" beta draft" if agent == "dot" else " alpha draft"), panel.input.toPlainText())
            self.choose_task(self.task_b)
            for agent, panel in self.window.panels.items():
                self.assertEqual(agent + " beta draft", panel.input.toPlainText())
        self.assert_no_adapter_actions()

    def test_project_roundtrip_preserves_drafts_and_task_context(self):
        panel = self.window.panels["claude"]
        panel.input.setPlainText("Alpha project unsent")
        self.choose_project(self.project_b)
        self.choose_task(self.task_c)
        self.assertEqual("", panel.input.toPlainText())
        panel.input.setPlainText("Beta project unsent")
        self.choose_project(self.project_a)
        self.choose_task(self.task_a)
        self.assertEqual("Alpha project unsent", panel.input.toPlainText())
        self.choose_project(self.project_b)
        self.choose_task(self.task_c)
        self.assertEqual("Beta project unsent", panel.input.toPlainText())
        self.assert_no_adapter_actions()

    def test_context_roundtrip_keeps_attachments_selection_model_effort(self):
        panel = self.connect_fixture()
        # Return to offline so context switching remains entirely local.
        self.adapters["claude"].state = "Disconnected"
        panel.set_state("Disconnected")
        file = self.root / "draft.txt"
        file.write_text("offline test attachment", encoding="utf-8")
        panel.add_attachments([str(file)])
        panel.input.setPlainText("selection survives")
        cursor = panel.input.textCursor()
        cursor.setPosition(1)
        cursor.setPosition(7, QTextCursor.KeepAnchor)
        panel.input.setTextCursor(cursor)
        panel.model.setCurrentIndex(1)
        panel.effort.setCurrentIndex(1)
        self.choose_task(self.task_b)
        self.assertEqual([], panel.attachments)
        self.choose_task(self.task_a)
        self.assertEqual([str(file)], panel.attachments)
        self.assertEqual("electi", panel.input.textCursor().selectedText())
        self.assertEqual("fixture-model-b", panel.model.currentData())
        self.assertEqual("high", panel.effort.currentData())
        self.assert_no_adapter_actions()

    def test_refresh_same_context_does_not_reset_draft_or_session_filter(self):
        panel = self.window.panels["claude"]
        panel.input.setPlainText("same context draft")
        panel.session_search.setText("Alpha task")
        selected = panel.session.currentData()
        self.window.reload_context()
        self.settle()
        self.assertEqual("same context draft", panel.input.toPlainText())
        self.assertEqual("Alpha task", panel.session_search.text())
        self.assertEqual(selected, panel.session.currentData())
        self.assert_no_adapter_actions()

    def test_native_session_mapping_has_separate_draft_cache(self):
        panel = self.window.panels["claude"]
        old = self.core.current_task["claude_session"]
        new = "claude-alternate-native-session"
        self.core.store.insert("sessions", {"id": new, "agent": "claude", "task_id": self.core.current_task_id,
            "project_id": self.core.current_project_id, "title": "Alternate native mapping", "cwd": str(self.root / "alpha"),
            "created_at": now(), "updated_at": now(), "metadata": {}})
        panel.input.setPlainText("original native draft")
        self.window.save_context_state()
        self.core.store.update("tasks", {"id": self.core.current_task_id}, {"claude_session": new})
        self.window.reload_context()
        self.assertEqual("", panel.input.toPlainText())
        panel.input.setPlainText("alternate native draft")
        self.window.save_context_state()
        self.core.store.update("tasks", {"id": self.core.current_task_id}, {"claude_session": old})
        self.window.reload_context()
        self.assertEqual("original native draft", panel.input.toPlainText())
        self.assert_no_adapter_actions()

    def test_context_roundtrip_preserves_transcript_scroll_and_message_selection(self):
        panel = self.window.panels["claude"]
        for number in range(24):
            self.core.store.insert("messages", {"id": "saved-scroll-" + str(number),
                "task_id": self.core.current_task_id, "agent": "claude",
                "session_id": self.core.current_task["claude_session"], "role": "assistant",
                "content": "select this saved response " * 12, "timestamp": now(),
                "status": "complete", "metadata": {}})
        self.window.reload_context()
        self.settle()
        card = panel.cards["saved-scroll-0"]
        cursor = card.body.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(6, QTextCursor.KeepAnchor)
        card.body.setTextCursor(cursor)
        bar = panel.scroll.verticalScrollBar()
        self.assertGreater(bar.maximum(), 100)
        bar.setValue(85)
        self.choose_task(self.task_b)
        self.choose_task(self.task_a)
        self.assertEqual("select", panel.cards["saved-scroll-0"].body.textCursor().selectedText())
        self.assertEqual(85, panel.scroll.verticalScrollBar().value())
        self.assert_no_adapter_actions()

    def test_session_picker_search_is_local_and_resume_requires_click(self):
        panel = self.connect_fixture("claude")
        active = self.adapters["claude"].session_id
        panel.session_search.setText("Second Alpha task")
        self.settle()
        self.assertEqual(2, panel.session.count())
        panel.session.setCurrentIndex(1)
        self.assertNotEqual(active, panel.session.currentData())
        self.assert_no_adapter_actions()
        QTest.mouseClick(panel.resume_button, Qt.LeftButton)
        self.settle()
        self.assertEqual([("resume_session", panel.session.currentData())], self.adapters["claude"].calls)

    def test_explicit_discovery_does_not_resume_or_read_native_history(self):
        panel = self.connect_fixture("claude")
        before = self.core.current_task["claude_session"]
        with patch("acw.ui.NativeSessionDialog.exec", return_value=QDialog.Rejected):
            panel.discover_sessions()
        self.assertEqual([("discover",)], self.adapters["claude"].calls)
        self.assertEqual(before, self.core.current_task["claude_session"])

    def test_message_update_preserves_readonly_selection(self):
        message = self.add_saved_response(text="first response exact")
        card = self.window.panels["claude"].cards[message["id"]]
        cursor = card.body.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(5, QTextCursor.KeepAnchor)
        card.body.setTextCursor(cursor)
        card.update_content("first response exact plus completion")
        self.assertEqual("first", card.body.textCursor().selectedText())
        self.assertEqual("first response exact plus completion", card.body.toPlainText())
        self.assert_no_adapter_actions()

    def test_unknown_capability_is_distinct_from_explicit_unsupported(self):
        panel = self.window.panels["claude"]
        panel.set_state("Disconnected")
        panel.update_capabilities({})
        unknown = panel.model.currentText() + " " + panel.effort.currentText() + " " + panel.notice.text()
        self.assertNotIn("不支援", unknown)
        self.assertIn("尚未偵測", unknown)
        panel.set_state("Connected")
        panel.update_capabilities({"supports_model_selection": False, "supports_effort": False,
                                   "supports_sessions": True, "detail": "Known offline fixture"})
        known = panel.model.currentText() + " " + panel.effort.currentText()
        self.assertIn("不支援", known)
        self.assertFalse(panel.model.isEnabled())
        self.assertFalse(panel.effort.isEnabled())

    def test_initial_mapped_session_is_selected_without_resuming_backend(self):
        for agent, panel in self.window.panels.items():
            self.assertEqual(self.core.current_task[agent + "_session"], panel.session.currentData())
            self.assertEqual("", self.adapters[agent].session_id)
            self.assertTrue(panel.session_details.isEnabled())
        self.assert_no_adapter_actions()

    def test_incompatible_effort_requires_explicit_choice_before_send(self):
        panel = self.connect_fixture("claude")
        with patch.object(self.adapters["claude"], "list_efforts",
                          side_effect=lambda model=None: ["low", "high"] if model == "fixture-model-a" else ["low"]):
            panel.update_capabilities(self.adapters["claude"].capabilities)
            panel.effort.setCurrentIndex(panel.effort.findData("high"))
            self.assertEqual("high", panel.effort.currentData())
            panel.input.setPlainText("do not silently downgrade effort")
            panel.model.setCurrentIndex(panel.model.findData("fixture-model-b"))
            self.assertIsNone(panel.effort.currentData())
            self.assertIn("請選擇支援的強度", panel.effort.currentText())
            self.assertFalse(panel.send_button.isEnabled())
            QTest.keyClick(panel.input, Qt.Key_Return, Qt.ControlModifier)
            self.assertEqual("do not silently downgrade effort", panel.input.toPlainText())
            self.assert_no_adapter_actions()
            panel.effort.setCurrentIndex(panel.effort.findData("low"))
            self.assertTrue(panel.send_button.isEnabled())
            QTest.keyClick(panel.input, Qt.Key_Return, Qt.ControlModifier)
        self.assertEqual([("send", "do not silently downgrade effort", "fixture-model-b", "low", None)],
                         self.adapters["claude"].calls)

    def test_effort_choice_required_survives_repeated_metadata_refresh(self):
        panel = self.connect_fixture("claude")
        with patch.object(self.adapters["claude"], "list_efforts",
                          side_effect=lambda model=None: ["low", "high"] if model == "fixture-model-a" else ["low"]):
            panel.update_capabilities(self.adapters["claude"].capabilities)
            panel.effort.setCurrentIndex(panel.effort.findData("high"))
            panel.input.setPlainText("retain unresolved effort choice")
            panel.model.setCurrentIndex(panel.model.findData("fixture-model-b"))
            self.assertIsNone(panel.effort.currentData())
            self.assertTrue(panel._effort_invalid)
            for refresh in (lambda: self.window.refresh_agent("claude"),
                            lambda: panel.update_capabilities(self.adapters["claude"].capabilities),
                            lambda: panel.update_capabilities(self.adapters["claude"].capabilities)):
                refresh()
                self.settle()
                self.assertIsNone(panel.effort.currentData())
                self.assertTrue(panel._effort_invalid)
                self.assertFalse(panel.send_button.isEnabled())
                QTest.keyClick(panel.input, Qt.Key_Return, Qt.ControlModifier)
                self.assertEqual("retain unresolved effort choice", panel.input.toPlainText())
                self.assert_no_adapter_actions()
            panel.effort.setCurrentIndex(panel.effort.findData("low"))
            self.window.refresh_agent("claude")
            self.assertEqual("low", panel.effort.currentData())
            self.assertTrue(panel.send_button.isEnabled())
        self.assert_no_adapter_actions()

    def test_effort_choice_required_survives_reload_and_task_cache_roundtrip(self):
        panel = self.connect_fixture("claude")
        with patch.object(self.adapters["claude"], "list_efforts",
                          side_effect=lambda model=None: ["low", "high"] if model == "fixture-model-a" else ["low"]):
            panel.update_capabilities(self.adapters["claude"].capabilities)
            panel.effort.setCurrentIndex(panel.effort.findData("high"))
            panel.model.setCurrentIndex(panel.model.findData("fixture-model-b"))
            panel.input.setPlainText("cached choice-required draft")
            self.window.save_context_state()
            self.window.reload_context()
            self.settle()
            self.assertIsNone(panel.effort.currentData())
            self.assertTrue(panel._effort_invalid)
            self.assertFalse(panel.send_button.isEnabled())
            self.choose_task(self.task_b)
            # A human selects a supported effort in B, leaving A unresolved.
            panel.effort.setCurrentIndex(panel.effort.findData("low"))
            self.choose_task(self.task_a)
            self.assertEqual("fixture-model-b", panel.model.currentData())
            self.assertIsNone(panel.effort.currentData())
            self.assertTrue(panel._effort_invalid)
            self.assertFalse(panel.send_button.isEnabled())
            self.assertEqual("cached choice-required draft", panel.input.toPlainText())
            QTest.keyClick(panel.input, Qt.Key_Return, Qt.ControlModifier)
            self.assert_no_adapter_actions()
            panel.effort.setCurrentIndex(panel.effort.findData("low"))
            self.window.reload_context()
            self.settle()
            self.assertEqual("low", panel.effort.currentData())
            self.assertTrue(panel.send_button.isEnabled())
        self.assert_no_adapter_actions()

    def test_uncached_task_has_valid_supported_effort_without_stale_required_choice(self):
        panel = self.connect_fixture("claude")
        with patch.object(self.adapters["claude"], "list_efforts",
                          side_effect=lambda model=None: ["low", "high"] if model == "fixture-model-a" else ["low"]):
            panel.update_capabilities(self.adapters["claude"].capabilities)
            panel.effort.setCurrentIndex(panel.effort.findData("high"))
            panel.model.setCurrentIndex(panel.model.findData("fixture-model-b"))
            panel.input.setPlainText("task A unresolved draft")
            self.assertIsNone(panel.effort.currentData())
            self.assertTrue(panel._effort_invalid)
            self.choose_task(self.task_b)
            self.assertFalse(panel._effort_invalid)
            self.assertIn(panel.effort.currentData(), ("low", "high"))
            self.assertNotIn("請選擇支援的強度", panel.effort.currentText())
            self.assertEqual("", panel.input.toPlainText())
            self.choose_task(self.task_a)
            self.assertTrue(panel._effort_invalid)
            self.assertIsNone(panel.effort.currentData())
            self.assertFalse(panel.send_button.isEnabled())
            self.assertEqual("task A unresolved draft", panel.input.toPlainText())
        self.assert_no_adapter_actions()

    def test_effort_detection_failure_is_labeled_failure_not_unsupported(self):
        panel = self.connect_fixture("claude")
        with patch.object(self.adapters["claude"], "list_efforts", side_effect=RuntimeError("offline effort detection error")):
            panel.model_changed()
            self.assertEqual("偵測失敗", panel.effort.currentText())
            self.assertIn("offline effort detection error", panel.effort.toolTip())
            self.assertNotIn("不支援", panel.effort.currentText())
            self.assertFalse(panel.effort.isEnabled())
            self.assertIsNone(panel.effort.currentData())
        self.assert_no_adapter_actions()

    def test_supported_but_empty_choices_are_unavailable_not_unsupported(self):
        panel = self.connect_fixture("claude")
        caps = self.adapters["claude"].capabilities.to_dict()
        caps["models"] = []
        caps["efforts"] = []
        with patch.object(self.adapters["claude"], "list_efforts", return_value=[]):
            panel.update_capabilities(caps)
            self.assertEqual("模型清單暫不可用", panel.model.currentText())
            self.assertIn("選項暫不可用", panel.effort.currentText())
            self.assertNotIn("不支援", panel.effort.currentText())
            self.assertNotIn("失敗", panel.effort.currentText())
            self.assertFalse(panel.model.isEnabled())
            self.assertFalse(panel.effort.isEnabled())
            self.assertIsNone(panel.model.currentData())
            self.assertIsNone(panel.effort.currentData())
        self.assert_no_adapter_actions()

    def test_dot_manual_actions_remain_explicit_no_streaming_or_creation(self):
        panel = self.connect_fixture("dot")
        self.assertFalse(panel.new_button.isEnabled())
        self.assertFalse(panel.stop_button.isEnabled())
        self.assertFalse(panel.attach_button.isVisible())
        self.assertFalse(panel.discover_button.isEnabled())
        self.assertTrue(panel.resume_button.isEnabled())
        self.assertTrue(panel.dot_refresh.isEnabled())
        self.assertTrue(panel.dot_older.isEnabled())
        self.assert_no_adapter_actions()
        with patch.object(panel, "dot_consent", return_value=False) as consent:
            panel.read_dot(False)
            panel.input.setPlainText("manual dot draft")
            panel.send()
            self.assertEqual(2, consent.call_count)
        self.assert_no_adapter_actions()
        self.assertEqual("manual dot draft", panel.input.toPlainText())

    def test_dot_reads_only_after_explicit_refresh_or_older_click(self):
        panel = self.connect_fixture("dot")
        self.window.show_sessions("dot")
        self.settle()
        with patch.object(panel, "dot_consent", return_value=True) as consent:
            QTest.mouseClick(panel.dot_refresh, Qt.LeftButton)
            self.window.poll_events()
            self.settle()
            self.assertEqual([("read", False)], self.adapters["dot"].calls)
            QTest.mouseClick(panel.dot_older, Qt.LeftButton)
            self.window.poll_events()
            self.settle()
            self.assertEqual([("read", False), ("read", True)], self.adapters["dot"].calls)
            self.assertEqual([(("messages",), {}), (("messages",), {})],
                             [(call.args, call.kwargs) for call in consent.call_args_list])

    def test_dot_send_does_not_automatically_read_stream_or_relay(self):
        panel = self.connect_fixture("dot")
        self.window.focus_agent("dot")
        self.settle()
        panel.input.setPlainText("explicit offline dot message")
        with patch.object(panel, "dot_consent", return_value=True) as consent:
            QTest.mouseClick(panel.send_button, Qt.LeftButton)
            self.window.poll_events()
            self.settle()
            consent.assert_called_once_with("send")
        self.assertEqual([("send", "explicit offline dot message", None, None, None)], self.adapters["dot"].calls)
        self.assertEqual([], self.adapters["claude"].calls)
        self.assertEqual([], self.adapters["codex"].calls)
        self.assertEqual("", panel.input.toPlainText())

    def test_pending_approval_stays_fixed_visible_when_new_events_arrive(self):
        panel = self.connect_fixture("codex")
        self.window.focus_agent("codex")
        self.settle()
        self.core.ingest_event("codex", "approval_request", request_id="offline-approval",
                               command="fixture command", content="Human review required")
        self.window.poll_events()
        for number in range(20):
            self.core.ingest_event("codex", "command_output", content="new output " + str(number))
        self.window.poll_events()
        self.settle()
        self.assertTrue(panel.pending_review.isVisible())
        self.assertFalse(panel.scroll.isAncestorOf(panel.pending_review))
        self.assertIn("offline-approval", panel.pending_approval_events)
        self.assert_no_adapter_actions()

    def test_hidden_role_pending_badge_does_not_steal_focus(self):
        panel = self.connect_fixture("codex")
        self.window.resize(760, 720)
        self.choose_enum(self.window.layout_mode, "Auto")
        self.window.update_workspace_layout()
        self.settle()
        self.assertTrue(self.window.panels["claude"].isVisible())
        self.assertFalse(panel.isVisible())
        event = self.core.ingest_event("codex", "approval_request", request_id="hidden-request", command="fixture")
        self.window.poll_events()
        self.settle()
        self.assertIn("待核准", self.window.role_tabs.tabText(2))
        self.assertTrue(self.window.panels["claude"].isVisible())
        self.assert_no_adapter_actions()
        QTest.mouseClick(self.window.role_tabs, Qt.LeftButton,
                         pos=self.window.role_tabs.tabRect(2).center())
        self.settle()
        self.assertEqual(2, self.window.role_tabs.currentIndex())
        self.assertTrue(panel.pending_review.isVisible())
        self.assert_no_adapter_actions()
        self.window.approve(event, False)
        self.window.poll_events()
        self.assertNotIn("待核准", self.window.role_tabs.tabText(2))

    def test_pending_approval_task_roundtrip_remains_actionable(self):
        panel = self.connect_fixture("codex")
        self.core.ingest_event("codex", "approval_request", request_id="keep-pending", command="fixture")
        self.window.poll_events()
        self.settle()
        self.choose_task(self.task_b)
        self.assertNotIn("keep-pending", panel.pending_approval_events)
        self.choose_task(self.task_a)
        self.assertIn("keep-pending", panel.pending_approval_events)
        card = panel.approvals["keep-pending"]
        self.assertFalse(card.historical)
        self.assertTrue(all(button.isEnabled() for button in card.approval_actions))
        self.assert_no_adapter_actions()

    def test_off_task_approval_cancellation_cannot_revive_cached_action(self):
        panel = self.connect_fixture("codex")
        request_id = "expired-task-a-request"
        session_id = self.core.current_task["codex_session"]
        self.core.ingest_event("codex", "approval_request", request_id=request_id, command="fixture")
        self.window.poll_events()
        self.choose_task(self.task_b)
        terminal = self.core.ingest_event("codex", "approval_cancelled", request_id=request_id,
                                        task_id=self.task_a["id"], session_id=session_id)
        self.window.poll_events()
        self.choose_task(self.task_a)
        self.assertNotIn(request_id, panel.pending_approval_events)
        self.assertTrue(panel.pending_review.isHidden())
        self.assertNotIn("待核准", self.window.role_tabs.tabText(2))
        card = panel.approvals.get(request_id)
        if card is not None:
            self.assertTrue(all(not button.isEnabled() for button in card.approval_actions))
        self.assertIn(terminal["id"], [event["id"] for event in self.core.events(agent="codex")])
        panel.review_pending_approval()
        self.assert_no_adapter_actions()

    def test_undrained_off_task_terminal_is_reconciled_from_persisted_approval_ledger(self):
        panel = self.connect_fixture("codex")
        request_id = "persisted-undrained-cancellation"
        session_a = self.core.current_task["codex_session"]
        self.core.ingest_event("codex", "approval_request", request_id=request_id, command="fixture")
        self.window.poll_events()
        self.choose_task(self.task_b)
        self.core.ingest_event("codex", "approval_cancelled", request_id=request_id,
                               task_id=self.task_a["id"], session_id=session_a)
        # Deliberately return before the queued terminal event is polled.
        self.choose_task(self.task_a)
        self.assertNotIn(request_id, panel.pending_approval_events)
        self.assertTrue(panel.pending_review.isHidden())
        card = panel.approvals.get(request_id)
        if card is not None:
            self.assertTrue(all(not button.isEnabled() for button in card.approval_actions))
        self.window.poll_events()
        self.settle()
        self.assertNotIn(request_id, panel.pending_approval_events)
        self.assertTrue(panel.pending_review.isHidden())
        panel.review_pending_approval()
        self.assert_no_adapter_actions()

    def test_off_task_approved_or_denied_response_cannot_revive_cached_action(self):
        panel = self.connect_fixture("codex")
        for approved in (True, False):
            with self.subTest(approved=approved):
                request_id = "responded-task-a-" + str(approved)
                session_id = self.core.current_task["codex_session"]
                self.core.ingest_event("codex", "approval_request", request_id=request_id, command="fixture")
                self.window.poll_events()
                self.choose_task(self.task_b)
                self.core.ingest_event("codex", "approval_response", request_id=request_id, approved=approved,
                                       task_id=self.task_a["id"], session_id=session_id)
                self.window.poll_events()
                self.choose_task(self.task_a)
                self.assertNotIn(request_id, panel.pending_approval_events)
                self.assertTrue(panel.pending_review.isHidden())
                card = panel.approvals.get(request_id)
                if card is not None:
                    self.assertTrue(all(not button.isEnabled() for button in card.approval_actions))
                panel.review_pending_approval()
                self.assert_no_adapter_actions()

    def test_off_task_terminal_event_does_not_cancel_same_id_in_active_other_task(self):
        panel = self.connect_fixture("codex")
        request_id = "same-id-independent-tasks"
        session_a = self.core.current_task["codex_session"]
        self.core.ingest_event("codex", "approval_request", request_id=request_id, command="task A fixture")
        self.window.poll_events()
        self.choose_task(self.task_b)
        session_b = self.core.current_task["codex_session"]
        self.core.ingest_event("codex", "approval_request", request_id=request_id,
                               command="task B fixture", session_id=session_b)
        self.window.poll_events()
        self.assertIn(request_id, panel.pending_approval_events)
        self.core.ingest_event("codex", "approval_cancelled", request_id=request_id,
                               task_id=self.task_a["id"], session_id=session_a)
        self.window.poll_events()
        self.assertIn(request_id, panel.pending_approval_events)
        self.assertTrue(all(button.isEnabled() for button in panel.approvals[request_id].approval_actions))
        self.choose_task(self.task_a)
        self.assertNotIn(request_id, panel.pending_approval_events)
        self.choose_task(self.task_b)
        self.assertIn(request_id, panel.pending_approval_events)
        self.assertFalse(panel.approvals[request_id].historical)
        self.assert_no_adapter_actions()

    def test_restored_pending_reminder_approves_exact_backend_request_id(self):
        panel = self.connect_fixture("codex")
        self.window.focus_agent("codex")
        self.settle()
        request_id = "native-restored-request-id"
        self.core.ingest_event("codex", "approval_request", request_id=request_id, command="fixture")
        self.window.poll_events()
        self.choose_task(self.task_b)
        self.choose_task(self.task_a)
        self.assertIn(request_id, panel.pending_approval_events)
        self.assert_no_adapter_actions()
        with patch("acw.ui.QMessageBox.exec", return_value=QMessageBox.Yes):
            QTest.mouseClick(panel.pending_review, Qt.LeftButton)
        self.window.poll_events()
        self.settle()
        self.assertEqual([("approve", request_id, True)], self.adapters["codex"].calls)
        self.assertNotIn(request_id, panel.pending_approval_events)
        self.assertTrue(panel.pending_review.isHidden())

    def test_approval_deny_dispatches_exact_request_and_resolves_reminder(self):
        panel = self.connect_fixture("codex")
        event = self.core.ingest_event("codex", "approval_request", request_id="deny-this-only", command="fixture")
        self.window.poll_events()
        self.window.approve(event, False)
        self.window.poll_events()
        self.assertEqual([("approve", "deny-this-only", False)], self.adapters["codex"].calls)
        self.assertFalse(panel.pending_review.isVisible())
        self.assertTrue(panel.approvals["deny-this-only"].approval_resolved)
        self.assertTrue(all(not b.isEnabled() for b in panel.approvals["deny-this-only"].approval_actions))

    def test_historical_approval_is_read_only(self):
        panel = self.connect_fixture("codex")
        panel.add_event({"type": "approval_request", "agent": "codex", "request_id": "history-only"}, historical=True)
        card = panel.approvals["history-only"]
        self.assertTrue(all(not b.isEnabled() for b in card.approval_actions))
        self.assertFalse(panel.pending_review.isVisible())
        self.assert_no_adapter_actions()

    def test_monitor_disables_send_and_approval_but_keeps_saved_history(self):
        panel = self.connect_fixture("codex")
        self.add_saved_response("codex", mid="saved-monitor-response")
        panel.add_event({"type": "approval_request", "agent": "codex", "request_id": "monitor-request"})
        self.choose_enum(self.window.mode, "Monitor")
        self.assertFalse(panel.send_button.isEnabled())
        self.assertTrue(panel.input.isReadOnly())
        self.assertFalse(panel.pending_review.isEnabled())
        self.assertIn("saved-monitor-response", panel.cards)
        self.assertTrue(all(not b.isEnabled() for b in panel.approvals["monitor-request"].approval_actions))
        self.choose_enum(self.window.mode, "Workspace")
        self.assertTrue(panel.send_button.isEnabled())
        self.assert_no_adapter_actions()

    def test_manual_handoff_sends_original_content_only_after_explicit_forward(self):
        self.connect_fixture("codex")
        original = "Verbatim reviewer result\n中文 exact content"
        message = self.add_saved_response("claude", original)
        self.choose_enum(self.window.handoff_mode, "manual")
        self.assert_no_adapter_actions()
        self.window.forward(message, "codex")
        calls = self.adapters["codex"].calls
        self.assertEqual(1, len(calls))
        self.assertEqual("send", calls[0][0])
        self.assertIn("Original content:\n" + original, calls[0][1])
        handoffs = self.core.store.query("SELECT * FROM handoffs")
        self.assertEqual("sent", handoffs[0]["status"])
        self.assertEqual(original, handoffs[0]["source_message"])

    def test_assisted_handoff_cancel_does_not_send(self):
        self.connect_fixture("codex")
        message = self.add_saved_response()
        with patch("acw.ui.HandoffDialog.exec", return_value=QDialog.Rejected):
            self.window.forward(message, "codex")
        self.assert_no_adapter_actions()
        handoffs = self.core.store.query("SELECT * FROM handoffs")
        self.assertEqual("prepared", handoffs[0]["status"])

    def test_flow_menu_does_not_trigger_agents_or_enable_automatic_step(self):
        menu = QMenu()
        self.window.populate_flow_menu(menu)
        self.assertFalse(menu.actions()[0].isEnabled())
        self.assertFalse(menu.actions()[1].isEnabled())
        self.assertIn("自動", menu.actions()[-1].text())
        self.assertIn("關閉", menu.actions()[-1].text())
        self.assert_no_adapter_actions()

    def test_details_tabs_show_real_structured_event_records(self):
        fixtures = {
            "Tools": ("tool_result", {"tool": "fixture_tool", "content": "fixed result"}),
            "Commands": ("command", {"command": "fixture echo", "stdout": "fixed stdout", "stderr": ""}),
            "Changes": ("diff", {"name": "fixture.diff", "content": "-old\n+new"}),
            "Tests": ("test", {"name": "fixture test", "status": "passed", "content": "1 offline check"}),
        }
        events = {group: self.core.ingest_event("codex", kind, **payload)
                  for group, (kind, payload) in fixtures.items()}
        QTest.mouseClick(self.window.details_toggle, Qt.LeftButton)
        self.settle()
        self.assertTrue(self.window.details_panel.isVisible() or
                        (self.window.details_dialog is not None and self.window.details_dialog.isVisible()))
        self.assertEqual(["工具", "命令", "變更", "測試", "時間線", "交接"],
                         [self.window.details_tabs.tabText(i) for i in range(self.window.details_tabs.count())])
        for group, event in events.items():
            tree = self.window.detail_trees[group]
            self.assertEqual(1, tree.topLevelItemCount(), group)
            item = tree.topLevelItem(0)
            record = item.data(0, Qt.UserRole)
            self.assertEqual(event["id"], record["id"])
            self.assertEqual(event["type"], record["type"])
            timeline = self.window.detail_trees["Timeline"]
            timeline_ids = [timeline.topLevelItem(i).data(0, Qt.UserRole)["id"]
                            for i in range(timeline.topLevelItemCount())]
            self.assertIn(event["id"], timeline_ids)
            with patch.object(self.window, "show_detail") as show:
                tree.itemDoubleClicked.emit(item, 0)
                show.assert_called_once_with("Recorded detail", record)
        self.assert_no_adapter_actions()

    def test_details_empty_state_and_unknown_status_are_honest(self):
        self.window.toggle_details()
        tree = self.window.detail_trees["Tools"]
        self.assertEqual(1, tree.topLevelItemCount())
        placeholder = tree.topLevelItem(0)
        self.assertIsNone(placeholder.data(0, Qt.UserRole))
        self.assertIn("尚無", placeholder.text(1))
        self.core.ingest_event("claude", "command", command="fixture status unspecified")
        self.window.refresh_work_details()
        item = self.window.detail_trees["Commands"].topLevelItem(0)
        self.assertIn("狀態待確認", item.text(1))
        self.assert_no_adapter_actions()

    def test_details_toggle_keeps_drafts_and_handoff_mode_reachable(self):
        panel = self.window.panels["claude"]
        panel.input.setPlainText("draft with details toggled")
        for _ in range(2):
            QTest.mouseClick(self.window.details_toggle, Qt.LeftButton)
            self.settle()
        self.assertEqual("draft with details toggled", panel.input.toPlainText())
        self.window.toggle_details()
        self.window.details_tabs.setCurrentIndex(5)
        self.settle()
        self.assertTrue(self.window.handoff_mode.isVisible())
        self.assertTrue(self.window.flow_button.isVisible())
        self.assertEqual("assisted", self.window.handoff_mode.currentData())
        self.assert_no_adapter_actions()

    def test_short_details_dialog_close_escape_and_reopen_keep_draft_and_tabs(self):
        self.window.resize(800, 600)
        self.window.update_workspace_layout()
        self.settle()
        panel = self.window.panels["claude"]
        panel.input.setPlainText("draft across detail close/reopen")
        tabs = self.window.details_tabs
        self.window.toggle_details()
        self.settle()
        dialog = self.window.details_dialog
        self.assertIsNotNone(dialog)
        self.assertTrue(dialog.isVisible())
        self.assertEqual(Qt.NonModal, dialog.windowModality())
        self.assertTrue(dialog.isAncestorOf(tabs))
        self.assertFalse(self.window.details_panel.isVisible())
        tabs.setCurrentIndex(3)
        dialog.reject()
        self.settle()
        self.assertFalse(dialog.isVisible())
        self.assertTrue(self.window.details_panel.isAncestorOf(tabs))
        self.assertFalse(self.window.details_toggle.isChecked())
        self.window.toggle_details()
        self.settle()
        self.assertIs(tabs, self.window.details_tabs)
        self.assertEqual(3, tabs.currentIndex())
        self.assertTrue(dialog.isVisible())
        QTest.keyClick(dialog, Qt.Key_Escape)
        self.settle()
        self.assertFalse(dialog.isVisible())
        self.assertEqual("draft across detail close/reopen", panel.input.toPlainText())
        self.assert_no_adapter_actions()

    def test_open_details_moves_from_tall_drawer_to_short_dialog_and_back(self):
        self.window.resize(1200, 850)
        self.window.update_workspace_layout()
        self.settle()
        panel = self.window.panels["claude"]
        panel.input.setPlainText("draft across height change")
        tabs = self.window.details_tabs
        self.window.toggle_details()
        self.settle()
        self.assertTrue(self.window.details_panel.isVisible())
        tabs.setCurrentIndex(5)
        self.window.resize(800, 600)
        self.settle()
        self.assertFalse(self.window.details_panel.isVisible())
        self.assertTrue(self.window.details_dialog.isVisible())
        self.assertEqual(5, tabs.currentIndex())
        self.assertGreaterEqual(panel.scroll.height(), 100)
        self.window.details_dialog.reject()
        self.settle()
        self.window.resize(1200, 850)
        self.settle()
        self.window.toggle_details()
        self.settle()
        self.assertTrue(self.window.details_panel.isVisible())
        self.assertTrue(self.window.details_panel.isAncestorOf(tabs))
        self.assertFalse(self.window.details_dialog.isVisible())
        self.assertEqual(5, tabs.currentIndex())
        self.assertEqual("draft across height change", panel.input.toPlainText())
        self.assert_no_adapter_actions()

    def test_short_details_dialog_refreshes_live_events_and_context_changes(self):
        self.window.resize(800, 600)
        self.window.update_workspace_layout()
        self.settle()
        self.window.toggle_details()
        self.settle()
        self.assertTrue(self.window.details_dialog.isVisible())
        event = self.core.ingest_event("claude", "command", command="new dialog command")
        self.window.poll_events()
        self.settle()
        tree = self.window.detail_trees["Commands"]
        self.assertEqual(event["id"], tree.topLevelItem(0).data(0, Qt.UserRole)["id"])
        self.choose_task(self.task_b)
        self.assertIsNone(tree.topLevelItem(0).data(0, Qt.UserRole))
        self.choose_task(self.task_a)
        self.assertEqual(event["id"], tree.topLevelItem(0).data(0, Qt.UserRole)["id"])
        self.assertTrue(self.window.details_dialog.isVisible())
        self.assert_no_adapter_actions()

    def test_details_handoff_record_is_exact_and_does_not_send(self):
        source = self.add_saved_response(text="exact saved handoff source")
        prepared = self.core.prepare_handoff(source["id"], "codex", annotation="offline annotation")
        self.window.toggle_details()
        item = self.window.detail_trees["Handoffs"].topLevelItem(0)
        record = item.data(0, Qt.UserRole)
        self.assertEqual(prepared["id"], record["id"])
        self.assertEqual("prepared", record["status"])
        self.assertEqual("exact saved handoff source", record["source_message"])
        self.assertEqual("offline annotation", record["annotation"])
        self.assert_no_adapter_actions()

    def test_details_tab_and_record_selection_survive_task_roundtrip(self):
        first = self.core.ingest_event("claude", "tool_result", tool="first fixture", content="one")
        second = self.core.ingest_event("claude", "tool_result", tool="second fixture", content="two")
        self.window.toggle_details()
        tree = self.window.detail_trees["Tools"]
        chosen = next(tree.topLevelItem(i) for i in range(tree.topLevelItemCount())
                      if tree.topLevelItem(i).data(0, Qt.UserRole)["id"] == second["id"])
        tree.setCurrentItem(chosen)
        self.window.details_tabs.setCurrentIndex(3)
        self.window.role_tabs.setCurrentIndex(2)
        self.settle()
        self.choose_task(self.task_b)
        self.window.details_tabs.setCurrentIndex(0)
        self.window.role_tabs.setCurrentIndex(1)
        self.choose_task(self.task_a)
        self.assertEqual(3, self.window.details_tabs.currentIndex())
        self.assertEqual(second["id"], tree.currentItem().data(0, Qt.UserRole)["id"])
        self.assertEqual(1, self.window.role_tabs.currentIndex())
        self.assertEqual(1, self.window.session_tabs.currentIndex())
        self.assertEqual("dot", self.core.get_setting("ui.active_agent"))
        self.assert_no_adapter_actions()

    def test_workspace_and_role_overflow_actions_remain_reachable(self):
        tool = self.window.findChild(QToolButton, "workspace_actions")
        actions = [action.text() for action in tool.menu().actions()]
        for name in ("任務筆記", "比較回覆", "差異／測試／附件", "匯出",
                     "設定", "診斷", "停止全部 Agent"):
            self.assertTrue(any(name in action for action in actions), name)
        for agent, panel in self.window.panels.items():
            names = [action.text() for action in panel.more_button.menu().actions()]
            conversation_actions=("工作交接關聯", "載入更早訊息") if agent=="dot" else ("對話", "本機歷史")
            for name in (*conversation_actions, "能力詳情", "原始事件", "日誌", "專案檔案"):
                self.assertTrue(any(name in action for action in names), (agent, name))
        self.assert_no_adapter_actions()

    def test_timeline_and_history_navigation_remain_reachable(self):
        self.add_saved_response()
        self.choose_enum(self.window.mode, "Timeline")
        self.assertEqual(1, self.window.stack.currentIndex())
        self.choose_enum(self.window.mode, "History")
        self.assertEqual(2, self.window.stack.currentIndex())
        self.choose_enum(self.window.mode, "Workspace")
        self.assertEqual(0, self.window.stack.currentIndex())
        self.assert_no_adapter_actions()

    def test_message_card_plain_text_copy_and_raw_action_preserve_content(self):
        text = "<b>literal, not HTML</b>\n中文 untouched"
        message = self.add_saved_response(text=text)
        card = self.window.panels["claude"].cards[message["id"]]
        self.assertEqual(text, card.body.toPlainText())
        card.copy(False)
        self.assertEqual(text, self.app.clipboard().text())
        forward_labels = [action.text() for action in card.forward_button.menu().actions()]
        self.assertEqual(["G8毛", "Codex", "Hermes"], forward_labels)
        self.assert_no_adapter_actions()


if __name__ == "__main__":
    unittest.main(verbosity=2)
