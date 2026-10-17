"""Official Codex app-server stdio adapter, verified against CLI 0.160.0.

No credential reads, shell text scraping, permission bypass, process-tree kill,
or automatic approval. Persistence is owned by Workspace Core. Public protocol:
https://learn.chatgpt.com/docs/app-server
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import threading
import time

from .base import Adapter, Capabilities
from ..security import sanitize, safe_file


class _CancellationOwnershipChanged(RuntimeError):
    pass


class CodexAdapter(Adapter):
    agent = "codex"

    def __init__(self, emit, executable="", **settings):
        super().__init__(emit, executable, **settings)
        self._auto_executable = None
        self._process = None
        self._pending = {}
        self._private_request_ids = set()
        self._approvals = {}
        self._write_lock = threading.Lock()
        self._lock = threading.RLock()
        self._next_id = 0
        self._generation = 0
        self._closing = False
        self._reader = None
        self._stderr_reader = None
        self._model_records = []
        self._native_sessions = {}
        self._items = {}
        self._started_messages = set()
        self._completed_turns = set()
        self._turn_id = ""
        self._send_sequence = 0
        self._accepted_operation = None
        self._turn_started = threading.Event()
        self._turn_done = threading.Event()
        self._turn_done.set()
        self._session_cwd = ""
        self._session_ready = False
        self._permission_state = {}
        self.last_event = ""
        self._stderr_tail = []

    def _emit(self, kind, **payload):
        clean = sanitize(payload)
        if kind == "message_delta" and isinstance(payload.get("content"), str):
            # This callback feeds Core's in-memory whole-message accumulator.
            # Filtering a chunk here destroys credential prefixes needed to
            # redact a later chunk. Core sanitizes the accumulated message
            # before queuing it or persisting any text; raw audits stay filtered.
            clean["content"] = payload["content"]
        self.emit(kind, **clean)

    def _error(self, error):
        self.last_error = sanitize(str(error))
        self._emit("error", content=self.last_error)

    def _write(self, message, *, expected_operation=None, dispatch_guard=None):
        # The final ownership/gate check and packet write share this lock.
        with self._lock, self._write_lock:
            if expected_operation is not None and self.active_operation_id() != expected_operation:
                raise _CancellationOwnershipChanged("Codex operation changed before interrupt dispatch")
            if not self._process or self._process.poll() is not None:
                raise ConnectionError("Codex app-server is disconnected")
            if dispatch_guard: dispatch_guard(final=True)
            self._process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
            self._process.stdin.flush()

    def _request(self, method, params=None, timeout=None, *, suppress_raw=False, expected_operation=None, dispatch_guard=None):
        with self._lock:
            self._next_id += 1
            request_id = self._next_id
            response = queue.Queue(maxsize=1)
            self._pending[request_id] = response
            if suppress_raw:
                self._private_request_ids.add(request_id)
        try:
            options = {}
            if expected_operation is not None: options["expected_operation"] = expected_operation
            if dispatch_guard is not None: options["dispatch_guard"] = dispatch_guard
            self._write({"id": request_id, "method": method, "params": params or {}}, **options)
            try:
                result = response.get(timeout=float(timeout or self.settings.get("timeout", 45)))
            except queue.Empty:
                raise TimeoutError(f"Codex {method} timed out; the request was not retried") from None
            if "error" in result:
                raise RuntimeError(json.dumps(sanitize(result["error"]), ensure_ascii=False))
            return result.get("result", {})
        finally:
            with self._lock:
                self._pending.pop(request_id, None)

    def _read_loop(self):
        try:
            for line in self._process.stdout:
                try:
                    message = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    self._error("Codex app-server produced a non-JSON protocol line: " + line[:1000])
                    continue
                try:
                    self._handle_message(message)
                except Exception as exc:
                    self._error(f"Codex event handling: {exc}")
        finally:
            self._session_ready = False
            self._turn_done.set()
            with self._lock:
                for response in self._pending.values():
                    try:
                        response.put_nowait({"error": {"message": "Codex app-server disconnected"}})
                    except queue.Full:
                        pass
            if not self._closing:
                self.set_state("Disconnected")
                self._error("Codex app-server disconnected" + (": " + self._stderr_tail[-1] if self._stderr_tail else ""))

    def _read_stderr(self):
        for line in self._process.stderr:
            original = line.rstrip()
            try:
                diagnostic = json.loads(original)
            except (ValueError, TypeError):
                diagnostic = original
            filtered = sanitize(diagnostic)
            clean = json.dumps(filtered, ensure_ascii=False) if not isinstance(diagnostic, str) else filtered
            self._stderr_tail.append(clean)
            self._stderr_tail = self._stderr_tail[-20:]
            fields = {"summary": clean, "source": "app-server stderr"}
            if diagnostic != filtered:
                fields["redaction"] = "Secret or hidden-reasoning filtering applied to diagnostic"
            self._emit("event", **fields)

    @staticmethod
    def _public_event(message):
        """Omit all reasoning notifications, including legacy codex/event variants."""
        method = str(message.get("method", ""))
        params = message.get("params") or {}
        if "reasoning" in method.lower() or "thinking" in method.lower():
            return {"method": method, "redaction": "hidden reasoning excluded"}
        legacy = params.get("msg", {})
        if isinstance(legacy, dict) and any(x in str(legacy.get("type", "")).lower() for x in ("reasoning", "thinking")):
            return {"method": method, "redaction": "hidden reasoning excluded"}
        return sanitize(message)

    def _handle_message(self, message):
        if "id" in message and "method" not in message:
            with self._lock:
                private_response = message["id"] in self._private_request_ids
                if private_response:
                    self._private_request_ids.discard(message["id"])
                private_waiter = self._pending.get(message["id"]) if private_response else None
            if private_response:
                # A preview is intentionally absent from the active task's raw log.
                # Keep the suppression ID until a response arrives, even on timeout.
                self._emit("raw", raw={"id": message["id"], "redaction": "Explicit native-history preview response omitted; no transcript persisted"})
                if private_waiter:
                    try:
                        private_waiter.put_nowait(message)
                    except queue.Full:
                        pass
                return
        public = self._public_event(message)
        self._emit("raw", raw=public)
        if "id" in message and "method" not in message:
            with self._lock:
                response = self._pending.get(message["id"])
            if response:
                try:
                    response.put_nowait(message)
                except queue.Full:
                    pass
            return
        method = message.get("method", "")
        self.last_event = method
        params = message.get("params") or {}
        if "id" in message:
            self._handle_server_request(message)
            return
        if public.get("redaction") == "hidden reasoning excluded":
            return
        # Legacy notifications duplicate v2 events; retain their safe raw form only.
        if method.startswith("codex/event/"):
            return
        if params.get("threadId") and self.session_id and params["threadId"] != self.session_id:
            return
        if method in ("turn/started", "turn/completed"):
            with self._lock:
                if method == "turn/started":
                    incoming = params["turn"]["id"]
                    if self._accepted_operation is not None and incoming != self._accepted_operation[3]:
                        self._accepted_operation = None
                    self._turn_id = incoming
                    self._turn_started.set()
                    self._turn_done.clear()
                    self.set_state("Busy")
                elif method == "turn/completed":
                    turn = params["turn"]
                    turn_id = turn.get("id", "")
                    if not turn_id or turn_id != self._turn_id:
                        # A duplicate/late terminal must never release a newer turn.
                        # The sanitized raw notification above remains in the audit.
                        self._emit("event", summary="Ignored stale turn completion",
                                   status="ignored", turn_id=turn_id,
                                   active_turn_id=self._turn_id)
                        return
                    self._completed_turns.add(turn_id)
                    if turn.get("error"):
                        self._error(turn["error"])
                    self._accepted_operation = None
                    self._turn_id = ""
                    self._turn_started.clear()
                    self._turn_done.set()
                    self._emit("event", summary="Turn " + turn.get("status", "completed"), status=turn.get("status"), turn_id=turn_id)
                    self.set_state("Connected")
            return
        if method in ("item/started", "item/completed"):
            self._handle_item(params.get("item", {}), method == "item/completed")
        elif method == "item/agentMessage/delta":
            item_id = params.get("itemId", "")
            if item_id not in self._started_messages:
                self._started_messages.add(item_id)
                self._emit("message_start", content="", item_id=item_id)
            self._emit("message_delta", content=params.get("delta", ""), item_id=item_id)
        elif method == "item/commandExecution/outputDelta":
            self._emit("event", summary=params.get("delta", ""), item_id=params.get("itemId"), event_type="command_output", output_stream="combined")
        elif method == "turn/diff/updated":
            self._emit("diff", content=params.get("diff", ""), diff=params.get("diff", ""), turn_id=params.get("turnId"))
        elif method == "serverRequest/resolved":
            self._approvals.pop(f"{self._generation}:{params.get('requestId')}", None)
        elif method == "error":
            self._error(params.get("error", params))
        elif method in ("warning", "configWarning"):
            self._emit("event", summary=params.get("message", params.get("summary", str(params))), status="warning")

    def _handle_item(self, item, completed):
        kind, item_id = item.get("type"), item.get("id", "")
        if kind == "reasoning":
            return
        status = item.get("status", "completed" if completed else "inProgress")
        if not completed:
            self._items[item_id] = {"started": time.time()}
        started = self._items.get(item_id, {}).get("started")
        duration = item.get("durationMs")
        common = dict(item_id=item_id, status=status, started=started,
                      completed=time.time() if completed else None, duration_ms=duration)
        if kind == "agentMessage":
            if completed:
                self._emit("message_end", content=item.get("text", ""), phase=item.get("phase"), **common)
                self._started_messages.discard(item_id)
            else:
                self._started_messages.add(item_id)
                self._emit("message_start", content="", **common)
        elif kind == "commandExecution":
            output = item.get("aggregatedOutput") or ""
            self._emit("command", command=item.get("command", ""), cwd=item.get("cwd", self.cwd),
                       stdout="", stderr="", output=output, output_stream="combined",
                       exit_code=item.get("exitCode"), **common)
            if completed:
                test = self._test_summary(item.get("command", ""), output)
                if test:
                    self._emit("test", **test, exit_code=item.get("exitCode"), duration_ms=duration)
            for action in item.get("commandActions", []):
                if action.get("type") == "read":
                    self._emit("file", path=action.get("path", action.get("name", "")), action="read", **common)
        elif kind == "fileChange":
            for change in item.get("changes", []):
                self._emit("file", path=change.get("path", ""), action=change.get("kind"), **common)
                if change.get("diff"):
                    self._emit("diff", content=change["diff"], diff=change["diff"], path=change.get("path", ""), **common)
        elif kind in ("mcpToolCall", "dynamicToolCall", "collabAgentToolCall", "webSearch", "imageView", "functionCallOutput"):
            self._emit("tool_result" if completed else "tool_start", tool=item.get("tool", item.get("name", kind)),
                       arguments=item.get("arguments", item.get("query", {})),
                       result=item.get("result", item.get("output", item.get("error"))), **common)
        if completed:
            self._items.pop(item_id, None)

    @staticmethod
    def _test_summary(command, output):
        framework = next((name for name in ("pytest", "unittest", "vitest", "jest", "cargo test", "dotnet test", "npm test") if name in command.lower()), None)
        if not framework:
            return None
        counts = {key: None for key in ("passed", "failed", "skipped")}
        for key in counts:
            match = re.search(r"\b(\d+)\s+" + key + r"\b", output, re.I)
            if match:
                counts[key] = int(match.group(1))
        if framework == "unittest":
            ran = re.search(r"Ran (\d+) tests? in ([\d.]+)s", output)
            final = re.search(r"(?m)^(OK|FAILED)(?: \(([^\n]+)\))?\s*$", output)
            if ran and final:
                details = dict((key, int(value)) for key, value in re.findall(r"(failures|errors|skipped)=(\d+)", final.group(2) or ""))
                counts["failed"] = details.get("failures", 0) + details.get("errors", 0)
                counts["skipped"] = details.get("skipped", 0)
                counts["passed"] = max(0, int(ran.group(1)) - counts["failed"] - counts["skipped"])
        return dict(command=command, framework=framework, output=output, **counts)

    def _handle_server_request(self, message):
        method = message["method"]
        params = message.get("params", {})
        supported = ("item/commandExecution/requestApproval", "item/fileChange/requestApproval", "item/permissions/requestApproval")
        if method in supported:
            # Storing this object is in memory only. No approval happens without approve().
            approval_id = f"{self._generation}:{message['id']}"
            self._approvals[approval_id] = message
            self._emit("approval", request_id=approval_id, details={"method": method, **params})
        else:
            # Authentication callbacks, external tools and interactive forms are not guessed.
            self._write({"id": message["id"], "error": {"code": -32601, "message": "Unsupported client request; use the official CLI for this interaction"}})
            self._error("Unsupported Codex client request: " + method)

    def _extra_args(self):
        return []

    def _process_env(self):
        return None

    def _resolve_executable(self):
        """Refresh automatic paths after desktop updates; preserve custom overrides."""
        executable = self.executable if self.executable != self._auto_executable else ""
        local = os.environ.get("LOCALAPPDATA") if os.name == "nt" else None
        root = Path(local) / "OpenAI" / "Codex" / "bin" if local else None
        managed = bool(root and executable and Path(executable).name.lower() == "codex.exe"
                       and Path(executable).parent.parent.resolve() == root.resolve())
        if executable and not managed:
            return executable
        candidates = []
        if root:
            for path in root.glob("*/codex.exe"):
                try:
                    if path.is_file():
                        candidates.append((path.stat().st_mtime, str(path)))
                except OSError:
                    # An updater may remove an older build during discovery.
                    continue
        selected = max(candidates)[1] if candidates else shutil.which("codex") or ""
        self._auto_executable = selected
        return selected

    def connect(self):
        if self._process and self._process.poll() is None and self.state in ("Connected", "Busy"):
            return self.capabilities
        self.set_state("Connecting")
        self._closing = False
        self._generation += 1
        self._approvals.clear()
        self.last_error = ""
        self._session_ready = False
        self.executable = self._resolve_executable()
        if not self.executable:
            self.set_state("Offline")
            raise FileNotFoundError("Official Codex executable not configured")
        try:
            env = self._process_env()
            self._process = subprocess.Popen([self.executable, "app-server", "--listen", "stdio://"] + self._extra_args(),
                cwd=self.cwd or None, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), **({'env': env} if env is not None else {}))
            self._reader = threading.Thread(target=self._read_loop, daemon=True, name="codex-jsonl")
            self._stderr_reader = threading.Thread(target=self._read_stderr, daemon=True, name="codex-stderr")
            self._reader.start()
            self._stderr_reader.start()
            handshake = self._request("initialize", {"clientInfo": {"name": "ai_collaboration_workspace", "title": "AI Collaboration Workspace", "version": "1.0.0"}})
            self.version = handshake.get("userAgent", "")
            self._write({"method": "initialized", "params": {}})
            self._discover_models()
            self.capabilities.supports_sessions = True
            self.capabilities.supports_tools = True
            self.capabilities.supports_project = True
            self.capabilities.supports_cancel = True
            self.capabilities.supports_streaming = True
            self.capabilities.supports_history = True
            self.capabilities.supports_approval = True
            self.capabilities.detail = "Official app-server; image attachments only when listed model supports image input; agent command stdout/stderr are combined; credentials remain with CLI"
            self.set_state("Connected")
            return self.capabilities
        except Exception as exc:
            self._error(exc)
            self.disconnect()
            self.set_state("Error")
            raise

    def _discover_models(self):
        records, cursor = [], None
        while True:
            params = {"limit": 100}
            if cursor:
                params["cursor"] = cursor
            result = self._request("model/list", params)
            records.extend(result.get("data", []))
            cursor = result.get("nextCursor")
            if not cursor:
                break
        self._model_records = [r for r in records if not r.get("hidden")]
        self.capabilities.models = [r.get("model", r["id"]) for r in self._model_records]
        self.capabilities.supports_model_selection = bool(self.capabilities.models)
        self.capabilities.efforts = self.list_efforts()
        self.capabilities.supports_effort = any(r.get("supportedReasoningEfforts") for r in self._model_records)
        self.capabilities.supports_files = any("image" in r.get("inputModalities", []) for r in self._model_records)

    def list_efforts(self, model=None):
        record = next((r for r in self._model_records if r.get("model", r.get("id")) == model), None) if model else next((r for r in self._model_records if r.get("isDefault")), None)
        return [e["reasoningEffort"] for e in (record or {}).get("supportedReasoningEfforts", [])]

    def attachment_capability(self, model=None):
        record = next((r for r in self._model_records if r.get('model',r.get('id')) == model),None) if model else next((r for r in self._model_records if r.get('isDefault')),None)
        supported = 'image' in (record or {}).get('inputModalities',[])
        return {'supported':supported,'kind':'image','extensions':['.png','.jpg','.jpeg','.webp','.gif'] if supported else [],'detail':'Selected Codex model supports image input' if supported else 'Image attachments Unsupported by selected Codex model'}

    def list_sessions(self):
        params = {"limit": 100, "useStateDbOnly": True}
        if self.cwd:
            params["cwd"] = self.cwd
        result = self._request("thread/list", params)
        rows = sanitize(result.get("data", []))
        if self.cwd:
            scope = os.path.normcase(str(Path(self.cwd).resolve()))
            self._native_sessions = {scope: {row["id"] for row in rows
                if row.get("id") and row.get("cwd") and os.path.normcase(str(Path(row["cwd"]).resolve())) == scope}}
        else:
            self._native_sessions.clear()
        return rows

    def _accept_session(self, result):
        thread = result["thread"]
        self.session_id = thread["id"]
        self._session_cwd = result.get("cwd", thread.get("cwd", self.cwd))
        self._permission_state = {k: result.get(k) for k in ("sandbox", "approvalPolicy", "approvalsReviewer")}
        self._session_ready = True
        self._emit("session", session_id=self.session_id, cwd=self._session_cwd, permissions=self._permission_state)
        return self.session_id

    def create_session(self):
        if self.state == "Busy":
            raise RuntimeError("Stop the active turn before creating a session")
        params = {"approvalsReviewer": "user"}
        if self.cwd:
            params["cwd"] = self.cwd
        for setting, field, choices in (
            ("sandbox", "sandbox", ("read-only", "workspace-write", "danger-full-access")),
            ("approval_policy", "approvalPolicy", ("untrusted", "on-request", "never")),
        ):
            value = self.settings.get(setting)
            if value not in (None, "", "inherit"):
                if value not in choices:
                    raise ValueError("Unsupported Codex " + setting + ": " + str(value))
                params[field] = value
        return self._accept_session(self._request("thread/start", params))

    def resume_session(self, session_id):
        if self.state == "Busy":
            raise RuntimeError("Stop the active turn before resuming a session")
        # Read-only cwd validation prevents continuing a session from another project.
        thread = self._request("thread/read", {"threadId": session_id, "includeTurns": False})["thread"]
        if self.cwd and thread.get("cwd") and Path(thread["cwd"]).resolve() != Path(self.cwd).resolve():
            raise ValueError("Session belongs to another project; select its project before resume")
        params = {"threadId": session_id, "approvalsReviewer": "user"}
        for setting, field, choices in (
            ("sandbox", "sandbox", ("read-only", "workspace-write", "danger-full-access")),
            ("approval_policy", "approvalPolicy", ("untrusted", "on-request", "never")),
        ):
            value = self.settings.get(setting)
            if value not in (None, "", "inherit"):
                if value not in choices:
                    raise ValueError("Unsupported Codex " + setting + ": " + str(value))
                params[field] = value
        return self._accept_session(self._request("thread/resume", params))

    def rename_session(self, name):
        return self._request("thread/name/set", {"threadId": self.session_id, "name": name})

    def send_message(self, content, model=None, effort=None, attachments=None, dispatch_guard=None):
        if self.state != "Connected":
            raise RuntimeError("Connect Codex and wait for the active turn before sending")
        if self.session_id and not self._session_ready:
            raise RuntimeError("Explicitly resume the saved session after reconnecting")
        if not self.session_id:
            self.create_session()
        sandbox_type = (self._permission_state.get("sandbox") or {}).get("type")
        if sandbox_type not in ("readOnly", "workspaceWrite", "dangerFullAccess"):
            raise PermissionError("Inherited Codex sandbox is " + str(sandbox_type or "unknown") + "; configure an approved sandbox in the official CLI before using Workspace")
        if model and model not in self.capabilities.models:
            raise ValueError("Model was not advertised by Codex model/list")
        if effort and effort not in self.list_efforts(model):
            raise ValueError("Effort was not advertised for the selected Codex model")
        inputs = [{"type": "text", "text": content}]
        for attachment in attachments or []:
            path = safe_file(attachment, [self.cwd])
            record = next((r for r in self._model_records if r.get("model") == model), None) if model else next((r for r in self._model_records if r.get("isDefault")), None)
            if "image" not in (record or {}).get("inputModalities", []) or path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
                raise ValueError("This model accepts only supported image attachments in the selected project")
            inputs.append({"type": "localImage", "path": str(path)})
        params = {"threadId": self.session_id, "input": inputs}
        if self.cwd:
            params["cwd"] = self.cwd
        if model:
            params["model"] = model
        if effort:
            params["effort"] = effort
        with self._lock:
            if self.state != "Connected":
                raise RuntimeError("Codex operation changed during send preparation")
            if dispatch_guard: dispatch_guard()
            self._send_sequence += 1
            sequence = self._send_sequence
            binding = (self._generation, sequence, self.session_id, id(self._process))
            self._accepted_operation = None
            self._turn_id = ""
            self._turn_done.clear()
            self._turn_started.clear()
            self.set_state("Busy")
        try:
            options = {"dispatch_guard": dispatch_guard} if dispatch_guard is not None else {}
            result = self._request("turn/start", params, **options)
            turn_id = result["turn"]["id"]
            with self._lock:
                current = (self._generation, self._send_sequence, self.session_id, id(self._process))
                if current == binding and turn_id not in self._completed_turns:
                    # An unsolicited replacement turn must not become this send's receipt.
                    if not self._turn_id or self._turn_id == turn_id:
                        self._turn_id = turn_id
                        self._accepted_operation = (binding[0], binding[1], binding[2], turn_id, binding[3])
            return turn_id
        except TimeoutError as exc:
            # A timeout says nothing about whether the server accepted the prompt.
            # Keep Busy until a terminal notification; never resend automatically.
            self._error(exc)
            raise
        except Exception as exc:
            with self._lock:
                current = (self._generation, self._send_sequence, self.session_id, id(self._process))
                if current == binding and not self._turn_id:
                    self._turn_done.set()
                    self.set_state("Connected" if self._process and self._process.poll() is None else "Disconnected")
            self._error(exc)
            raise

    def active_operation_id(self):
        """Opaque RAM-only identity of this send's accepted native turn, if still active."""
        with self._lock:
            token = self._accepted_operation
            if (token is None or self.state != "Busy" or token != self._current_operation_id()):
                return None
            return token

    def _current_operation_id(self):
        return (self._generation, self._send_sequence, self.session_id, self._turn_id, id(self._process))

    def _stop_snapshot(self, expected, *, require_accepted):
        with self._lock:
            current = self.active_operation_id() if require_accepted else self._current_operation_id()
            if expected is None or current != expected:
                return False
            wait = self.state == "Busy" and not self._turn_started.is_set()
            started = self._turn_started
            thread_id, turn_id = expected[2], expected[3]
        if wait:
            started.wait(10)
        with self._lock:
            current = self.active_operation_id() if require_accepted else self._current_operation_id()
            if not require_accepted and not turn_id:
                # Manual Stop can precede acknowledgement, but cannot follow a new local send.
                if current[:3] != expected[:3] or current[4] != expected[4]:
                    return False
                turn_id = current[3]
            elif current != expected:
                return False
            if self.state == "Busy" and not self._turn_started.is_set() and not self._turn_done.is_set():
                raise TimeoutError("Codex has not announced turn/started; cancellation is pending, retry Stop")
            if not turn_id:
                if self.state == "Busy":
                    raise RuntimeError("Turn has not been acknowledged yet; retry Stop after the turn starts")
                return False
        try:
            options = {"expected_operation": expected} if require_accepted else {}
            self._request("turn/interrupt", {"threadId": thread_id, "turnId": turn_id}, **options)
        except _CancellationOwnershipChanged:
            return False
        self._emit("event", summary="Cancellation requested through turn/interrupt", status="cancelling")
        return True

    def stop_if_owned(self, expected):
        """Never interrupt a replacement native turn after waiting for turn/started."""
        return self._stop_snapshot(expected, require_accepted=True)

    def stop(self):
        # Explicit manual Stop targets a snapshot of the current native operation.
        with self._lock:
            expected = self._current_operation_id()
        return self._stop_snapshot(expected, require_accepted=False)

    def set_project(self, path, metadata=None):
        if self.state == "Busy":
            raise RuntimeError("Stop the active Codex turn before changing project")
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_dir():
            raise ValueError("Codex project must be an existing directory")
        if self.cwd and Path(self.cwd).resolve() != resolved:
            self.session_id = ""
            self._session_ready = False
            self._session_cwd = ""
            self._native_sessions.clear()
        self.cwd = str(resolved)

    def native_history_capability(self):
        scope = os.path.normcase(str(Path(self.cwd).resolve())) if self.cwd else ""
        available = self.state in ("Connected", "Busy") and bool(self._native_sessions.get(scope))
        return {"supported": True, "available": available, "read_only": True,
                "reason": "Official thread/read preview; explicitly discover sessions in the current project first. Preview is not persisted or resumed."}

    def get_history(self, session_id=None, *, native=False, limit=200, offset=0):
        if native:
            return self.get_native_history(session_id, limit=limit, offset=offset)
        target = session_id or self.session_id
        if not target:
            return []
        result = self._request("thread/read", {"threadId": target, "includeTurns": True})
        return sanitize(result["thread"].get("turns", []))

    def get_native_history(self, session_id, *, limit=200, offset=0):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("Native history limit must be between 1 and 500")
        if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 10000:
            raise ValueError("Native history offset must be between 0 and 10000")
        if not session_id or not self.cwd or self.state not in ("Connected", "Busy"):
            raise PermissionError("Connect and explicitly discover sessions in the current project before native preview")
        scope = os.path.normcase(str(Path(self.cwd).resolve()))
        if session_id not in self._native_sessions.get(scope, set()):
            raise PermissionError("Native preview requires a session explicitly discovered in this project")
        def verify_thread(thread):
            if thread.get("id") != session_id or not thread.get("cwd"):
                raise PermissionError("Backend returned different or incomplete session metadata")
            if os.path.normcase(str(Path(thread["cwd"]).resolve())) != scope:
                raise PermissionError("Native session belongs to a different project")
            if os.path.normcase(str(Path(self.cwd).resolve())) != scope:
                raise PermissionError("Project changed during native history preview")
        metadata = self._request("thread/read", {"threadId": session_id, "includeTurns": False}, suppress_raw=True)["thread"]
        verify_thread(metadata)
        thread = self._request("thread/read", {"threadId": session_id, "includeTurns": True}, suppress_raw=True)["thread"]
        verify_thread(thread)
        rows = []
        for turn in thread.get("turns", []):
            for item in turn.get("items", []):
                kind = item.get("type")
                if kind not in ("userMessage", "agentMessage"):
                    continue
                content = item.get("text", "") if kind == "agentMessage" else "\n".join(
                    part.get("text", "") for part in item.get("content", []) if part.get("type") == "text")
                rows.append({"id": item.get("id", ""), "session_id": session_id, "agent": self.agent,
                             "role": "assistant" if kind == "agentMessage" else "user", "content": content,
                             "source": "native", "read_only": True})
        return sanitize(rows[offset:offset + limit])

    def approve(self, request_id, approved):
        request = self._approvals.pop(str(request_id), None)
        if request is None:
            raise ValueError("Approval request is no longer pending")
        method, params = request["method"], request.get("params", {})
        if method == "item/permissions/requestApproval":
            result = {"permissions": params.get("permissions", {}) if approved else {}, "scope": "turn"}
        else:
            available = params.get("availableDecisions")
            offered = [item for item in available if isinstance(item, str)] if available else None
            if approved:
                decision = "accept"
            else:
                # A command approval offers "cancel" rather than "decline" (seen 2026-10-17 with
                # ['accept', {'acceptWithExecpolicyAmendment': …}, 'cancel']); either one is the user's "no".
                decision = next((name for name in ("decline", "cancel") if offered is None or name in offered), None)
            if offered is not None and decision not in offered:
                self._approvals[str(request_id)] = request
                raise ValueError("Backend does not offer this one-time decision")
            result = {"decision": decision}
        self._write({"id": request["id"], "result": result})

    def disconnect(self):
        self._closing = True
        self._approvals.clear()
        self._native_sessions.clear()
        if self._process and self._process.poll() is None:
            if self._turn_id:
                self.stop()
                if not self._turn_done.wait(10):
                    self._closing = False
                    raise TimeoutError("Codex has not confirmed cancellation; the process was not killed")
            # EOF is the documented stdio transport shutdown, never kill/taskkill.
            try:
                self._process.stdin.close()
            except OSError:
                pass
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._closing = False
                raise TimeoutError("Codex did not exit after stdio close; the process was not killed") from None
        if self._process and self._process.poll() is not None:
            for reader in (self._reader, self._stderr_reader):
                if reader and reader is not threading.current_thread():
                    reader.join(timeout=2)
            for stream in (self._process.stdout, self._process.stderr):
                if stream:
                    stream.close()
        self._session_ready = False
        self.set_state("Disconnected")

    def diagnostics(self):
        return sanitize({**super().diagnostics(), "last_event": self.last_event,
                         "permissions": self._permission_state, "turn": self._turn_id,
                         "output_streams": "Agent command output is combined stdout/stderr",
                         "stderr_tail": self._stderr_tail, "session_requires_resume": bool(self.session_id and not self._session_ready)})
