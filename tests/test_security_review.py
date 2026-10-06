"""Independent security regression review; every value is a synthetic test canary.

No installed-agent state, credentials, session files, or real project is accessed.
"""
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock

from acw.security import safe_file, sanitize
from acw.store import Store


class SecurityBoundaryReview(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="acw-security-review-")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_nested_sensitive_fields_are_redacted_without_mutating_source(self):
        canary = "SYNTHETIC_SECRET_CANARY_92843"
        data = {"nested": [{"accessToken": canary, "api_key": canary,
                            "password": canary, "cookie": canary}],
                "safe": "ordinary response"}
        before = json.dumps(data, sort_keys=True)
        filtered = sanitize(data)
        self.assertNotIn(canary, json.dumps(filtered))
        self.assertEqual(before, json.dumps(data, sort_keys=True))
        self.assertEqual("ordinary response", filtered["safe"])

    def test_entire_cookie_header_is_redacted(self):
        canary = "SYNTHETIC_SECOND_COOKIE_CANARY"
        text = "Cookie: session=synthetic; refresh=" + canary + "; locale=en\nOrdinary text"
        result = sanitize({"stdout": text})
        self.assertNotIn(canary, json.dumps(result))
        self.assertIn("Ordinary text", result["stdout"])

    def test_environment_style_credential_fields_are_redacted(self):
        canary = "SYNTHETIC_ENV_CREDENTIAL_CANARY"
        fields = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DATABASE_PASSWORD",
                  "AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN")
        payload = {"tool_result": {"env": {name: canary for name in fields}},
                   "usage": {"input_tokens": 12, "output_tokens": 9}}
        cleaned = sanitize(payload)
        self.assertNotIn(canary, json.dumps(cleaned))
        self.assertEqual(12, cleaned["usage"]["input_tokens"])
        self.assertEqual(9, cleaned["usage"]["output_tokens"])

    def test_environment_style_assignments_are_redacted_in_command_output(self):
        canary = "SYNTHETIC_ENV_OUTPUT_CANARY"
        output = "OPENAI_API_KEY=" + canary + "\nDATABASE_PASSWORD=" + canary + "\nordinary=42"
        cleaned = sanitize({"output": output})["output"]
        self.assertNotIn(canary, cleaned)
        self.assertIn("ordinary=42", cleaned)

    def test_hidden_reasoning_rpc_envelope_does_not_reach_disk(self):
        canary = "SYNTHETIC_PRIVATE_REASONING_CANARY"
        store = Store(self.root / "store")
        try:
            ref = store.append_raw("codex", {"method": "item/reasoning/textDelta",
                "params": {"threadId": "synthetic-thread", "delta": canary}})
            stored = store.read_raw(ref)
            self.assertNotIn(canary, json.dumps(stored))
            self.assertNotIn(canary.encode(), (store.raw_dir / "codex.jsonl").read_bytes())
        finally:
            store.close()

    def test_raw_partial_secret_is_not_reconstructible_from_delta_frames(self):
        # Split deliberately before the recognized key's identifying body. The
        # application must defer or omit raw fragment content, rather than rely
        # on a stateless regex applied independently to each network chunk.
        secret = "sk-proj-SYNTHETICCANARY01234567890"
        fragments = [secret[:8], secret[8:]]
        store = Store(self.root / "store")
        try:
            for fragment in fragments:
                store.append_raw("codex", {"method": "item/agentMessage/delta",
                    "params": {"threadId": "synthetic-thread", "itemId": "synthetic-item",
                               "delta": fragment}})
            disk = (store.raw_dir / "codex.jsonl").read_text(encoding="utf-8")
            self.assertNotIn(secret, disk)
            self.assertNotIn("SYNTHETICCANARY01234567890", disk)
            self.assertNotIn(secret, json.dumps(sanitize({"content": secret})))
        finally:
            store.close()

    def test_file_boundary_rejects_parent_traversal_and_secret_names(self):
        project = self.root / "project"
        project.mkdir()
        allowed = project / "notes.txt"
        allowed.write_text("safe synthetic note", encoding="utf-8")
        outside = self.root / "outside.txt"
        outside.write_text("outside boundary", encoding="utf-8")
        credential = project / "auth.json"
        credential.write_text("synthetic excluded filename", encoding="utf-8")
        self.assertEqual(allowed.resolve(), safe_file(allowed, [project]))
        with self.assertRaises(PermissionError):
            safe_file(project / ".." / "outside.txt", [project])
        with self.assertRaises(PermissionError):
            safe_file(credential, [project])

    def test_raw_reference_cannot_escape_raw_directory(self):
        outside = self.root / "outside.jsonl"
        outside.write_text('{"synthetic":"outside boundary"}\n', encoding="utf-8")
        store = Store(self.root / "store")
        try:
            with self.assertRaises(PermissionError):
                store.read_raw("../outside.jsonl:0")
            with self.assertRaises(PermissionError):
                store.read_raw(str(outside) + ":0")
        finally:
            store.close()

    def test_known_secret_and_reasoning_omitted_in_nested_backend_output(self):
        secret = "sk-proj-SYNTHETICCANARY01234567890"
        reasoning = "SYNTHETIC_HIDDEN_THINKING_CANARY"
        result = sanitize({"type": "assistant", "message": {"content": [
            {"type": "thinking", "thinking": reasoning},
            {"type": "text", "text": "The synthetic key is " + secret},
            {"type": "text", "text": "The answer is ordinary text."}]}})
        encoded = json.dumps(result)
        self.assertNotIn(secret, encoded)
        self.assertNotIn(reasoning, encoded)
        self.assertIn("The answer is ordinary text.", encoded)

    def test_normalized_streams_leave_no_secret_in_sqlite_wal_or_raw_files(self):
        from acw.core import WorkspaceCore
        core = WorkspaceCore(self.root / "core-data")
        try:
            # Explicit test substitute for branch discovery; no real repository
            # or installed agent is touched by this persistence regression.
            core.git_snapshot = Mock(return_value={"branch": "security-test"})
            project_dir = self.root / "isolated-project"
            project_dir.mkdir()
            project = core.create_project("Synthetic security test", project_dir)
            core.select_project(project["id"], sync=False)
            core.create_task("Synthetic stream safety")
            secret = "sk-proj-SYNTHETICNORMALIZEDCANARY0000"
            core.ingest_event("codex", "message_start", content="")
            core.ingest_event("codex", "message_delta", content=secret[:8])
            core.ingest_event("codex", "message_delta", content=secret[8:])
            core.ingest_event("codex", "message_end", content=secret)
            for fragment in (secret[:8], secret[8:]):
                core.ingest_event("codex", "event", event_type="command_output",
                                  summary=fragment, output_stream="combined")
            core.ingest_event("codex", "command", command="synthetic-command",
                              output=secret, output_stream="combined", exit_code=0)
            core.ingest_event("codex", "raw", raw={"method": "item/reasoning/textDelta",
                              "params": {"delta": "SYNTHETIC_CORE_PRIVATE_REASONING"}})
            self.assertTrue(core.messages())
            for path in core.data_dir.rglob("*"):
                if path.is_file():
                    data = path.read_bytes()
                    self.assertNotIn(b"SYNTHETICNORMALIZEDCANARY0000", data, str(path))
                    self.assertNotIn(b"SYNTHETIC_CORE_PRIVATE_REASONING", data, str(path))
        finally:
            core.store.close()

    def test_all_task_exports_and_diagnostics_exclude_secrets_and_escape_html(self):
        from acw.core import WorkspaceCore
        core = WorkspaceCore(self.root / "export-core")
        try:
            core.git_snapshot = Mock(return_value={"branch": "security-test"})
            project_dir = self.root / "export-project"
            project_dir.mkdir()
            project = core.create_project("Synthetic export test", project_dir)
            core.select_project(project["id"], sync=False)
            task = core.create_task("Export security review")
            canary = "SYNTHETIC_EXPORT_PASSWORD_CANARY"
            private = "SYNTHETIC_EXPORT_PRIVATE_REASONING"
            content = ("Original A\npassword=" + canary +
                       "\n<thinking>" + private + "</thinking>\n<script>alert('synthetic')</script>")
            core.ingest_event("claude", "message_end", content=content)
            source = core.messages(agent="claude")[-1]
            core.prepare_handoff(source["id"], "dot", annotation="Synthetic note")
            core.add_artifact("report", "synthetic report", content="password=" + canary)
            paths = []
            for kind in ("markdown", "json", "html", "zip"):
                paths.append(core.export_task(task["id"], kind, self.root / ("task-export." + kind)))
            paths.append(core.export_diagnostics(self.root / "workspace-diagnostics.zip"))
            for path in paths:
                if zipfile.is_zipfile(path):
                    with zipfile.ZipFile(path) as archive:
                        entries = [(name, archive.read(name).decode("utf-8")) for name in archive.namelist()]
                else:
                    entries = [(path.name, path.read_text(encoding="utf-8"))]
                for name, text in entries:
                    self.assertNotIn(canary, text, str(path) + ":" + name)
                    self.assertNotIn(private, text, str(path) + ":" + name)
                    if name.endswith(".html"):
                        self.assertNotIn("<script>", text)
            self.assertIn("Original A", paths[0].read_text(encoding="utf-8"))
            self.assertIn("&lt;script&gt;", paths[2].read_text(encoding="utf-8"))
        finally:
            core.close()


if __name__ == "__main__":
    unittest.main()
