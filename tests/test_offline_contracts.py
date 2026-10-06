"""New offline contracts for unchanged Core/Store/security/presentation code.

Synthetic text only, temporary data, no adapters or private CLI/helper imports.
This supplements the missing historical test archive; it is not a legacy-suite
or live-backend certification.
"""
from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from acw.core import WorkspaceCore
from acw.presentation import local_session_displays, project_label, session_display
from acw.security import OMITTED_REASONING, REDACTED, is_hidden_reasoning, safe_file, sanitize
from acw.store import now


class OfflineContractsTests(unittest.TestCase):
    def setUp(self):
        self.guards = []
        for target in ("socket.create_connection", "socket.socket.connect", "urllib.request.urlopen", "subprocess.Popen"):
            guard = patch(target, side_effect=AssertionError("External I/O forbidden: " + target))
            guard.start()
            self.guards.append(guard)
        self.temp = tempfile.TemporaryDirectory(prefix="acw-offline-contract-")
        self.root = Path(self.temp.name)
        self.core = WorkspaceCore(self.root / "data")
        self.core.git_snapshot = lambda *args, **kwargs: {"branch": "offline-fixture", "is_git": False}
        for directory in ("one/repo", "two/repo"):
            (self.root / directory).mkdir(parents=True)
        self.project_a = self.core.create_project("重複專案", self.root / "one/repo")
        self.project_b = self.core.create_project("重複專案", self.root / "two/repo")
        self.core.select_project(self.project_a["id"], sync=False)
        self.task_a = self.core.create_task("繁體中文任務甲")
        self.task_b = self.core.create_task("繁體中文任務乙")
        self.core.select_task(self.task_a["id"])
        self.core.drain_events()
        self.assertEqual({}, self.core.adapters)

    def tearDown(self):
        self.core.close()
        self.temp.cleanup()
        for guard in reversed(self.guards):
            guard.stop()

    def add_local_session(self, sid, task=None, title="同名對話"):
        task = task or self.task_a
        row = {"id": sid, "agent": "claude", "task_id": task["id"],
               "project_id": task["project_id"], "title": title,
               "cwd": self.project_a["repo_path"], "created_at": "2026-10-01T12:00:00+00:00",
               "updated_at": "2026-10-01T12:00:00+00:00", "metadata": {}}
        self.core.store.insert("sessions", row)
        return row

    def add_local_message(self, mid, text, *, task=None, sid="", agent="claude"):
        task = task or self.task_a
        self.core.store.insert("messages", {"id": mid, "task_id": task["id"], "agent": agent,
            "session_id": sid, "role": "assistant", "content": text,
            "timestamp": now(), "status": "complete", "metadata": {}})
        return self.core.store.get("messages", {"id": mid})

    def test_secret_sanitization_is_recursive_nonmutating_and_idempotent(self):
        original = {"content": "Authorization: Bearer fixture-secret-one\n可見內容",
                    "nested": [{"api_key": "fixture-secret-two", "thinking": "fixture private text"}],
                    "settings": {"OPENAI_API_KEY": "fixture-secret-three"}}
        untouched = deepcopy(original)
        cleaned = sanitize(original)
        self.assertEqual(untouched, original)
        self.assertEqual(REDACTED, cleaned["nested"][0]["api_key"])
        self.assertEqual(OMITTED_REASONING, cleaned["nested"][0]["thinking"])
        self.assertEqual(REDACTED, cleaned["settings"]["OPENAI_API_KEY"])
        self.assertIn("可見內容", cleaned["content"])
        self.assertNotIn("fixture-secret", json.dumps(cleaned))
        self.assertEqual(cleaned, sanitize(cleaned))

    def test_hidden_reasoning_types_including_summary_fragments_are_excluded(self):
        for kind in ("reasoning", "thinking", "reasoning_summary", "reasoning_summary_text_delta"):
            with self.subTest(kind=kind):
                payload = {"type": kind, "content": "fixture private reasoning"}
                self.assertTrue(is_hidden_reasoning(payload))
                self.assertEqual({"type": "omitted_reasoning", "redaction": "hidden reasoning excluded"}, sanitize(payload))

    def test_ordinary_visible_summary_remains_while_hidden_tags_are_removed(self):
        payload = {"type": "tool_result", "summary": "公開摘要", "content": "回答<thinking>fixture private reasoning</thinking>結論"}
        cleaned = sanitize(payload)
        self.assertEqual("公開摘要", cleaned["summary"])
        self.assertEqual("回答" + OMITTED_REASONING + "結論", cleaned["content"])
        self.assertNotIn("fixture private reasoning", json.dumps(cleaned))

    def test_core_hidden_reasoning_event_never_enters_messages_or_raw(self):
        self.core.ingest_event("claude", "reasoning", content="fixture private reasoning")
        self.assertEqual([], self.core.messages(agent="claude"))
        events = self.core.events(agent="claude")
        self.assertEqual("redaction", events[0]["type"])
        raw = self.core.read_raw(events[0]["raw_ref"])
        self.assertNotIn("fixture private reasoning", json.dumps(raw))
        self.assertNotIn("fixture private reasoning", "".join(path.read_text(encoding="utf-8") for path in self.core.store.raw_dir.glob("*.jsonl")))

    def test_stream_fragments_do_not_persist_split_secret_before_completion(self):
        self.core.ingest_event("claude", "message_start")
        self.core.ingest_event("claude", "message_delta", content="Authorization: Bearer fixture-")
        self.core.ingest_event("claude", "message_delta", content="synthetic-value\n中文完整回覆")
        before = self.core.messages(agent="claude")[0]
        self.assertNotIn("fixture-synthetic-value", before["content"])
        self.core.ingest_event("claude", "message_end")
        final = self.core.messages(agent="claude")[0]
        self.assertEqual("complete", final["status"])
        self.assertIn(REDACTED, final["content"])
        self.assertIn("中文完整回覆", final["content"])
        raw = "".join(path.read_text(encoding="utf-8") for path in self.core.store.raw_dir.glob("*.jsonl"))
        self.assertNotIn("fixture-synthetic-value", raw)

    def test_utf8_cjk_and_emoji_survive_store_raw_and_reopen(self):
        text = "繁體中文回覆，G8毛 🐈\n第二行"
        self.core.ingest_event("claude", "message_start")
        end = self.core.ingest_event("claude", "message_end", content=text)
        self.assertEqual(text, self.core.messages(agent="claude")[0]["content"])
        self.assertEqual(text, self.core.read_raw(end["raw_ref"])["content"])
        task_id = self.core.current_task_id
        self.core.close()
        self.core = WorkspaceCore(self.root / "data")
        self.assertEqual(task_id, self.core.current_task_id)
        self.assertEqual(text, self.core.messages(agent="claude")[0]["content"])
        self.assertEqual({}, self.core.adapters)

    def test_duplicate_session_labels_keep_exact_native_identifiers(self):
        rows = [self.add_local_session("native-id-one"), self.add_local_session("native-id-two")]
        with patch.object(self.core, "native_history", side_effect=AssertionError("Local labels must not read backend history")):
            displays = local_session_displays(self.core, "claude", rows)
        self.assertEqual({"native-id-one", "native-id-two"}, {display["id"] for row, display in displays})
        self.assertEqual(1, len({display["label"] for row, display in displays}))
        for row, display in displays:
            self.assertEqual(row["id"], display["id"])
            self.assertIn(row["id"], display["details"])
            self.assertNotIn(row["id"], display["label"])

    def test_duplicate_project_names_gain_real_distinguishing_path_clues(self):
        projects = [self.project_a, self.project_b]
        a, b = (project_label(project, projects) for project in projects)
        self.assertNotEqual(a, b)
        self.assertIn("one/repo", a)
        self.assertIn("two/repo", b)
        display = session_display({"id": "exact-native-id", "cwd": self.project_a["repo_path"], "title": "中文名稱"}, "claude", projects)
        self.assertEqual("exact-native-id", display["id"])
        self.assertIn(a, display["label"])

    def test_task_and_session_history_are_local_and_filtered_by_exact_context(self):
        self.add_local_session("session-a")
        self.add_local_session("session-b", self.task_b)
        self.add_local_message("message-a", "任務甲回覆", sid="session-a")
        self.add_local_message("message-b", "任務乙回覆", task=self.task_b, sid="session-b")
        self.assertEqual(["message-a"], [row["id"] for row in self.core.messages(agent="claude")])
        self.assertEqual(["message-b"], [row["id"] for row in self.core.get_history("claude", "session-b")])
        self.core.select_task(self.task_b["id"])
        self.assertEqual(["message-b"], [row["id"] for row in self.core.get_history("claude")])
        self.assertEqual({"session-a", "session-b"}, {row["id"] for row in self.core.sessions("claude")})

    def test_artifact_reads_reject_outside_roots_and_secret_filenames(self):
        allowed = self.root / "one/repo/report.txt"
        allowed.write_text("可讀報告", encoding="utf-8")
        outside = self.root / "outside.txt"
        outside.write_text("outside fixture", encoding="utf-8")
        secret = self.root / "one/repo/.env"
        secret.write_text("fixture synthetic env data", encoding="utf-8")
        self.assertEqual(allowed.resolve(), self.core.safe_artifact_path(allowed))
        for path in (outside, secret, self.root / "one/repo/../outside.txt"):
            with self.subTest(path=path):
                with self.assertRaises(PermissionError):
                    self.core.safe_artifact_path(path)

    def test_artifact_symlink_escape_is_rejected_before_read(self):
        outside = self.root / "outside.txt"
        outside.write_text("outside fixture", encoding="utf-8")
        link = self.root / "one/repo/linked-report.txt"
        link.symlink_to(outside)
        with self.assertRaises(PermissionError):
            self.core.safe_artifact_path(link)

    def test_artifact_size_limit_is_checked_before_import(self):
        path = self.root / "one/repo/oversized.txt"
        with path.open("wb") as handle:
            handle.truncate(16 * 1024 * 1024 + 1)
        with self.assertRaises(ValueError):
            self.core.safe_artifact_path(path)
        self.assertEqual([], self.core.artifacts())
        small = self.root / "one/repo/small.txt"
        small.write_bytes(b"12345")
        with self.assertRaises(ValueError):
            safe_file(small, [small.parent], max_bytes=4)

    def test_imported_text_artifact_is_owned_sanitized_utf8_and_independent_of_source(self):
        source = self.root / "one/repo/report.txt"
        source.write_text("繁體中文報告\nAPI_KEY=fixture-import-secret", encoding="utf-8")
        artifact = self.core.import_artifact(source)
        self.assertIn("繁體中文報告", artifact["content"])
        self.assertNotIn("fixture-import-secret", artifact["content"])
        owned = self.core.artifact_path(artifact["id"])
        self.assertTrue(owned.is_relative_to(self.core.store.artifact_dir))
        self.assertEqual(artifact["content"], owned.read_text(encoding="utf-8"))
        source.write_text("changed source", encoding="utf-8")
        target = self.root / "export.txt"
        self.core.export_artifact(artifact["id"], target)
        self.assertEqual(artifact["content"], target.read_text(encoding="utf-8"))

    def test_jsonl_artifacts_are_structurally_valid_and_filtered_per_record(self):
        text = json.dumps({"type": "tool_result", "token": "fixture-jsonl-secret", "content": "公開結果"}, ensure_ascii=False) + "\n"
        text += json.dumps({"type": "thinking", "content": "fixture private reasoning"}) + "\n"
        artifact = self.core.add_artifact("jsonl", "fixture.jsonl", content=text)
        rows = [json.loads(line) for line in artifact["content"].splitlines()]
        self.assertEqual(REDACTED, rows[0]["token"])
        self.assertEqual("公開結果", rows[0]["content"])
        self.assertEqual("omitted_reasoning", rows[1]["type"])
        with self.assertRaises(ValueError):
            self.core.add_artifact("jsonl", "invalid.jsonl", content="{invalid json}")

    def test_exports_reject_managed_secret_symlink_and_invalid_suffix_destinations(self):
        forbidden = [self.core.store.raw_dir / "blocked.json", self.core.store.artifact_dir / "blocked.json", self.root / ".env"]
        for target in forbidden:
            with self.subTest(target=target):
                with self.assertRaises(PermissionError):
                    self.core.export_task(self.task_a["id"], "json", target)
                self.assertFalse(target.exists())
        link = self.root / "linked-output"
        (self.root / "real-output").mkdir()
        link.symlink_to(self.root / "real-output", target_is_directory=True)
        with self.assertRaises(PermissionError):
            self.core.export_task(self.task_a["id"], "json", link / "task.json")
        with self.assertRaises(ValueError):
            self.core.export_task(self.task_a["id"], "json", self.root / "task.txt")
        self.assertFalse((self.root / "task.txt").exists())

    def test_task_json_html_and_zip_exports_preserve_text_without_unescaped_markup(self):
        text = "中文完整回覆 <script>literal source</script>"
        self.add_local_message("export-message", text)
        self.core.add_artifact("report", "../../unsafe-name", content="中文附件\nTOKEN=fixture-export-secret")
        target = self.root / "task.json"
        self.core.export_task(self.task_a["id"], "json", target)
        bundle = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(text, bundle["messages"][0]["content"])
        self.assertNotIn("fixture-export-secret", target.read_text(encoding="utf-8"))
        html = self.root / "task.html"
        self.core.export_task(self.task_a["id"], "html", html)
        self.assertIn("&lt;script&gt;literal source&lt;/script&gt;", html.read_text(encoding="utf-8"))
        self.assertNotIn("<script>literal source", html.read_text(encoding="utf-8"))
        archive = self.root / "task.zip"
        self.core.export_task(self.task_a["id"], "zip", archive)
        with zipfile.ZipFile(archive) as handle:
            self.assertTrue(all(not name.startswith("/") and ".." not in Path(name).parts for name in handle.namelist()))
            self.assertEqual(text, json.loads(handle.read("task.json"))["messages"][0]["content"])
            self.assertFalse(json.loads(handle.read("task.json"))["screenshots_included"])

    def test_store_public_query_is_readonly_and_secret_settings_are_redacted(self):
        with self.assertRaises(ValueError):
            self.core.store.query("DELETE FROM tasks")
        self.assertIsNotNone(self.core.get_task(self.task_a["id"]))
        self.core.store.set_setting("api_key", "fixture-setting-secret")
        self.assertEqual(REDACTED, self.core.store.get_setting("api_key"))
        self.core.store.set_setting("ordinary", {"notes": "繁體中文設定"})
        self.assertEqual({"notes": "繁體中文設定"}, self.core.store.get_setting("ordinary"))

    def test_automatic_orchestration_cannot_be_enabled_through_settings(self):
        for key in ("automatic", "automatic_orchestration", "automation.enabled"):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    self.core.set_setting(key, True)
                self.assertIsNone(self.core.get_setting(key))
        self.assertEqual("OFF", self.core.diagnostics()["automatic_orchestration"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
