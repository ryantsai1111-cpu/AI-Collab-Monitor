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
from acw.ui import AGENTS, SessionNavigator
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
             "message": {"id": "m1", "content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "TOOL INPUT"}},
                                                 {"type": "text", "text": "第二段"}]}},
            {"type": "user", "uuid": "u2", "timestamp": "2026-10-01T00:00:05Z",
             "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "TOOL OUTPUT"}]}},
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

    def test_a_conversation_mapped_into_the_wrong_task_is_moved_back_to_its_own(self):
        own = self.core.open_desktop_session(self.record)
        wrong = self.core.create_task("別的對話")
        self.core.store.update("tasks", {"id": wrong["id"]}, {"claude_session": SESSION})
        again = self.core.open_desktop_session(self.record)
        self.assertEqual(own["task_id"], again["task_id"])
        self.assertEqual("", self.core.get_task(wrong["id"])["claude_session"])
        self.assertEqual(SESSION, self.core.get_task(own["task_id"])["claude_session"])
        # A task that only shares the title is reused when it has no Claude conversation yet.
        self.core.store.update("tasks", {"id": own["task_id"]}, {"claude_session": ""})
        self.assertEqual(own["task_id"], self.core.open_desktop_session(self.record)["task_id"])
        self.assertEqual(2, len(self.core.list_tasks(project_id=own["project_id"])))

    def test_a_second_open_is_ignored_while_the_first_is_still_in_flight(self):
        window = OfflineWindow(self.core)
        try:
            pending = []
            original = window.run
            window.run = lambda operation, callback=None, agent=None, on_error=None: pending.append((operation, callback, agent, on_error))
            window.open_desktop_session(self.record, resume=True)
            window.open_desktop_session(self.record, resume=True)
            window.open_desktop_session(dict(self.record, title="另一個"), resume=True)
            self.assertEqual(1, len(pending), "Only the first open may start")
            self.assertFalse(window.navigator.isEnabled())
            window.run = original
            operation, callback, agent, on_error = pending.pop()
            callback(operation())
            self.assertTrue(window.navigator.isEnabled())
            self.assertEqual(1, [call[0] for call in self.adapters["claude"].calls].count("resume_session"))
            window.open_desktop_session(dict(self.record, id="../bad"), resume=True)
            self.assertTrue(window.navigator.isEnabled(), "A failed open must release the lock")
            window.reported_errors.clear()
        finally:
            window.timer.stop()
            window.close()

    def test_missing_folder_or_bad_identifier_is_refused(self):
        with self.assertRaises(ValueError):
            self.core.open_desktop_session(desktop_sessions.list_desktop_sessions()[1])
        with self.assertRaises(ValueError):
            self.core.open_desktop_session(dict(self.record, id="../escape"))
        self.assertEqual([], self.core.list_projects())

    def test_navigator_lists_projects_filters_and_only_enables_usable_rows(self):
        window = OfflineWindow(self.core)
        try:
            nav = window.navigator
            self.assertIsInstance(nav, SessionNavigator)
            self.assertIsNone(nav.sessions["claude"], "Nothing may be read before the page is shown")
            nav.set_sessions("claude", self.core.desktop_sessions("claude"))
            self.assertEqual(1, nav.tree.topLevelItemCount())  # archived conversation hidden by default
            nav.archived_action.setChecked(True)
            self.assertEqual(2, nav.tree.topLevelItemCount())
            nav.tree.setCurrentItem(nav.tree.topLevelItem(0).child(0))
            self.assertTrue(nav.open_button.isEnabled())
            nav.tree.setCurrentItem(nav.tree.topLevelItem(1).child(0))
            self.assertFalse(nav.open_button.isEnabled())
            self.assertFalse(nav.new_action.isEnabled())
            nav.search.setText("第一個")
            self.assertEqual(1, nav.tree.topLevelItemCount())
            nav.tree.setCurrentItem(nav.tree.topLevelItem(0).child(0))
            with patch.object(window, "open_desktop_session") as opened:
                nav.open_selected(True)
            self.assertEqual(SESSION, opened.call_args.args[0]["id"])
        finally:
            window.timer.stop()
            window.close()

    def test_sidebar_page_choice_persists_and_marks_the_open_conversation(self):
        window = OfflineWindow(self.core)
        try:
            self.assertEqual(1, window.sidebar_pages.currentIndex())
            window.show_desktop_sessions("claude")
            self.assertEqual("nav", self.core.get_setting("ui.sidebar_page"))
            self.assertEqual([SESSION, OTHER], [s["id"] for s in window.navigator.sessions["claude"]])
            window.open_desktop_session(self.record, resume=False)
            current = window.navigator.tree.currentItem()
            self.assertEqual(SESSION, current.data(0, Qt.UserRole)["id"])
            self.assertTrue(current.font(0).bold())
            window.show_sessions("claude")
            self.assertEqual(1, window.sidebar_pages.currentIndex())
            self.assertEqual([], window.reported_errors)
        finally:
            window.timer.stop()
            window.close()

    def test_tool_activity_is_imported_as_events_in_conversation_order(self):
        result = self.core.open_desktop_session(self.record)
        self.assertEqual(1, result["tools"])
        events = [e for e in self.core.events(result["task_id"], "claude") if e["type"] == "command"]
        self.assertEqual("TOOL INPUT", events[0]["payload"]["command"])
        self.assertEqual("TOOL OUTPUT", events[0]["payload"]["output"])
        self.assertNotIn("PRIVATE REASONING", json.dumps(self.core.events(result["task_id"], "claude"), ensure_ascii=False, default=str))
        window = OfflineWindow(self.core)
        try:
            layout = window.panels["claude"].transcript_layout
            kinds = [type(layout.itemAt(i).widget()).__name__ for i in range(layout.count()) if layout.itemAt(i).widget()]
            self.assertEqual(["MessageCard", "MessageCard", "ActivityGroup"], [k for k in kinds if k != "QLabel"])
            group = window.panels["claude"].activity_groups()[0]
            self.assertEqual("指令 1", group.toggle.text())
            self.assertFalse(group.inner.isVisible())
        finally:
            window.timer.stop()
            window.close()

    def test_rename_and_archive_stay_inside_the_workspace(self):
        before = {path: path.read_bytes() for path in self.meta.rglob("*.json")}
        self.core.set_desktop_override("claude", SESSION, title="我的名稱", archived=True)
        row = next(s for s in self.core.desktop_sessions("claude") if s["id"] == SESSION)
        self.assertEqual(("我的名稱", True), (row["title"], row["archived"]))
        self.core.set_desktop_override("claude", SESSION, title="", archived=False)
        row = next(s for s in self.core.desktop_sessions("claude") if s["id"] == SESSION)
        self.assertEqual(("第一個對話", False), (row["title"], row["archived"]))
        self.assertEqual(before, {path: path.read_bytes() for path in self.meta.rglob("*.json")})
        with self.assertRaises(ValueError):
            self.core.set_desktop_override("claude", "../escape", title="x")

    def test_codex_threads_are_listed_opened_and_resumed(self):
        thread = "01a10fd2-424f-79e0-893a-8c2ee65913fd"
        home = self.root / "codex-home"
        day = home / "sessions" / "2026" / "10" / "06"
        day.mkdir(parents=True)
        (home / "session_index.jsonl").write_text(json.dumps({"id": thread, "thread_name": "Codex 對話", "updated_at": "2026-10-06T05:00:00.000Z"}, ensure_ascii=False) + "\n", encoding="utf-8")
        rows = [
            {"timestamp": "2026-10-06T04:00:00.000Z", "type": "session_meta", "payload": {"id": thread, "cwd": str(self.repo), "timestamp": "2026-10-06T04:00:00.000Z", "base_instructions": {"text": "NOT COPIED"}}},
            {"timestamp": "2026-10-06T04:00:01.000Z", "type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "UserMessage", "id": "u1", "content": [{"type": "text", "text": "修這個"}]}}},
            {"timestamp": "2026-10-06T04:00:02.000Z", "type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "Reasoning", "id": "r1", "raw_content": ["PRIVATE REASONING"]}}},
            {"timestamp": "2026-10-06T04:00:03.000Z", "type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "CommandExecution", "id": "c1", "command": ["pwsh", "-c", "dir"], "parsed_cmd": [{"cmd": "dir"}], "stdout": "listing", "stderr": ""}}},
            {"timestamp": "2026-10-06T04:00:04.000Z", "type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "FileChange", "id": "f1", "changes": {str(self.repo / "a.py"): {"type": "update", "unified_diff": "+new line"}}}}},
            {"timestamp": "2026-10-06T04:00:05.000Z", "type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "AgentMessage", "id": "a1", "phase": "final_answer", "content": [{"type": "Text", "text": "修好了"}]}}},
        ]
        (day / ("rollout-2026-10-06T12-00-00-" + thread + ".jsonl")).write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
        with patch.object(desktop_sessions, "codex_roots", return_value=[home]):
            listed = self.core.desktop_sessions("codex")
            self.assertEqual([("codex", thread, "Codex 對話")], [(s["agent"], s["id"], s["title"]) for s in listed])
            self.assertNotIn("NOT COPIED", json.dumps(listed))
            window = OfflineWindow(self.core)
            try:
                window.open_desktop_session(listed[0], resume=True)
                self.assertEqual(thread, self.core.agent_task("codex")["codex_session"])
                self.assertIsNone(self.core.current_task)
                self.assertEqual(["修這個", "修好了"], [m["content"] for m in self.core.messages(agent="codex")])
                events = {e["type"]: e["payload"] for e in self.core.events(agent="codex") if e["type"] in ("command", "file_edit")}
                self.assertEqual("listing", events["command"]["output"])
                self.assertIn("+new line", json.dumps(events["file_edit"]["input"]))
                self.assertNotIn("PRIVATE REASONING", json.dumps(self.core.events(agent="codex"), default=str))
                self.assertIn(("resume_session", thread), self.adapters["codex"].calls)
                self.assertEqual([], [call for call in self.adapters["claude"].calls if call[0] != "set_project"])
                self.assertEqual([], window.reported_errors)
            finally:
                window.timer.stop()
                window.close()

    def test_window_open_resumes_exact_session_only_when_asked(self):
        window = OfflineWindow(self.core)
        try:
            window.open_desktop_session(self.record, resume=False)
            self.assertNotIn("resume_session", [call[0] for call in self.adapters["claude"].calls])
            self.assertEqual(SESSION, self.core.agent_task("claude")["claude_session"])
            self.assertIsNone(self.core.current_task)
            window.open_desktop_session(self.record, resume=True)
            self.assertIn(("resume_session", SESSION), self.adapters["claude"].calls)
            self.assertEqual([], window.reported_errors)
        finally:
            window.timer.stop()
            window.close()


if __name__ == "__main__":
    unittest.main()
