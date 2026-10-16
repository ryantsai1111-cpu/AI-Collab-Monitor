"""An open conversation follows what the desktop app keeps appending to it."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from acw import desktop_sessions
from tests.workspace_fixtures import TranscriptFixtureCore as WorkspaceCore
from acw.ui import AGENTS, ActivityGroup, MessageCard
from test_desktop_sessions import SESSION, DesktopSessionFixture
from test_ui_refresh import OfflineAdapter, OfflineWindow


class LiveSyncTests(DesktopSessionFixture):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()
        desktop_sessions._HISTORY_FILES.clear()
        self.adapters = {agent: OfflineAdapter(agent) for agent in AGENTS}
        self.core = WorkspaceCore(self.root / "data", self.adapters)
        self.core.git_snapshot = lambda *a, **k: {"branch": "", "dirty": False, "ahead": 0, "behind": 0,
                                                  "status": "", "diff": "", "log": "", "is_git": False, "error": ""}
        self.record = desktop_sessions.list_desktop_sessions()[0]
        self.file = self.transcripts / "slug" / (SESSION + ".jsonl")
        self.window = OfflineWindow(self.core)
        self.window.sync_timer.stop()
        self.window.open_desktop_session(self.record, resume=False)
        self.panel = self.window.panels["claude"]
        self.window.sync_local_conversations()  # first look: remember the file as it was when opened

    def tearDown(self):
        self.window.timer.stop()
        self.window.sync_timer.stop()
        self.window.close()
        self.core.close()
        super().tearDown()

    def append(self, *rows):
        with self.file.open("a", encoding="utf-8") as out:
            for row in rows:
                out.write(json.dumps(row, ensure_ascii=False) + "\n")

    def cards(self):
        layout = self.panel.transcript_layout
        widgets = [layout.itemAt(i).widget() for i in range(layout.count())]
        return [w for w in widgets if isinstance(w, (MessageCard, ActivityGroup))]

    def contents(self):
        return [m["content"] for m in self.core.messages(agent="claude")]

    def test_nothing_changes_while_the_file_is_unchanged(self):
        before = len(self.cards())
        with patch.object(self.core, "sync_local_history", side_effect=AssertionError("no read without a change")):
            self.window.sync_local_conversations()
            self.window.sync_local_conversations()
        self.assertEqual(before, len(self.cards()))

    def test_new_desktop_messages_and_tools_appear_in_order_without_reopening(self):
        before = len(self.cards())
        self.append(
            {"type": "user", "uuid": "u9", "timestamp": "2099-10-02T00:00:01Z", "message": {"content": "Desktop 新問題"}},
            {"type": "assistant", "uuid": "a9", "timestamp": "2099-10-02T00:00:02Z",
             "message": {"id": "m9", "content": [{"type": "tool_use", "id": "t9", "name": "Bash", "input": {"command": "ls"}}]}},
            {"type": "assistant", "uuid": "a10", "timestamp": "2099-10-02T00:00:03Z",
             "message": {"id": "m10", "content": [{"type": "text", "text": "Desktop 新回覆"}]}})
        self.window.sync_local_conversations()
        self.assertEqual(["Desktop 新問題", "Desktop 新回覆"], self.contents()[-2:])
        new = self.cards()[before:]
        self.assertEqual(["MessageCard", "ActivityGroup", "MessageCard"], [type(card).__name__ for card in new])
        self.assertEqual([], [call for call in self.adapters["claude"].calls if call[0] not in ("set_project",)])
        again = len(self.cards())
        self.window.sync_local_conversations()
        self.append({"type": "assistant", "uuid": "a11", "timestamp": "2099-10-02T00:00:04Z",
                     "message": {"id": "m11", "content": [{"type": "text", "text": "再一則"}]}})
        self.window.sync_local_conversations()
        self.assertEqual(again + 1, len(self.cards()))
        self.assertEqual(1, self.contents().count("Desktop 新回覆"), "Nothing is imported twice")
        self.assertEqual([], self.window.reported_errors)

    def test_content_this_role_produced_itself_is_not_imported_again(self):
        self.panel.set_state("Busy")
        self.window.sync_local_conversations()
        self.append({"type": "assistant", "uuid": "own1", "timestamp": "2026-10-02T00:00:05Z",  # written during the busy turn
                     "message": {"id": "own", "content": [{"type": "tool_use", "id": "own-tool", "name": "Bash", "input": {"command": "own"}}]}})
        self.panel.set_state("Connected")
        self.window.sync_local_conversations()
        events = [e for e in self.core.events(agent="claude") if (e.get("payload") or {}).get("command") == "own"]
        self.assertEqual([], events, "A turn run from here is already shown by its live stream")

    def test_core_sync_ignores_roles_without_a_local_conversation(self):
        self.assertEqual([], self.core.sync_local_history("dot")["items"])
        self.assertEqual([], self.core.sync_local_history("codex")["items"])
        self.assertIsNone(desktop_sessions.history_stamp("claude", "../escape"))
        self.assertIsNone(desktop_sessions.history_stamp("claude", "00000000-0000-4000-8000-000000000000"))


if __name__ == "__main__":
    unittest.main()
