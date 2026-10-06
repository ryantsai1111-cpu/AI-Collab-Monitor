"""Claude desktop session picker: fixture files only, no real desktop data, no backend."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from acw import desktop_sessions
from acw.core import WorkspaceCore
from acw.ui import AGENTS, DesktopSessionsDialog
from test_ui_refresh import OfflineAdapter, OfflineWindow

SESSION = "11111111-2222-4333-8444-555555555555"
OTHER = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


class DesktopSessionFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="acw-desktop-")
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo-one"
        self.repo.mkdir()
        self.meta = self.root / "sessions"
        store = self.meta / "account" / "org"
        store.mkdir(parents=True)
        self.write_meta(store / "local_one.json", SESSION, self.repo, "第一個對話", 2000)
        self.write_meta(store / "local_two.json", OTHER, self.root / "gone", "資料夾不見了", 1000, archived=True)
        (store / "local_bad.json").write_text("{not json", encoding="utf-8")
        (store / "local_noid.json").write_text(json.dumps({"cwd": str(self.repo), "cliSessionId": "../escape"}), encoding="utf-8")
        self.transcripts = self.root / "projects"
        (self.transcripts / "slug").mkdir(parents=True)
        rows = [
            {"type": "user", "uuid": "u1", "timestamp": "2026-10-01T00:00:01Z", "message": {"content": "請幫我看這段"}},
            {"type": "assistant", "uuid": "a1", "timestamp": "2026-10-01T00:00:02Z",
             "message": {"id": "m1", "content": [{"type": "thinking", "thinking": "PRIVATE REASONING"}]}},
            {"type": "assistant", "uuid": "a2", "timestamp": "2026-10-01T00:00:03Z",
             "message": {"id": "m1", "content": [{"type": "text", "text": "第一段"}]}},
            {"type": "assistant", "uuid": "a3", "timestamp": "2026-10-01T00:00:04Z",
             "message": {"id": "m1", "content": [{"type": "tool_use", "name": "Bash", "input": {"command": "TOOL INPUT"}},
                                                 {"type": "text", "text": "第二段"}]}},
            {"type": "user", "uuid": "u2", "timestamp": "2026-10-01T00:00:05Z",
             "message": {"content": [{"type": "tool_result", "content": "TOOL OUTPUT"}]}},
            {"type": "user", "uuid": "u3", "isMeta": True, "message": {"content": "META ROW"}},
            {"type": "assistant", "uuid": "a4", "isSidechain": True, "message": {"content": [{"type": "text", "text": "SUBAGENT"}]}},
            {"type": "summary", "summary": "ignored"},
        ]
        (self.transcripts / "slug" / (SESSION + ".jsonl")).write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\nnot json\n", encoding="utf-8")
        self.guards = [patch.object(desktop_sessions, "session_roots", return_value=[self.meta]),
                       patch.object(desktop_sessions, "transcript_roots", return_value=[self.transcripts])]
        for guard in self.guards:
            guard.start()

    def tearDown(self):
        for guard in self.guards:
            guard.stop()
        self.temp.cleanup()

    @staticmethod
    def write_meta(path, session_id, cwd, title, activity, archived=False):
        path.write_text(json.dumps({"cliSessionId": session_id, "cwd": str(cwd), "title": title, "model": "fixture-model",
                                    "lastActivityAt": activity, "createdAt": activity, "isArchived": archived,
                                    "enabledMcpTools": {"secret": "NOT COPIED"}}, ensure_ascii=False), encoding="utf-8")


class ReaderTests(DesktopSessionFixture):
    def test_list_returns_only_whitelisted_fields_and_skips_unreadable_files(self):
        sessions = desktop_sessions.list_desktop_sessions()
        self.assertEqual([SESSION, OTHER], [s["id"] for s in sessions])
        self.assertEqual("第一個對話", sessions[0]["title"])
        self.assertTrue(sessions[0]["cwd_exists"])
        self.assertFalse(sessions[1]["cwd_exists"])
        self.assertTrue(sessions[1]["archived"])
        self.assertNotIn("NOT COPIED", json.dumps(sessions))

    def test_grouping_is_by_folder_with_newest_first(self):
        groups = desktop_sessions.group_by_project(desktop_sessions.list_desktop_sessions())
        self.assertEqual(["repo-one", "gone"], [g["name"] for g in groups])

    def test_transcript_keeps_only_visible_text_and_rejoins_split_replies(self):
        messages = desktop_sessions.read_transcript(SESSION)
        self.assertEqual([("user", "請幫我看這段"), ("assistant", "第一段\n\n第二段")],
                         [(m["role"], m["content"]) for m in messages])
        dumped = json.dumps(messages, ensure_ascii=False)
        for hidden in ("PRIVATE REASONING", "TOOL INPUT", "TOOL OUTPUT", "META ROW", "SUBAGENT"):
            self.assertNotIn(hidden, dumped)

    def test_transcript_rejects_non_uuid_identifiers(self):
        for bad in ("../x", "*", "", "not-a-uuid"):
            with self.assertRaises(ValueError):
                desktop_sessions.read_transcript(bad)


class CoreAndUiTests(DesktopSessionFixture):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()
        self.adapters = {agent: OfflineAdapter(agent) for agent in AGENTS}
        self.core = WorkspaceCore(self.root / "data", self.adapters)
        self.core.git_snapshot = lambda *a, **k: {"branch": "", "dirty": False, "ahead": 0, "behind": 0,
                                                  "status": "", "diff": "", "log": "", "is_git": False, "error": ""}
        self.record = desktop_sessions.list_desktop_sessions()[0]

    def tearDown(self):
        self.core.close()
        super().tearDown()

    def test_open_creates_project_task_mapping_and_history_without_contacting_claude(self):
        result = self.core.open_desktop_session(self.record)
        self.assertEqual(2, result["imported"])
        self.assertEqual(str(self.repo.resolve()), self.core.current_project["repo_path"])
        self.assertEqual("第一個對話", self.core.current_task["title"])
        self.assertEqual(SESSION, self.core.current_task["claude_session"])
        self.assertEqual(["請幫我看這段", "第一段\n\n第二段"],
                         [m["content"] for m in self.core.messages(result["task_id"], "claude")])
        self.assertEqual([], [call for call in self.adapters["claude"].calls if call[0] != "set_project"])

    def test_opening_twice_reuses_project_and_task_and_does_not_duplicate_history(self):
        first = self.core.open_desktop_session(self.record)
        second = self.core.open_desktop_session(self.record)
        self.assertEqual((first["project_id"], first["task_id"]), (second["project_id"], second["task_id"]))
        self.assertEqual(0, second["imported"])
        self.assertEqual(1, len(self.core.list_projects()))
        self.assertEqual(2, len(self.core.messages(first["task_id"], "claude")))

    def test_missing_folder_or_bad_identifier_is_refused(self):
        with self.assertRaises(ValueError):
            self.core.open_desktop_session(desktop_sessions.list_desktop_sessions()[1])
        with self.assertRaises(ValueError):
            self.core.open_desktop_session(dict(self.record, id="../escape"))
        self.assertEqual([], self.core.list_projects())

    def test_dialog_lists_projects_filters_and_only_enables_usable_rows(self):
        window = OfflineWindow(self.core)
        try:
            dialog = DesktopSessionsDialog(window)
            dialog.set_sessions(self.core.desktop_sessions())
            self.assertEqual(1, dialog.tree.topLevelItemCount())  # archived session hidden by default
            dialog.archived.setChecked(True)
            self.assertEqual(2, dialog.tree.topLevelItemCount())
            dialog.tree.setCurrentItem(dialog.tree.topLevelItem(0).child(0))
            self.assertTrue(dialog.open_button.isEnabled())
            dialog.tree.setCurrentItem(dialog.tree.topLevelItem(1).child(0))
            self.assertFalse(dialog.open_button.isEnabled())
            self.assertFalse(dialog.new_button.isEnabled())
            dialog.search.setText("第一個")
            self.assertEqual(1, dialog.tree.topLevelItemCount())
            dialog.tree.setCurrentItem(dialog.tree.topLevelItem(0).child(0))
            with patch.object(window, "open_desktop_session") as opened:
                dialog.open_selected(True)
            self.assertEqual(SESSION, opened.call_args.args[0]["id"])
        finally:
            window.timer.stop()
            window.close()

    def test_window_open_resumes_exact_session_only_when_asked(self):
        window = OfflineWindow(self.core)
        try:
            window.open_desktop_session(self.record, resume=False)
            self.assertNotIn("resume_session", [call[0] for call in self.adapters["claude"].calls])
            self.assertEqual(SESSION, self.core.current_task["claude_session"])
            window.open_desktop_session(self.record, resume=True)
            self.assertIn(("resume_session", SESSION), self.adapters["claude"].calls)
            self.assertEqual([], window.reported_errors)
        finally:
            window.timer.stop()
            window.close()


if __name__ == "__main__":
    unittest.main()
