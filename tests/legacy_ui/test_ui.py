"""Isolated Qt interaction tests. FakeCore is explicitly a test double.

These tests validate workspace widgets and boundaries; they are not backend or
Final acceptance evidence. No official agent or production repository is used.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt, QPoint, QRect, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QMenu

from acw.ui import MainWindow, HandoffDialog, NativeSessionDialog, NativeHistoryDialog, ArtifactPanel, EventCard, MessageCard


class FakeCore:
    """Deliberately labeled synthetic fixture; no backend calls."""
    def __init__(self, root):
        self.data_dir = Path(root)
        self.settings = {}
        self.calls = []
        self.pending = []
        self.project = {"id": "project-test", "name": "ISOLATED UI TEST", "repo_path": str(root)}
        self.task = {"id": "task-test", "title": "Synthetic UI test", "project_id": "project-test", "status": "NEW", "branch": "test/ui"}
        self.records = []
        self.event_records = []
        self.imported_sessions = []
        self.artifact_records = []
        self.native_history_available = True
        self.states = {agent: "Disconnected" for agent in ("claude", "dot", "codex")}
        self.caps = {agent: {} for agent in self.states}
        self.caps["dot"] = {"detail": "BLOCKED: test fixture has no dot bridge"}

    @property
    def current_project(self): return self.project
    @property
    def current_task(self): return self.task
    def get_setting(self, key, default=None): return self.settings.get(key, default)
    def set_setting(self, key, value): self.settings[key] = value
    def list_projects(self): return [self.project]
    def list_tasks(self, **filters):
        self.last_filters = filters
        return [self.task]
    def messages(self, task_id=None, agent=None): return [m for m in self.records if not agent or m["agent"] == agent]
    def events(self, task_id=None, agent=None, limit=1000): return [e for e in self.event_records if not agent or e.get("agent") == agent][-limit:]
    def sessions(self, agent=None): return [row for row in self.imported_sessions if not agent or row["agent"] == agent]
    def discover_sessions(self, agent):
        self.calls.append(("discover_sessions", agent))
        return [{"id": "native-test-session", "title": "Explicit discovery fixture", "cwd": str(self.data_dir), "source": "LABELED TEST DOUBLE"}]
    def native_history_capability(self, agent):
        return {"supported": self.native_history_available, "detail": "LABELED TEST DOUBLE native history" if self.native_history_available else "Fixture native helper unavailable"}
    def native_history(self, agent, session_id):
        self.calls.append(("native_history", agent, session_id))
        return [{"role": "user", "content": "Fixture original prompt"}, {"role": "assistant", "content": "Fixture original response"}]
    def import_session(self, agent, record):
        self.calls.append(("import_session", agent, record))
        value = dict(record, agent=agent)
        self.imported_sessions.append(value)
        return value
    def save_patch(self, diff_text, target_path):
        self.calls.append(("save_patch", diff_text, target_path))
        return Path(target_path)
    def artifacts(self, task_id=None): return list(self.artifact_records)
    def import_artifact(self, path, kind=None, name=None, agent="", task_id=None, *, user_selected=False):
        self.calls.append(("import_artifact", path, task_id, user_selected))
        record = {"id": "artifact-test", "type": "screenshot" if Path(path).suffix == ".png" else "markdown", "name": Path(path).name, "path": str(Path(self.data_dir) / "managed" / Path(path).name), "timestamp": "2026-10-05"}
        self.artifact_records.append(record)
        return record
    def artifact_path(self, artifact_id):
        self.calls.append(("artifact_path", artifact_id))
        return Path(self.data_dir) / "managed" / "registered.md"
    def export_artifact(self, artifact_id, target_path, *, screenshot_reviewed=False):
        self.calls.append(("export_artifact", artifact_id, target_path, screenshot_reviewed))
        return Path(target_path)
    def export_task(self, task_id, format_name, target_path, *, include_screenshots=False):
        self.calls.append(("export_task", task_id, format_name, target_path, include_screenshots))
        return Path(target_path)
    def capabilities(self, agent): return self.caps[agent]
    def list_efforts(self, agent, model=None):
        for record in self.caps[agent].get("models", []):
            if isinstance(record, dict) and record.get("id") == model:
                return record.get("supportedReasoningEfforts", [])
        return []
    def poll_legacy(self, root=None): return []
    def git_snapshot(self): return {"is_git": False}
    def diagnostics(self, agent=None):
        if agent:
            return {"agent": agent, "state": self.states[agent], "backend": "LABELED TEST DOUBLE", "executable": "", "session": ""}
        return {"test_double": True}
    def drain_events(self):
        events, self.pending = self.pending, []
        return events
    def connect(self, agent):
        self.calls.append(("connect", agent))
        self.states[agent] = "Connected"
    def disconnect(self, agent):
        self.calls.append(("disconnect", agent))
        self.states[agent] = "Disconnected"
    def send_message(self, agent, content, **kwargs):
        self.calls.append(("send", agent, content, kwargs))
        self.pending.append({"id": "message-1", "message_id": "message-1", "type": "message_end", "agent": agent, "role": "assistant", "full_content": "Synthetic test response", "task_id": "task-test"})
        self.pending.append({"type": "state", "agent": agent, "state": "Connected"})
    def stop_task(self, confirmed=False): self.calls.append(("stop_task", confirmed))
    def stop(self, agent): self.calls.append(("stop", agent))
    def prepare_handoff(self, message_id, target_agent, annotation=""):
        message = next(m for m in self.records if m["id"] == message_id)
        self.prepared = {"id": "handoff-test", "source_message": message["content"], "handoff_message": f"Source: {message['agent']}\nTarget: {target_agent}\n\n{message['content']}\n\nNote: {annotation}", "annotation": annotation, "target_agent": target_agent}
        return self.prepared
    def update_handoff_annotation(self, handoff_id, annotation):
        self.prepared["annotation"] = annotation
        self.prepared["handoff_message"] = self.prepared["source_message"] + "\nNote: " + annotation
        return self.prepared
    def send_handoff(self, preview): self.calls.append(("handoff", preview))
    def update_task(self, task_id, **fields): self.task.update(fields)
    def search(self, query, **filters):
        self.calls.append(("search", query, filters))
        return self.records


class WorkspaceUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="acw-ui-isolated-")
        self.core = FakeCore(self.temp.name)
        self.window = MainWindow(self.core)
        self.window.show()
        QTest.qWait(20)

    def tearDown(self):
        deadline = time.monotonic() + 3
        while self.window.workers and time.monotonic() < deadline:
            QTest.qWait(10)
        for panel in self.window.panels.values():
            panel.set_state("Disconnected")
        self.window.close()
        self.window.deleteLater()
        QTest.qWait(10)
        self.temp.cleanup()

    def ready(self, agent="codex"):
        self.core.states[agent] = "Connected"
        self.core.caps[agent] = {"supports_model_selection": True, "supports_effort": True, "supports_sessions": True,
                                 "supports_cancel": True, "models": [{"id": "fixture-model", "displayName": "Fixture model", "supportedReasoningEfforts": [{"reasoningEffort": "fixture-effort"}]}]}
        self.window.refresh_agent(agent)
        return self.window.panels[agent]

    def assert_message_rendered(self, panel, message_id):
        """Require an exposed card inside the viewport, not just stored text."""
        QTest.qWait(20)
        card = panel.cards[message_id]
        panel.scroll.ensureWidgetVisible(card)
        QTest.qWait(20)
        self.assertTrue(card.isVisible())
        self.assertTrue(card.body.isVisible())
        self.assertGreater(card.width(), 100)
        self.assertGreater(card.body.height(), 0)
        viewport = panel.scroll.viewport()
        for widget in (card, card.body):
            bounds = QRect(widget.mapTo(viewport, QPoint(0, 0)), widget.size())
            self.assertTrue(viewport.rect().intersects(bounds), "Rendered message must intersect its visible viewport")

    def test_startup_never_connects_and_dot_is_honestly_blocked(self):
        self.assertEqual(self.core.calls, [])
        self.assertEqual(set(self.window.panels), {"claude", "dot", "codex"})
        dot = self.window.panels["dot"]
        self.assertFalse(dot.connect_button.isEnabled())
        self.assertFalse(dot.model.isEnabled())
        self.assertEqual(dot.model.currentText(), "Managed by ChatGPT / dot")
        self.assertIn("BLOCKED", dot.notice.text())
        self.assertFalse(dot.send_button.isEnabled())

    def test_only_discovered_model_and_effort_choices(self):
        panel = self.ready()
        self.assertEqual(panel.model.count(), 1)
        self.assertEqual(panel.model.currentData(), "fixture-model")
        self.assertEqual(panel.effort.count(), 1)
        self.assertEqual(panel.effort.currentData(), "fixture-effort")
        panel.update_capabilities({"supports_model_selection": True, "models": []})
        self.assertEqual(panel.model.currentText(), "Default backend model")
        self.assertFalse(panel.model.isEnabled())
        self.assertFalse(panel.effort.isEnabled())

    def test_real_qt_click_sends_selected_values_through_core(self):
        panel = self.ready()
        QTest.mouseClick(panel.input.viewport(), Qt.LeftButton)
        QTest.keyClicks(panel.input, "Isolated harmless UI test")
        QTest.mouseClick(panel.send_button, Qt.LeftButton)
        for _ in range(50):
            QTest.qWait(10)
            if self.core.calls:
                break
        sent = next(call for call in self.core.calls if call[0] == "send")
        self.assertEqual(sent[2], "Isolated harmless UI test")
        self.assertEqual(sent[3]["model"], "fixture-model")
        self.assertEqual(sent[3]["effort"], "fixture-effort")
        self.window.poll_events()
        self.assertEqual(panel.cards["message-1"].body.toPlainText(), "Synthetic test response")
        self.assert_message_rendered(panel, "message-1")

    def test_streaming_replaces_cumulative_redacted_content(self):
        panel = self.window.panels["codex"]
        for content in ("Text ", "Text [REDACTED]", "Text [REDACTED] final"):
            self.core.pending.append({"id": "event", "message_id": "stream-1", "type": "message_delta", "agent": "codex", "task_id": "task-test", "full_content": content})
            self.window.poll_events()
        self.assertEqual(len(panel.cards), 1)
        self.assertEqual(panel.cards["stream-1"].body.toPlainText(), "Text [REDACTED] final")
        self.assert_message_rendered(panel, "stream-1")
        self.core.pending.append({"id": "raw-fragment", "message_id": "stream-1", "type": "message_delta", "agent": "codex", "content": "unsafe raw fragment"})
        self.window.poll_events()
        self.assertNotIn("unsafe", panel.cards["stream-1"].body.toPlainText())

    def test_pending_approval_remains_visible_after_event_burst_and_requires_user_action(self):
        panel = self.ready()
        self.core.caps['codex']['supports_approval'] = True
        panel.update_capabilities(self.core.caps['codex'])
        event = {"id": "approval-fixture", "agent": "codex", "type": "approval", "request_id": "fixture-request", "details": {"method": "item/fileChange/requestApproval"}}
        panel.add_event(event)
        for index in range(30):
            panel.add_event({"agent": "codex", "type": "event", "summary": "Synthetic newer activity " + str(index)})
        QTest.qWait(30)
        self.assertTrue(panel.pending_review.isVisible())
        self.assertFalse(any(call[0] == "approve" for call in self.core.calls))
        self.window.mode.setCurrentText('Monitor')
        self.assertFalse(panel.pending_review.isEnabled())
        self.assertFalse(any(control.isEnabled() for control in panel.approvals['fixture-request'].approval_actions))
        self.window.mode.setCurrentText('Workspace')
        self.assertTrue(panel.pending_review.isEnabled())
        with patch.object(self.window, "approve") as review:
            QTest.mouseClick(panel.pending_review, Qt.LeftButton)
            review.assert_called_once_with(event, True)
        panel.resolve_pending_approval("fixture-request")
        self.assertFalse(panel.pending_review.isVisible())
        self.assertFalse(any(control.isEnabled() for control in panel.approvals["fixture-request"].approval_actions))
        self.window.mode.setCurrentText('Monitor');self.window.mode.setCurrentText('Workspace')
        self.assertFalse(any(control.isEnabled() for control in panel.approvals['fixture-request'].approval_actions))

    def test_unsupported_approval_is_readonly_and_never_dispatches(self):
        panel = self.ready()
        event = {'id':'unsupported-request','agent':'codex','type':'approval','request_id':'unsupported-request'}
        panel.add_event(event)
        self.assertFalse(panel.pending_review.isEnabled())
        self.assertFalse(any(control.isEnabled() for control in panel.approvals['unsupported-request'].approval_actions))
        with patch.object(self.window,'approve') as action:
            QTest.mouseClick(panel.pending_review,Qt.LeftButton)
            for control in panel.approvals['unsupported-request'].approval_actions:QTest.mouseClick(control,Qt.LeftButton)
            action.assert_not_called()

    def test_model_change_gates_attachments_and_preserves_queued_files_until_explicit_clear(self):
        panel=self.ready()
        self.core.caps['codex'].update(supports_files=True,models=[{'id':'image-model','inputModalities':['text','image']},{'id':'text-model','inputModalities':['text']}])
        self.core.attachment_capability=lambda agent,model=None:{'supported':model=='image-model'}
        panel.update_capabilities(self.core.caps['codex']);panel.model.setCurrentIndex(panel.model.findData('image-model'))
        self.assertTrue(panel.attach_button.isVisible());self.assertTrue(panel.input.acceptDrops());panel.add_attachments(['isolated-image.png']);self.assertEqual(panel.attachments,['isolated-image.png'])
        panel.model.setCurrentIndex(panel.model.findData('text-model'));self.assertFalse(panel.attach_button.isVisible());self.assertFalse(panel.input.acceptDrops());self.assertFalse(panel.send_button.isEnabled());self.assertEqual(panel.attachments,['isolated-image.png'])
        QTest.mouseClick(panel.clear_attach_button,Qt.LeftButton);self.assertEqual(panel.attachments,[]);self.assertTrue(panel.send_button.isEnabled())

    def test_commands_are_collapsible_activity_not_chat_messages(self):
        self.core.pending.append({"id": "cmd", "agent": "codex", "type": "command", "command": "echo harmless", "exit_code": 0, "output": "harmless"})
        self.window.poll_events()
        cards = self.window.panels["codex"].findChildren(EventCard)
        self.assertEqual(len(cards), 1)
        self.assertEqual(len(self.window.panels["codex"].cards), 0)
        # Newly inserted widgets need a show/layout event cycle before pointer
        # input. The original visible run clicked before the card was exposed;
        # its captured screenshot had no card visible at all.
        QTest.qWait(20)
        self.window.panels["codex"].scroll.ensureWidgetVisible(cards[0].toggle)
        self.assertTrue(cards[0].toggle.isVisible())
        self.assertFalse(cards[0].body.isVisible())
        QTest.mouseClick(cards[0].toggle, Qt.LeftButton)
        QTest.qWait(10)
        self.assertTrue(cards[0].toggle.isChecked())
        self.assertTrue(cards[0].body.isVisible())
        self.assertIn("Combined output", cards[0].body.toPlainText())
        QTest.mouseClick(cards[0].toggle, Qt.LeftButton)
        self.assertFalse(cards[0].toggle.isChecked())
        self.assertFalse(cards[0].body.isVisible())

    def test_monitor_mode_is_read_only_and_focus_can_return(self):
        panel = self.ready()
        self.window.mode.setCurrentText("Monitor")
        self.assertFalse(panel.send_button.isEnabled())
        self.assertTrue(panel.input.isReadOnly())
        self.assertFalse(panel.model.isEnabled())
        self.window.mode.setCurrentText("Workspace")
        self.assertTrue(panel.send_button.isEnabled())
        QTest.mouseDClick(panel.title, Qt.LeftButton)
        self.assertFalse(self.window.panels["claude"].isVisible())
        self.assertTrue(panel.isVisible())
        QTest.mouseClick(self.window.unfocus_button, Qt.LeftButton)
        self.assertTrue(all(p.isVisible() for p in self.window.panels.values()))

    def test_handoff_preserves_exact_source_and_separate_annotation(self):
        message = {"id": "a", "agent": "claude", "role": "assistant", "content": "A\n  preserved spacing\n", "timestamp": "2026-10-05T00:00:00Z"}
        self.core.records.append(message)
        dialog = HandoffDialog(self.window, message, "dot")
        self.assertFalse(dialog.send_button.isEnabled())
        dialog.annotation.setPlainText("Additional context")
        self.assertEqual(dialog.preview["source_message"], "A\n  preserved spacing\n")
        self.assertEqual(dialog.preview["annotation"], "Additional context")
        self.assertEqual(message["content"], "A\n  preserved spacing\n")
        self.assertEqual(self.core.calls, [])
        dialog.close()

    def test_context_change_requires_confirmation_for_unsent_input(self):
        panel = self.window.panels["claude"]
        panel.input.setPlainText("draft remains in this project")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.No):
            self.assertFalse(self.window.confirm_context_change())
        self.assertEqual(panel.input.toPlainText(), "draft remains in this project")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            self.assertTrue(self.window.confirm_context_change())
        self.assertEqual(panel.input.toPlainText(), "")

    def test_history_filters_and_search_are_forwarded_to_core(self):
        self.window.mode.setCurrentText("History")
        self.window.history_agent.setCurrentText("codex")
        self.window.history_status.setCurrentText("BLOCKED")
        self.window.history_project.setChecked(True)
        self.window.history_branch.setText("test/")
        self.window.history_date.setText("2026-10-05")
        self.window.history_errors.setChecked(True)
        self.window.search.setText("needle")
        QTest.keyClick(self.window.search, Qt.Key_Return)
        call = self.core.calls[-1]
        self.assertEqual(call[:2], ("search", "needle"))
        self.assertEqual(call[2], {"agent": "codex", "status": "BLOCKED", "project_id": "project-test", "branch": "test/", "date_from": "2026-10-05", "date_to": "2026-10-05", "error": True})

    def test_backend_operation_does_not_block_gui_event_loop(self):
        completed = []
        self.window.run(lambda: (time.sleep(.2), "complete"), lambda value: completed.append(value))
        start = time.monotonic()
        self.window.mode.setCurrentText("Timeline")
        QTest.qWait(20)
        self.assertEqual(self.window.stack.currentIndex(), 1)
        self.assertLess(time.monotonic() - start, .15)
        for _ in range(50):
            if completed:
                break
            QTest.qWait(10)
        self.assertTrue(completed)

    def test_geometry_is_saved_without_prompt_resend(self):
        self.window.resize(1280, 800)
        self.window.close()
        self.assertTrue(self.core.settings.get("ui.geometry"))
        self.assertEqual(self.core.calls, [])

    def test_manual_handoff_sends_only_after_explicit_forward_action(self):
        self.ready("codex")
        message = {"id": "manual-source", "agent": "claude", "role": "assistant", "content": "A\n unchanged", "status": "complete"}
        self.core.records.append(message)
        self.assertEqual(self.window.handoff_mode.currentText(), "Assisted")
        self.window.handoff_mode.setCurrentText("Manual")
        self.assertEqual(self.core.calls, [])
        self.window.forward(message, "codex")
        for _ in range(50):
            if self.core.calls:
                break
            QTest.qWait(10)
        sent = next(call for call in self.core.calls if call[0] == "handoff")
        self.assertEqual(sent[1]["source_message"], "A\n unchanged")
        self.assertEqual(sent[1]["target_agent"], "codex")

    def test_quick_flow_marks_dot_blocked_and_never_chains(self):
        self.core.records.append({"id": "flow-source", "agent": "claude", "role": "assistant", "content": "A", "status": "complete"})
        menu = QMenu(self.window)
        self.window.populate_flow_menu(menu)
        self.assertIn("Blocked", menu.actions()[0].text())
        self.assertFalse(menu.actions()[0].isEnabled())
        self.assertFalse(menu.actions()[1].isEnabled())
        self.assertEqual(self.core.calls, [])

    def test_native_session_import_is_explicit_and_does_not_resume(self):
        self.ready("codex")
        dialog = NativeSessionDialog(self.window, "codex")
        dialog.show()
        self.assertEqual(self.core.calls, [])
        dialog.load()
        for _ in range(50):
            if dialog.table.topLevelItemCount():
                break
            QTest.qWait(10)
        self.assertEqual(self.core.calls, [("discover_sessions", "codex")])
        self.assertEqual(dialog.table.topLevelItemCount(), 1)
        dialog.table.setCurrentItem(dialog.table.topLevelItem(0))
        self.assertEqual(self.core.imported_sessions, [])
        QTest.qWait(20)
        QTest.mouseClick(dialog.import_button, Qt.LeftButton)
        for _ in range(50):
            if self.core.imported_sessions:
                break
            QTest.qWait(10)
        self.assertEqual(len(self.core.imported_sessions), 1)
        self.assertEqual([call[0] for call in self.core.calls], ["discover_sessions", "import_session"])
        self.assertEqual(self.core.diagnostics("codex")["session"], "")
        self.assertNotIn("codex_session", self.core.current_task)
        dialog.close()

    def test_patch_save_delegates_to_core_without_direct_file_write(self):
        destination = str(Path(self.temp.name) / "selected.patch")
        patch_text = "--- a/file\n+++ b/file\n@@ -1 +1 @@\n-before\n+after\n"
        with patch("acw.ui.QFileDialog.getSaveFileName", return_value=(destination, "Patch (*.patch)")):
            self.window.save_patch(patch_text)
        for _ in range(50):
            if self.core.calls:
                break
            QTest.qWait(10)
        self.assertEqual(self.core.calls, [("save_patch", patch_text, destination)])
        self.assertFalse(Path(destination).exists(), "The UI must delegate persistence to core")

    def test_artifact_import_and_open_use_core_managed_paths(self):
        panel = ArtifactPanel(self.window)
        selected = str(Path(self.temp.name) / "chosen.md")
        with patch("acw.ui.QFileDialog.getOpenFileName", return_value=(selected, "Markdown (*.md)")):
            panel.import_file()
        for _ in range(50):
            if panel.table.topLevelItemCount():
                break
            QTest.qWait(10)
        self.assertEqual(self.core.calls[0], ("import_artifact", selected, "task-test", False))
        panel.table.setCurrentItem(panel.table.topLevelItem(0))
        # Backend-provided metadata path is not used to open a file.
        self.core.artifact_records[0]["path"] = "C:/outside/untrusted.md"
        with patch("acw.ui.QDesktopServices.openUrl", return_value=True) as open_url:
            panel.open_selected()
        self.assertEqual(self.core.calls[-1], ("artifact_path", "artifact-test"))
        self.assertTrue(open_url.call_args.args[0].toLocalFile().replace("\\", "/").endswith("/managed/registered.md"))
        with patch("acw.ui.QDesktopServices.openUrl", return_value=False):
            panel.open_selected()
        self.assertIn("Open failed", panel.status.text())
        panel.close()

    def test_screenshot_import_requires_explicit_confirmation(self):
        panel = ArtifactPanel(self.window)
        selected = str(Path(self.temp.name) / "chosen.png")
        with patch("acw.ui.QFileDialog.getOpenFileName", return_value=(selected, "Screenshots (*.png)")), patch.object(self.window, "confirm_screenshot_import", return_value=False):
            panel.import_file()
        self.assertEqual(self.core.calls, [])
        with patch("acw.ui.QFileDialog.getOpenFileName", return_value=(selected, "Screenshots (*.png)")), patch.object(self.window, "confirm_screenshot_import", return_value=True):
            panel.import_file()
        for _ in range(50):
            if self.core.calls:
                break
            QTest.qWait(10)
        self.assertEqual(self.core.calls, [("import_artifact", selected, "task-test", True)])
        panel.close()

    def test_screenshot_exports_cancel_without_pixel_review(self):
        image = {"id": "image-test", "type": "screenshot", "name": "chosen.png", "path": str(Path(self.temp.name) / "managed" / "chosen.png")}
        self.core.artifact_records.append(image)
        panel = ArtifactPanel(self.window)
        panel.table.setCurrentItem(panel.table.topLevelItem(0))
        with patch.object(self.window, "confirm_screenshot_export", return_value=False) as review:
            panel.export_selected()
        review.assert_called_once_with([image])
        self.assertEqual(self.core.calls, [])
        target = str(Path(self.temp.name) / "task.zip")
        with patch("acw.ui.QFileDialog.getSaveFileName", return_value=(target, "ZIP (*.zip)")), patch.object(self.window, "confirm_screenshot_export", return_value=False) as review:
            self.window.export()
        review.assert_called_once_with([image])
        self.assertEqual(self.core.calls, [])
        panel.close()

    def test_reviewed_screenshot_export_passes_explicit_core_consent(self):
        image = {"id": "image-test", "type": "screenshot", "name": "chosen.png", "path": str(Path(self.temp.name) / "managed" / "chosen.png")}
        self.core.artifact_records.append(image)
        panel = ArtifactPanel(self.window)
        panel.table.setCurrentItem(panel.table.topLevelItem(0))
        target_image = str(Path(self.temp.name) / "exported.png")
        with patch.object(self.window, "confirm_screenshot_export", return_value=True), patch("acw.ui.QFileDialog.getSaveFileName", return_value=(target_image, "Artifact (*.png)")):
            panel.export_selected()
        for _ in range(50):
            if self.core.calls:
                break
            QTest.qWait(10)
        self.assertEqual(self.core.calls[-1], ("export_artifact", "image-test", target_image, True))
        target_zip = str(Path(self.temp.name) / "exported.zip")
        with patch.object(self.window, "confirm_screenshot_export", return_value=True), patch("acw.ui.QFileDialog.getSaveFileName", return_value=(target_zip, "ZIP (*.zip)")):
            self.window.export()
        for _ in range(50):
            if any(call[0] == "export_task" for call in self.core.calls):
                break
            QTest.qWait(10)
        self.assertEqual(self.core.calls[-1], ("export_task", "task-test", "zip", target_zip, True))
        panel.close()

    def test_three_panel_synthetic_stream_burst_renders_and_remains_responsive(self):
        """300 cumulative fixture updates, zero agent/network/process calls."""
        final = {}
        for agent in ("claude", "dot", "codex"):
            self.ready(agent)
            self.core.caps[agent]["detail"] = "LABELED TEST DOUBLE · burst rendering only; no live backend"
            self.window.refresh_agent(agent)
        for step in range(1, 101):
            for agent in ("claude", "dot", "codex"):
                text = f"LABELED TEST DOUBLE — {agent.upper()}\nStreaming update {step}/100\n" + ("synthetic segment " * step)
                final[agent] = text
                self.core.pending.append({"id": f"event-{agent}-{step}", "message_id": f"burst-{agent}", "type": "message_delta", "agent": agent, "task_id": "task-test", "full_content": text})
        tick = []
        QTimer.singleShot(0, lambda: tick.append(True))
        started = time.monotonic()
        self.window.poll_events()
        QTest.qWait(30)
        self.assertTrue(tick, "The GUI event loop must process a queued callback during the burst")
        self.assertLess(time.monotonic() - started, 2.0, "A 300-event fixture burst must return control within two seconds")
        for agent in ("claude", "dot", "codex"):
            panel = self.window.panels[agent]
            self.assertEqual(len(panel.cards), 1)
            self.assertEqual(panel.cards[f"burst-{agent}"].body.toPlainText(), final[agent])
            self.assert_message_rendered(panel, f"burst-{agent}")
        self.assertEqual(self.core.calls, [], "Fixture rendering must not connect, send, resume, or call a backend")

    def test_native_history_is_explicit_read_only_without_import_or_resume(self):
        self.ready("codex")
        dialog = NativeSessionDialog(self.window, "codex")
        dialog.show()
        self.assertFalse(dialog.history_button.isEnabled())
        dialog.load()
        for _ in range(50):
            if dialog.table.topLevelItemCount():
                break
            QTest.qWait(10)
        self.assertEqual(self.core.calls, [("discover_sessions", "codex")])
        dialog.table.setCurrentItem(dialog.table.topLevelItem(0))
        self.assertTrue(dialog.history_button.isEnabled())
        self.assertEqual(len(self.core.calls), 1, "Selecting a row must not read history")
        prior_task = dict(self.core.current_task)
        with patch("acw.ui.main_window.NativeHistoryDialog") as preview:
            preview.return_value.exec.return_value = 0
            QTest.qWait(20)
            QTest.mouseClick(dialog.history_button, Qt.LeftButton)
            for _ in range(50):
                if preview.called:
                    break
                QTest.qWait(10)
            self.assertTrue(preview.called)
            history = preview.call_args.args[2]
        self.assertEqual(self.core.calls, [("discover_sessions", "codex"), ("native_history", "codex", "native-test-session")])
        self.assertEqual(self.core.current_task, prior_task)
        self.assertEqual(self.core.records, [])
        self.assertEqual(self.core.imported_sessions, [])
        viewer = NativeHistoryDialog("codex", "native-test-session", history, dialog)
        self.assertTrue(viewer.transcript.isReadOnly())
        self.assertIn("Fixture original response", viewer.transcript.toPlainText())
        viewer.close()
        dialog.close()

    def test_native_history_unavailable_and_backend_error_are_visible(self):
        self.core.native_history_available = False
        dialog = NativeSessionDialog(self.window, "claude")
        dialog.show()
        dialog.set_sessions([{"id": "native-test-session", "title": "Fixture"}])
        dialog.table.setCurrentItem(dialog.table.topLevelItem(0))
        self.assertFalse(dialog.history_button.isEnabled())
        self.assertIn("unavailable", dialog.history_button.toolTip())
        self.assertEqual(self.core.calls, [])
        self.core.native_history_available = True
        dialog.set_sessions([{"id": "native-test-session", "title": "Fixture"}])
        dialog.table.setCurrentItem(dialog.table.topLevelItem(0))
        with patch.object(self.core, "native_history", side_effect=RuntimeError("Official fixture helper: session no longer available")):
            dialog.view_history()
            for _ in range(50):
                if "session no longer available" in dialog.status.text():
                    break
                QTest.qWait(10)
        self.assertIn("Official fixture helper: session no longer available", dialog.status.text())
        self.assertEqual(self.core.imported_sessions, [])
        self.assertNotIn("claude_session", self.core.current_task)
        dialog.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
