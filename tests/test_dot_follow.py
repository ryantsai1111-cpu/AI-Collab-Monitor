"""After a consented send, G8毛's reply is read automatically for a bounded time."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from acw.adapters.dot import DotAdapter
from acw.core import WorkspaceCore
from acw.ui import AGENTS
from test_ui_refresh import OfflineAdapter, OfflineWindow

TARGET = "fixture-dot-id"


class DotFollowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="acw-dot-follow-")
        self.calls, self.thread = [], [{"id": "m0", "who": "dot", "text": "之前的舊回覆"}]
        def runner(operation, **kwargs):
            self.calls.append(operation)
            if operation == "send":
                self.thread.append({"id": "u" + str(len(self.thread)), "who": "you", "text": kwargs["text"]})
                return {"id": "sent"}
            return {"messages": [{"id": m["id"], "content": {"text": m["text"]}, "created_at": ""} for m in self.thread],
                    "lines": [m["who"] + ": " + m["text"] for m in reversed(self.thread)]}
        self.adapters = {agent: OfflineAdapter(agent) for agent in AGENTS if agent != "dot"}
        self.core = WorkspaceCore(Path(self.temp.name) / "data", self.adapters)
        self.dot = DotAdapter(self.core.make_emitter("dot"), runner=runner)
        self.core.set_adapter("dot", self.dot)
        self.core.git_snapshot = lambda *a, **k: {"branch": "", "dirty": False, "ahead": 0, "behind": 0,
                                                  "status": "", "diff": "", "log": "", "is_git": False, "error": ""}
        (Path(self.temp.name) / "repo").mkdir()
        project = self.core.create_project("P", Path(self.temp.name) / "repo")
        self.core.select_project(project["id"], sync=False)
        task = self.core.create_task("t")
        self.dot.target, self.dot.target_name, self.dot.state, self.dot.session_id = TARGET, "G8毛", "Connected", TARGET
        self.dot._refresh_capabilities()
        self.core.store.update("tasks", {"id": task["id"]}, {"dot_session": TARGET})
        self.core._contexts.clear()
        self.window = OfflineWindow(self.core)
        self.window.refresh_agent("dot")
        self.panel = self.window.panels["dot"]
        self.consent = patch.object(self.panel, "dot_consent", side_effect=lambda action: self.dot.authorize_manual_action(action) or True)
        self.consent.start()

    def tearDown(self):
        self.consent.stop()
        self.panel._dot_timer.stop()
        self.window.timer.stop()
        self.window.close()
        self.core.close()
        self.temp.cleanup()

    def send(self, text="請確認 README 第一行"):
        self.panel.set_state("Connected")
        self.panel.input.setPlainText(text)
        self.panel.send()
        self.window.poll_events()
        self.panel._dot_timer.stop()  # the test drives the ticks

    def tick(self):
        self.panel.set_state("Connected")
        self.panel._dot_follow_tick()
        self.window.poll_events()

    def test_reply_arriving_after_the_send_is_shown_without_pressing_refresh(self):
        self.send()
        self.assertEqual(["send"], self.calls)
        self.assertIsNotNone(self.panel._dot_follow)
        self.tick()
        self.assertIsNotNone(self.panel._dot_follow, "Only old messages so far: keep reading")
        self.thread.append({"id": "r1", "who": "dot", "text": "我先確認專案"})
        self.tick()
        self.thread.append({"id": "r2", "who": "dot", "text": "你指的是哪個專案？"})
        self.tick()
        self.tick()
        self.tick()
        self.assertIsNone(self.panel._dot_follow, "Two identical reads in a row end the follow")
        self.assertEqual("已讀取新回覆 · 尚無原生完成訊號", self.panel.notice.text())
        replies = [m["content"] for m in self.core.dot_conversation_messages() if m["role"] == "assistant"]
        self.assertIn("你指的是哪個專案？", replies)
        self.assertIn("我先確認專案", replies)
        self.assertFalse(any(m["content"] in replies for m in self.core.messages(agent="dot")))
        with self.assertRaises(PermissionError):
            self.dot.refresh_messages(False)
        self.assertEqual([], self.window.reported_errors)

    def test_following_stops_at_the_time_limit_and_revokes_the_grant(self):
        self.send()
        self.panel._dot_follow["until"] = 0
        self.tick()
        self.assertIsNone(self.panel._dot_follow)
        self.assertIn("已停止自動讀取", self.panel.notice.text())
        reads = self.calls.count("messages")
        with self.assertRaises(PermissionError):
            self.dot.refresh_messages(False)
        self.assertEqual(reads, self.calls.count("messages"))

    def test_following_stops_on_disconnect_and_never_starts_without_a_send(self):
        self.assertIsNone(self.panel._dot_follow)
        self.window.poll_events()
        self.assertEqual([], self.calls)
        self.send()
        self.panel.set_state("Disconnected")
        self.assertIsNone(self.panel._dot_follow)
        self.assertIsNone(self.dot._run_grant)

    def test_inline_refresh_button_is_on_the_panel_and_still_asks_for_consent(self):
        self.assertTrue(self.panel.isAncestorOf(self.panel.dot_refresh_inline))
        self.panel.set_state("Connected")
        self.panel.dot_refresh_inline.click()
        self.window.poll_events()
        self.assertEqual(["messages"], self.calls)
        self.panel.dot_consent.assert_called_with("messages")


if __name__ == "__main__":
    unittest.main()
