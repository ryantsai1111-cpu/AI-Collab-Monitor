"""Protocol unit tests use an explicitly labelled transport substitute.

Real backend acceptance is opt-in: ACW_CODEX_LIVE=1 python -m unittest
tests.test_codex.CodexLiveTests. It creates ONLY a new isolated test session.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from acw.adapters.codex import CodexAdapter


class ProtocolTestAdapter(CodexAdapter):
    """Test-only in-memory transport; never used by the application."""
    def __init__(self):
        self.events, self.requests, self.writes = [], [], []
        super().__init__(lambda kind, **data: self.events.append((kind, data)))
        self.responses = {}
        self.state = "Connected"

    def _request(self, method, params=None, timeout=None):
        self.requests.append((method, params))
        return self.responses.get(method, {})

    def _write(self, message):
        self.writes.append(message)


class CodexProtocolTests(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolTestAdapter()

    def test_structured_stderr_excludes_hidden_reasoning_and_secret_before_tail_or_event(self):
        import io
        from types import SimpleNamespace
        original={'level':'INFO','fields':{'payload':{'type':'reasoning','text':'DIAGNOSTIC_PRIVATE_CANARY'},'token':'DIAGNOSTIC_TOKEN_CANARY','message':'PUBLIC_DIAGNOSTIC'}}
        self.a._process=SimpleNamespace(stderr=io.StringIO(json.dumps(original)+'\n'))
        self.a._read_stderr()
        serialized=json.dumps({'tail':self.a._stderr_tail,'events':self.a.events})
        self.assertNotIn('DIAGNOSTIC_PRIVATE_CANARY',serialized)
        self.assertNotIn('DIAGNOSTIC_TOKEN_CANARY',serialized)
        self.assertIn('PUBLIC_DIAGNOSTIC',serialized)
        self.assertIn('hidden reasoning excluded',serialized)
        self.assertIn('Secret or hidden-reasoning filtering applied',serialized)
        self.assertEqual(original['fields']['payload']['text'],'DIAGNOSTIC_PRIVATE_CANARY')

    def test_plain_stderr_redacts_secret_and_preserves_public_error(self):
        import io
        from types import SimpleNamespace
        self.a._process=SimpleNamespace(stderr=io.StringIO('Sandbox setup failed password=PLAIN_DIAGNOSTIC_CANARY\n'))
        self.a._read_stderr()
        serialized=json.dumps({'tail':self.a._stderr_tail,'events':self.a.events})
        self.assertNotIn('PLAIN_DIAGNOSTIC_CANARY',serialized)
        self.assertIn('Sandbox setup failed',serialized)

    def test_attachment_policy_uses_selected_model_actual_input_modalities(self):
        self.a._model_records=[{'id':'image-fixture','model':'image-fixture','isDefault':True,'inputModalities':['text','image']},{'id':'text-fixture','model':'text-fixture','inputModalities':['text']}]
        self.assertTrue(self.a.attachment_capability()['supported'])
        self.assertTrue(self.a.attachment_capability('image-fixture')['supported'])
        self.assertEqual(self.a.attachment_capability('image-fixture')['extensions'],['.png','.jpg','.jpeg','.webp','.gif'])
        self.assertFalse(self.a.attachment_capability('text-fixture')['supported'])
        self.assertFalse(self.a.attachment_capability('unadvertised-fixture')['supported'])

    def test_models_efforts_come_only_from_backend_catalog(self):
        self.a.responses["model/list"] = {"data": [
            {"id": "catalog-id", "model": "backend-model", "isDefault": True, "inputModalities": ["text"], "supportedReasoningEfforts": [{"reasoningEffort": "minimal"}]},
            {"id": "hidden", "model": "hidden", "hidden": True}]}
        self.a._discover_models()
        self.assertEqual(self.a.list_models(), ["backend-model"])
        self.assertEqual(self.a.list_efforts(), ["minimal"])
        self.assertEqual(self.a.list_efforts("invented-model"), [])
        self.assertFalse(self.a.capabilities.supports_files)

    def test_approval_is_pending_until_explicit_user_decision(self):
        self.a._handle_message({"id": 42, "method": "item/commandExecution/requestApproval", "params": {"command": "example", "availableDecisions": ["accept", "decline"]}})
        self.assertEqual(self.a.writes, [])
        self.assertTrue(any(e[0] == "approval" for e in self.a.events))
        self.a.approve("0:42", True)
        self.assertEqual(self.a.writes, [{"id": 42, "result": {"decision": "accept"}}])
        with self.assertRaises(ValueError):
            self.a.approve("0:42", True)

    def test_permission_denial_grants_nothing(self):
        self.a._handle_message({"id": 9, "method": "item/permissions/requestApproval", "params": {"permissions": {"network": {"enabled": True}}}})
        self.a.approve("0:9", False)
        self.assertEqual(self.a.writes[-1]["result"], {"permissions": {}, "scope": "turn"})

    def test_unknown_server_callback_does_not_extract_credentials(self):
        self.a._handle_message({"id": 10, "method": "account/chatgptAuthTokens/refresh", "params": {}})
        self.assertIn("error", self.a.writes[-1])

    def test_stop_uses_turn_interrupt_only(self):
        self.a.session_id, self.a._turn_id = "owned-thread", "owned-turn"
        self.a.stop()
        self.assertEqual(self.a.requests, [("turn/interrupt", {"threadId": "owned-thread", "turnId": "owned-turn"})])

    def test_immediate_stop_waits_for_backend_turn_started(self):
        self.a.session_id, self.a._turn_id, self.a.state = "owned-thread", "queued-turn", "Busy"
        self.a._turn_done.clear()
        timer = threading.Timer(0.02, lambda: self.a._handle_message({"method": "turn/started", "params": {"threadId": "owned-thread", "turn": {"id": "queued-turn"}}}))
        timer.start()
        try:
            self.assertTrue(self.a.stop())
            self.assertTrue(self.a._turn_started.is_set())
            self.assertEqual(self.a.requests, [("turn/interrupt", {"threadId": "owned-thread", "turnId": "queued-turn"})])
        finally:
            timer.join()

    def test_reasoning_and_secrets_do_not_reach_callbacks(self):
        self.a._handle_message({"method": "item/reasoning/textDelta", "params": {"delta": "private-deliberation"}})
        self.a._handle_message({"method": "item/completed", "params": {"item": {"type": "reasoning", "content": ["private-deliberation"]}}})
        self.a._handle_message({"method": "codex/event/reasoning", "params": {"msg": {"type": "agent_reasoning", "text": "private-deliberation"}}})
        self.a._handle_message({"method": "warning", "params": {"message": "password=synthetic-test-secret"}})
        rendered = json.dumps(self.a.events)
        self.assertNotIn("private-deliberation", rendered)
        self.assertNotIn("synthetic-test-secret", rendered)
        self.assertIn("REDACTED", rendered)

    def test_command_preserves_combined_stream_and_exit_status(self):
        self.a._handle_item({"id": "cmd1", "type": "commandExecution", "command": "python -m pytest", "cwd": "fixture", "status": "completed", "aggregatedOutput": "2 passed, 1 skipped", "exitCode": 0, "durationMs": 300}, True)
        command = next(data for kind, data in self.a.events if kind == "command")
        self.assertEqual(command["output_stream"], "combined")
        self.assertEqual(command["stdout"], "")
        self.assertEqual(command["stderr"], "")
        self.assertEqual(command["exit_code"], 0)
        test = next(data for kind, data in self.a.events if kind == "test")
        self.assertEqual(test["passed"], 2)
        self.assertEqual(test["skipped"], 1)
        self.assertIsNone(test["failed"])

    def test_unittest_counts_from_complete_runner_summary(self):
        result = self.a._test_summary("python -B -m unittest", "..s\nRan 3 tests in 0.001s\n\nOK (skipped=1)\n")
        self.assertEqual((result["passed"], result["failed"], result["skipped"]), (2, 0, 1))

    def test_project_change_does_not_carry_old_session(self):
        with tempfile.TemporaryDirectory() as left, tempfile.TemporaryDirectory() as right:
            self.a.set_project(left)
            self.a.session_id = "previous-session"
            self.a._session_ready = True
            self.a.set_project(right)
            self.assertEqual(self.a.session_id, "")
            self.assertFalse(self.a._session_ready)

    def test_busy_project_change_is_rejected(self):
        self.a.state = "Busy"
        with self.assertRaises(RuntimeError):
            self.a.set_project(tempfile.gettempdir())

    def test_resume_cannot_cross_project_boundary(self):
        with tempfile.TemporaryDirectory() as left, tempfile.TemporaryDirectory() as right:
            self.a.set_project(left)
            self.a.responses["thread/read"] = {"thread": {"id": "test", "cwd": right}}
            with self.assertRaises(ValueError):
                self.a.resume_session("test")
            self.assertNotIn("thread/resume", [r[0] for r in self.a.requests])

    def test_reconnect_does_not_silently_resume_saved_session(self):
        self.a.session_id = "stored-session"
        with self.assertRaises(RuntimeError):
            self.a.send_message("hello")
        self.assertEqual(self.a.requests, [])

    def test_returned_full_access_sandbox_allows_turn(self):
        self.a.session_id, self.a._session_ready = "test", True
        self.a._permission_state = {"sandbox": {"type": "dangerFullAccess"}}
        self.a.responses["turn/start"] = {"turn": {"id": "approved-turn"}}
        self.assertEqual("approved-turn", self.a.send_message("hello"))
        self.assertEqual(self.a.requests[0][0], "turn/start")

    def test_unknown_inherited_sandbox_blocks_turn(self):
        self.a.session_id, self.a._session_ready = "test", True
        with self.assertRaises(PermissionError):
            self.a.send_message("hello")
        self.assertEqual(self.a.requests, [])

    def test_timed_out_turn_cannot_be_silently_resent(self):
        self.a.session_id, self.a._session_ready = "test", True
        self.a._permission_state = {"sandbox": {"type": "readOnly"}}
        def timeout(*args, **kwargs):
            raise TimeoutError("acknowledgment timeout")
        self.a._request = timeout
        with self.assertRaises(TimeoutError):
            self.a.send_message("hello")
        self.assertEqual(self.a.state, "Busy")
        self.assertFalse(self.a._turn_done.is_set())
        with self.assertRaises(RuntimeError):
            self.a.send_message("hello")

    def test_disconnect_invalidates_pending_approvals(self):
        self.a._handle_message({"id": 42, "method": "item/fileChange/requestApproval", "params": {}})
        self.a.disconnect()
        with self.assertRaises(ValueError):
            self.a.approve("0:42", True)

    def test_stream_delta_precedes_completion(self):
        self.a._handle_message({"method": "item/agentMessage/delta", "params": {"itemId": "m", "delta": "hello "}})
        self.a._handle_message({"method": "item/completed", "params": {"item": {"id": "m", "type": "agentMessage", "text": "hello world"}}})
        messages = [kind for kind, _ in self.a.events if kind.startswith("message_")]
        self.assertEqual(messages, ["message_start", "message_delta", "message_end"])

    def test_interrupted_turn_returns_connected_without_resend(self):
        self.a.session_id, self.a._turn_id = "test", "turn"
        self.a._handle_message({"method": "turn/completed", "params": {"threadId": "test", "turn": {"id": "turn", "status": "interrupted"}}})
        self.assertEqual(self.a.state, "Connected")
        self.assertEqual(self.a._turn_id, "")
        self.assertEqual(self.a.requests, [])


@unittest.skipUnless(os.environ.get("ACW_CODEX_LIVE") == "1", "Real CLI test requires explicit ACW_CODEX_LIVE=1")
class CodexLiveTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("ACW_CODEX_TOOLS") == "1", "Real command test requires explicit ACW_CODEX_TOOLS=1")
    def test_real_tools_command_and_test_output(self):
        root = Path(__file__).resolve().parent.parent
        sandbox = root / "tests" / "sandbox-codex"
        sandbox.mkdir(parents=True, exist_ok=True)
        fixture = sandbox / "test_acw_fixture.py"
        fixture.write_text("import unittest\nclass Fixture(unittest.TestCase):\n    def test_sum(self): self.assertEqual(2 + 2, 4)\n    def test_string(self): self.assertEqual('acw'.upper(), 'ACW')\n    @unittest.skip('deliberate fixture skip')\n    def test_skipped(self): pass\n", encoding="utf-8")
        events, approval_seen = [], threading.Event()
        def emit(kind, **data):
            events.append((kind, data))
            if kind == "approval":
                approval_seen.set()
        executable = os.environ.get("ACW_CODEX_EXECUTABLE", r"C:\Users\ryant\AppData\Local\OpenAI\Codex\bin\8aaf1547b825b104\codex.exe")
        adapter = CodexAdapter(emit, executable, timeout=45)
        evidence = {"backend": "official app-server", "fixture": str(sandbox), "checks": {}, "errors": []}
        try:
            adapter.set_project(str(sandbox))
            adapter.connect()
            evidence["session"] = adapter.create_session()
            evidence["permissions"] = adapter.diagnostics()["permissions"]
            prompt = ("This is an authorized harmless acceptance test in the isolated repository " + str(sandbox) + ". "
                      "Use your native shell tool for exactly these two read-only checks. Do not read unrelated files, credentials or invoke network or install software. "
                      "Use PowerShell commands with this existing Python executable: " + sys.executable + ". "
                      "First run: & '" + sys.executable + "' -B -c \"import sys; print('ACW_STDOUT'); sys.stderr.write('ACW_STDERR\\n'); sys.exit(7)\". "
                      "Exit code 7 is intentional. Then run: & '" + sys.executable + "' -B -m unittest -v test_acw_fixture.py. "
                      "The fixture has two passing tests and one deliberate skip. Do not modify any file. Briefly report results normally.")
            adapter.send_message(prompt)
            deadline = time.monotonic() + 120
            while not adapter._turn_done.wait(0.1) and time.monotonic() < deadline and not approval_seen.is_set():
                pass
            if approval_seen.is_set():
                evidence["blocked"] = "Native backend requested approval; it was not approved automatically"
                adapter.stop()
                adapter._turn_done.wait(15)
            elif not adapter._turn_done.is_set():
                evidence["blocked"] = "120-second time limit; cancelled through official interrupt"
                adapter.stop()
                adapter._turn_done.wait(15)
            commands = [data for kind, data in events if kind == "command" and data.get("completed")]
            tests = [data for kind, data in events if kind == "test"]
            evidence["commands"], evidence["tests"] = commands, tests
            evidence["checks"]["command"] = bool(commands)
            evidence["checks"]["combined_stdout_stderr"] = any("ACW_STDOUT" in c.get("output", "") and "ACW_STDERR" in c.get("output", "") for c in commands)
            # PowerShell -Command normalizes a native nonzero exit to 1 unless
            # explicitly forwarded. Assert the reported shell exit, not Python's.
            evidence["checks"]["nonzero_exit"] = any(isinstance(c.get("exit_code"), int) and c["exit_code"] != 0 and "ACW_STDOUT" in c.get("output", "") for c in commands)
            evidence["checks"]["zero_exit"] = any(c.get("exit_code") == 0 and "unittest" in c.get("command", "") for c in commands)
            evidence["checks"]["test_counts"] = any((t.get("passed"), t.get("failed"), t.get("skipped")) == (2, 0, 1) for t in tests)
            self.assertTrue(all(evidence["checks"].values()), evidence.get("blocked", evidence["checks"]))
        except Exception as exc:
            evidence["errors"].append(str(exc))
            raise
        finally:
            try:
                adapter.disconnect()
            except Exception as exc:
                evidence["errors"].append("disconnect: " + str(exc))
            evidence["approvals"] = [data for kind, data in events if kind == "approval"]
            evidence["backend_errors"] = [data.get("content") for kind, data in events if kind == "error"]
            evidence["event_counts"] = {kind: sum(1 for k, _ in events if k == kind) for kind in sorted({k for k, _ in events})}
            (root / "evidence" / "codex-live-tools.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")

    def test_real_handshake_session_message_stream_resume_and_interrupt(self):
        root = Path(__file__).resolve().parent.parent
        sandbox = root / "tests" / "sandbox-codex"
        sandbox.mkdir(parents=True, exist_ok=True)
        git = shutil.which("git") or r"C:\Program Files\Git\cmd\git.exe"
        subprocess.run([git, "-C", str(sandbox), "init", "--quiet"], check=True, capture_output=True)
        events = []
        executable = os.environ.get("ACW_CODEX_EXECUTABLE", r"C:\Users\ryant\AppData\Local\OpenAI\Codex\bin\8aaf1547b825b104\codex.exe")
        adapter = CodexAdapter(lambda kind, **data: events.append((kind, data)), executable, timeout=45)
        evidence = {"backend": "official app-server", "fixture": str(sandbox), "checks": {}, "errors": []}
        try:
            adapter.set_project(str(sandbox))
            adapter.connect()
            evidence["checks"]["handshake"] = adapter.state == "Connected"
            evidence["version"] = adapter.version
            evidence["models"] = adapter.list_models()
            evidence["efforts"] = {m: adapter.list_efforts(m) for m in adapter.list_models()}
            sid = adapter.create_session()
            evidence["session"] = sid
            evidence["permissions"] = adapter.diagnostics()["permissions"]
            evidence["checks"]["session"] = bool(sid)
            evidence["checks"]["cwd"] = Path(adapter._session_cwd).resolve() == sandbox.resolve()
            selected = next(r for r in adapter._model_records if r.get("isDefault"))
            model = selected["model"]
            effort = selected.get("defaultReasoningEffort")
            evidence["selected_model"], evidence["selected_effort"] = model, effort
            adapter.send_message("This is a harmless isolated Workspace acceptance check. Do not use tools or read files. Reply with exactly ACW_CODEX_OK.", model=model, effort=effort)
            self.assertTrue(adapter._turn_done.wait(120), "Message did not complete")
            evidence["checks"]["streaming"] = any(kind == "message_delta" for kind, _ in events)
            evidence["checks"]["response"] = any(kind == "message_end" and "ACW_CODEX_OK" in data.get("content", "") for kind, data in events)
            evidence["checks"]["history"] = bool(adapter.get_history())
            evidence["checks"]["list_sessions"] = any(t.get("id") == sid for t in adapter.list_sessions())
            adapter.disconnect()
            adapter.connect()
            evidence["checks"]["reconnect_requires_resume"] = not adapter._session_ready and adapter.session_id == sid
            evidence["checks"]["resume"] = adapter.resume_session(sid) == sid
            adapter.send_message("This is a cancellation check. Do not use tools or read files. Generate a long numbered list of ordinary colors and shapes, at least 500 entries.")
            evidence["checks"]["interrupt_requested"] = adapter.stop()
            self.assertTrue(adapter._turn_done.wait(45), "Cancellation was not confirmed")
            evidence["checks"]["interrupted"] = any(kind == "event" and data.get("status") == "interrupted" for kind, data in events)
            self.assertTrue(all(evidence["checks"].values()), evidence["checks"])
        except Exception as exc:
            evidence["errors"].append(str(exc))
            raise
        finally:
            try:
                adapter.disconnect()
            except Exception as exc:
                evidence["errors"].append("disconnect: " + str(exc))
            evidence["event_counts"] = {kind: sum(1 for k, _ in events if k == kind) for kind in sorted({k for k, _ in events})}
            evidence["backend_errors"] = [data.get("content") for kind, data in events if kind == "error"]
            evidence["terminal_events"] = [data for kind, data in events if kind == "event" and data.get("status") in ("interrupted", "completed", "failed")]
            (root / "evidence" / "codex-live-acceptance.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
