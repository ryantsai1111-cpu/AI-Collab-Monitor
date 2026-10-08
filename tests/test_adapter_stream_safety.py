"""Offline adapter-handler -> Core stream and terminal safety regressions.

All credential-shaped strings below are synthetic canaries. No executable,
authentication, native session, or network transport is used by these tests.
"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from acw.adapters.claude import ClaudeAdapter
from acw.adapters.codex import CodexAdapter
from acw.core import WorkspaceCore
from acw.security import sanitize


TOKEN_PREFIX = "sk-proj-ABCDEFGH"
TOKEN_SUFFIX = "SYNTHETIC_SUFFIX"
SYNTHETIC_TOKEN = TOKEN_PREFIX + TOKEN_SUFFIX
SAFE_LINE = "Public first line\n"
PRIVATE_REASONING = "PRIVATE_REASONING_CANARY"


class AdapterStreamSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="acw-adapter-stream-safety-")
        self.root = Path(self.temp.name)
        self.repo = self.root / "isolated-repo"
        self.repo.mkdir()
        self.cores = []
        self.transports = []

    def tearDown(self):
        for core in self.cores:
            if not core._closed:
                core.close()
        for transport in self.transports:
            transport.assert_not_called()
        self.temp.cleanup()

    def make_core(self, agent, name="data"):
        adapter_type = CodexAdapter if agent == "codex" else ClaudeAdapter
        adapter = adapter_type(lambda kind, **payload: None)
        for method in ("_write", "_request"):
            transport = Mock(side_effect=AssertionError("Offline test attempted transport"))
            setattr(adapter, method, transport)
            self.transports.append(transport)
        core = WorkspaceCore(self.root / name, {agent: adapter})
        self.cores.append(core)
        core.git_snapshot = lambda project_id=None: {"branch": "fixture", "diff": "", "status": "", "log": ""}
        project = core.create_project("Offline stream fixture", self.repo)
        core.select_project(project["id"], sync=False)
        core.create_task("Replay isolated adapter stream")
        adapter.session_id = "offline-session"
        core.ingest_event(agent, "session", session_id=adapter.session_id)
        return core, adapter

    @staticmethod
    def codex_notification(adapter, method, **params):
        adapter._handle_message({"method": method, "params": {"threadId": adapter.session_id, **params}})

    def start_message(self, adapter, message_id="visible-message", turn_id="active-turn"):
        if isinstance(adapter, CodexAdapter):
            self.codex_notification(adapter, "turn/started", turn={"id": turn_id})
            self.codex_notification(adapter, "item/started", turnId=turn_id,
                                    item={"type": "agentMessage", "id": message_id})
        else:
            adapter.set_state("Busy")
            adapter._handle({"type": "stream_event", "event": {
                "type": "message_start", "message": {"id": message_id}}})

    def delta(self, adapter, text, message_id="visible-message"):
        if isinstance(adapter, CodexAdapter):
            self.codex_notification(adapter, "item/agentMessage/delta",
                                    turnId=adapter._turn_id, itemId=message_id, delta=text)
        else:
            adapter._handle({"type": "stream_event", "event": {
                "type": "content_block_delta", "delta": {"type": "text_delta", "text": text}}})

    def finish_message(self, adapter, text):
        if isinstance(adapter, CodexAdapter):
            self.codex_notification(adapter, "item/completed", turnId=adapter._turn_id,
                                    item={"type": "agentMessage", "id": "visible-message", "text": text})
        else:
            adapter._handle({"type": "stream_event", "event": {"type": "message_stop"}})

    def assert_safe_surfaces(self, core):
        """Check queried rows, actual DB/WAL/raw bytes, and the UI event queue."""
        events = core.drain_events(limit=100000)
        serialized = json.dumps(events, ensure_ascii=False)
        self.assertNotIn(SYNTHETIC_TOKEN, serialized)
        self.assertNotIn(TOKEN_SUFFIX, serialized)
        self.assertNotIn(PRIVATE_REASONING, serialized)
        for event in events:
            if event["type"] == "message_delta":
                self.assertNotIn("delta", event)
                self.assertEqual(event["content"], event["full_content"])
        for table in sorted(core.store.TABLES):
            rows = json.dumps(core.store.query("SELECT * FROM " + table), ensure_ascii=False)
            self.assertNotIn(SYNTHETIC_TOKEN, rows)
            self.assertNotIn(TOKEN_SUFFIX, rows)
            self.assertNotIn(PRIVATE_REASONING, rows)
        for path in core.data_dir.rglob("*"):
            if path.is_file():
                data = path.read_bytes()
                self.assertNotIn(SYNTHETIC_TOKEN.encode(), data, str(path))
                self.assertNotIn(TOKEN_SUFFIX.encode(), data, str(path))
                self.assertNotIn(PRIVATE_REASONING.encode(), data, str(path))
        return events

    def test_split_credential_survives_adapter_only_in_memory_before_restart(self):
        for agent in ("codex", "claude"):
            with self.subTest(agent=agent):
                core, adapter = self.make_core(agent, agent + "-interrupted")
                self.start_message(adapter)
                self.delta(adapter, SAFE_LINE + TOKEN_PREFIX)
                self.assertIn(TOKEN_PREFIX, core._streams[agent]["text"])
                self.assert_safe_surfaces(core)
                self.delta(adapter, TOKEN_SUFFIX + "\n")
                self.assertEqual(core._streams[agent]["text"], SAFE_LINE + SYNTHETIC_TOKEN + "\n")
                self.assertEqual(core.messages(agent=agent)[-1]["content"], SAFE_LINE + "[REDACTED]\n")
                self.assert_safe_surfaces(core)
                core.close()
                restored = WorkspaceCore(core.data_dir)
                self.cores.append(restored)
                saved = restored.messages(agent=agent)[-1]
                self.assertEqual(saved["status"], "interrupted")
                self.assertEqual(saved["content"], SAFE_LINE + "[REDACTED]\n")
                self.assert_safe_surfaces(restored)

    def test_unterminated_secret_line_is_never_written_before_restart(self):
        for agent in ("codex", "claude"):
            with self.subTest(agent=agent):
                core, adapter = self.make_core(agent, agent + "-unterminated")
                self.start_message(adapter)
                self.delta(adapter, SAFE_LINE + "sk-")
                self.delta(adapter, "proj-ABCDEFGH")
                self.delta(adapter, TOKEN_SUFFIX)
                self.assertEqual(core.messages(agent=agent)[-1]["content"], SAFE_LINE)
                queued = self.assert_safe_surfaces(core)
                self.assertEqual([e for e in queued if e["type"] == "message_delta"][-1]["full_content"],
                                 SAFE_LINE + "[REDACTED]")
                core.close()
                restored = WorkspaceCore(core.data_dir)
                self.cores.append(restored)
                self.assertEqual(restored.messages(agent=agent)[-1]["content"], SAFE_LINE)
                self.assertEqual(restored.messages(agent=agent)[-1]["status"], "interrupted")
                self.assert_safe_surfaces(restored)

    def test_every_credential_split_is_redacted_after_real_handler_completion(self):
        for agent in ("codex", "claude"):
            for split in range(1, len(SYNTHETIC_TOKEN)):
                with self.subTest(agent=agent, split=split):
                    core, adapter = self.make_core(agent, "%s-split-%d" % (agent, split))
                    self.start_message(adapter)
                    self.delta(adapter, SAFE_LINE + SYNTHETIC_TOKEN[:split])
                    self.assert_safe_surfaces(core)
                    self.delta(adapter, SYNTHETIC_TOKEN[split:] + "\nPublic last line")
                    self.assert_safe_surfaces(core)
                    text = SAFE_LINE + SYNTHETIC_TOKEN + "\nPublic last line"
                    self.finish_message(adapter, text)
                    message = core.messages(agent=agent)[-1]
                    self.assertEqual(message["status"], "complete")
                    self.assertEqual(message["content"], sanitize(text))
                    self.assert_safe_surfaces(core)
                    core.close()

    def test_hidden_native_reasoning_and_message_metadata_stay_filtered(self):
        for agent in ("codex", "claude"):
            with self.subTest(agent=agent):
                core, adapter = self.make_core(agent, agent + "-reasoning")
                self.start_message(adapter, message_id=SYNTHETIC_TOKEN)
                if agent == "codex":
                    self.codex_notification(adapter, "item/reasoning/textDelta", delta=PRIVATE_REASONING)
                    self.codex_notification(adapter, "item/completed",
                                            item={"type": "reasoning", "id": "hidden", "text": PRIVATE_REASONING})
                else:
                    adapter._handle({"type": "stream_event", "event": {
                        "type": "content_block_delta", "delta": {
                            "type": "thinking_delta", "thinking": PRIVATE_REASONING,
                            "signature": "PRIVATE_SIGNATURE_CANARY"}}})
                self.delta(adapter, "Visible safe answer\n", message_id=SYNTHETIC_TOKEN)
                self.assertEqual(core._streams[agent]["text"], "Visible safe answer\n")
                queued = self.assert_safe_surfaces(core)
                self.assertNotIn("PRIVATE_SIGNATURE_CANARY", json.dumps(queued))
                delta = next(e for e in queued if e["type"] == "message_delta")
                self.assertEqual(delta.get("item_id", delta.get("backend_message_id", "[REDACTED]")), "[REDACTED]")

    def test_stale_native_terminal_leaves_core_stream_and_ui_busy(self):
        core, adapter = self.make_core("codex", "codex-stale-terminal")
        self.codex_notification(adapter, "turn/started", turn={"id": "A"})
        self.codex_notification(adapter, "turn/completed", turn={"id": "A", "status": "completed"})
        self.start_message(adapter, turn_id="B")
        self.delta(adapter, "Active B answer\n")
        core.drain_events(limit=100000)
        self.codex_notification(adapter, "turn/completed", turn={"id": "A", "status": "failed",
            "error": {"message": "Obsolete failure"}})
        self.assertEqual(adapter.state, "Busy")
        self.assertEqual(adapter._turn_id, "B")
        self.assertFalse(adapter._turn_done.is_set())
        self.assertIn("codex", core._streams)
        self.assertEqual(core.messages(agent="codex")[-1]["status"], "streaming")
        queued = self.assert_safe_surfaces(core)
        self.assertFalse(any(event["type"] in ("error", "state") for event in queued))
        ignored = next(event for event in queued if event["type"] == "event")
        self.assertEqual((ignored["status"], ignored["turn_id"], ignored["active_turn_id"]),
                         ("ignored", "A", "B"))

    def test_only_visible_delta_content_bypasses_adapter_chunk_filter_in_ram(self):
        for adapter_type, emit_name in ((CodexAdapter, "_emit"), (ClaudeAdapter, "_event")):
            with self.subTest(adapter=adapter_type.__name__):
                events = []
                adapter = adapter_type(lambda kind, **payload: events.append((kind, payload)))
                emit = getattr(adapter, emit_name)
                emit("message_delta", content=TOKEN_PREFIX,
                     details={"token": "METADATA_SECRET_CANARY", "thinking": PRIVATE_REASONING},
                     item_id=SYNTHETIC_TOKEN)
                payload = events[-1][1]
                self.assertEqual(payload["content"], TOKEN_PREFIX)
                self.assertEqual(payload["details"]["token"], "[REDACTED]")
                self.assertNotIn(PRIVATE_REASONING, json.dumps(payload))
                self.assertEqual(payload["item_id"], "[REDACTED]")
                emit("message_end", content=SYNTHETIC_TOKEN)
                emit("event", content=SYNTHETIC_TOKEN)
                emit("raw", raw={"text": SYNTHETIC_TOKEN})
                self.assertNotIn(SYNTHETIC_TOKEN, json.dumps(events[1:]))


class CodexTerminalIdentityTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.adapter = CodexAdapter(lambda kind, **payload: self.events.append((kind, payload)))
        self.adapter.session_id = "owned-session"

    def notification(self, method, turn):
        self.adapter._handle_message({"method": method,
            "params": {"threadId": self.adapter.session_id, "turn": turn}})

    def start(self, turn_id):
        self.notification("turn/started", {"id": turn_id})

    def assert_active(self, turn_id):
        self.assertEqual(self.adapter.state, "Busy")
        self.assertEqual(self.adapter._turn_id, turn_id)
        self.assertTrue(self.adapter._turn_started.is_set())
        self.assertFalse(self.adapter._turn_done.is_set())

    def test_late_and_duplicate_terminals_cannot_release_new_active_turn(self):
        self.start("A")
        self.notification("turn/completed", {"id": "A", "status": "completed"})
        self.assertEqual(self.adapter.state, "Connected")
        self.assertTrue(self.adapter._turn_done.is_set())
        self.start("B")
        for _ in range(2):
            self.notification("turn/completed", {"id": "A", "status": "completed"})
            self.assert_active("B")
        self.notification("turn/completed", {"id": "B", "status": "interrupted"})
        self.assertEqual(self.adapter.state, "Connected")
        self.assertEqual(self.adapter._turn_id, "")
        self.assertFalse(self.adapter._turn_started.is_set())
        self.assertTrue(self.adapter._turn_done.is_set())
        self.start("C")
        self.notification("turn/completed", {"id": "B", "status": "interrupted"})
        self.assert_active("C")
        terminals = [payload for kind, payload in self.events
                     if kind == "event" and payload.get("status") in ("completed", "interrupted")]
        self.assertEqual([event["turn_id"] for event in terminals], ["A", "B"])
        ignored = [payload for kind, payload in self.events if kind == "event" and payload.get("status") == "ignored"]
        self.assertEqual([event["turn_id"] for event in ignored], ["A", "A", "B"])
        self.assertEqual(len([1 for kind, payload in self.events if kind == "raw"]), 8)

    def test_stale_error_and_missing_native_identity_do_not_change_active_turn(self):
        self.start("B")
        self.notification("turn/completed", {"id": "A", "status": "failed",
            "error": {"message": "Old error password=IGNORED_ERROR_CANARY"}})
        self.assert_active("B")
        self.assertEqual(self.adapter.last_error, "")
        self.notification("turn/completed", {"status": "completed"})
        self.assert_active("B")
        self.assertFalse(any(kind == "error" for kind, payload in self.events))
        self.assertNotIn("IGNORED_ERROR_CANARY", json.dumps(self.events))

    def test_terminal_without_active_identity_is_audited_without_becoming_connected(self):
        self.adapter.state = "Disconnected"
        self.notification("turn/completed", {"id": "old", "status": "completed"})
        self.assertEqual(self.adapter.state, "Disconnected")
        self.assertTrue(any(kind == "raw" for kind, payload in self.events))
        self.assertTrue(any(kind == "event" and payload.get("status") == "ignored"
                            for kind, payload in self.events))

    def test_matching_terminal_keeps_non_id_adapter_fixture_fields_optional(self):
        # Native turn identity remains mandatory; threadId and unrelated metadata
        # are absent in older in-memory fixtures and need not disable matching.
        self.adapter._turn_id = "active"
        self.adapter.state = "Busy"
        self.adapter._turn_done.clear()
        self.adapter._handle_message({"method": "turn/completed",
            "params": {"turn": {"id": "active", "status": "completed"}}})
        self.assertEqual(self.adapter.state, "Connected")
        self.assertEqual(self.adapter._turn_id, "")
        self.assertTrue(self.adapter._turn_done.is_set())


if __name__ == "__main__":
    unittest.main()
