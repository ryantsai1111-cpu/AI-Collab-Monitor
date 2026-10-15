"""First-run guidance: an empty workspace must explain what is missing instead of failing."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from acw.core import WorkspaceCore
from acw.ui import AGENTS
from test_ui_refresh import OfflineAdapter, OfflineWindow


class FirstRunGuidanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="acw-first-run-")
        self.adapters = {agent: OfflineAdapter(agent) for agent in AGENTS}
        self.core = WorkspaceCore(Path(self.temp.name) / "data", self.adapters)
        self.window = OfflineWindow(self.core)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.timer.stop()
        self.window.close()
        self.core.close()
        self.temp.cleanup()

    def test_claude_connect_without_project_offers_project_creation_and_does_not_connect(self):
        panel = self.window.panels["claude"]
        with patch.object(self.window, "require_project") as guide:
            QTest.mouseClick(panel.connect_button, Qt.LeftButton)
        guide.assert_called_once()
        self.assertIn("Claude", guide.call_args.args[0])
        self.assertEqual([], self.adapters["claude"].calls)
        self.assertEqual("Disconnected", panel.connection_state)
        self.assertEqual([], self.window.reported_errors)

    def test_codex_connect_without_project_guides_only_codex_without_connecting(self):
        with patch.object(self.window, "require_project") as guide:
            QTest.mouseClick(self.window.panels["codex"].connect_button, Qt.LeftButton)
        guide.assert_called_once()
        self.assertEqual('codex', guide.call_args.kwargs['agent'])
        self.assertEqual([], self.adapters["codex"].calls)

    def test_first_send_creates_own_conversation_without_task_form(self):
        (Path(self.temp.name) / "repo").mkdir()
        project = self.core.create_project("First", Path(self.temp.name) / "repo")
        self.core.select_agent_project('codex', project['id'])
        self.window.reload_context()
        panel = self.window.panels["codex"]
        self.adapters["codex"].state = "Connected"
        self.window.refresh_agent("codex")
        panel.input.setPlainText("keep me")
        with patch.object(self.window, "show_sessions") as guide:
            panel.send()
        guide.assert_not_called()
        self.assertEqual([], self.window.reported_errors)
        self.assertEqual('', panel.input.toPlainText())
        self.assertEqual(['create_session', 'send'], [call[0] for call in self.adapters['codex'].calls])
        self.assertIsNotNone(self.core.agent_task('codex'))
        self.assertIsNone(self.core.agent_task('claude'))
        self.assertIsNone(self.core.current_task)


if __name__ == "__main__":
    unittest.main()
