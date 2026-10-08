"""Official Claude Code stream-json adapter.

Control envelopes follow Anthropic's public claude-agent-sdk-python query.py.
No terminal scraping, credential inspection, permission bypass, or process kill.
Callbacks may arrive on reader threads; Workspace Core owns durable history.
"""
from __future__ import annotations

import json
import os
import base64
import importlib
import inspect
import shutil
import sys
import subprocess
import threading
import time
import uuid
from pathlib import Path

from .base import Adapter, Capabilities
from ..security import sanitize, safe_file


class _NodeSessionSDK:
    """Read-only local subprocess bridge to public TypeScript SDK functions."""
    def __init__(self, helper, node):
        self.helper, self.node = Path(helper), node
        capabilities = self._call('capabilities')
        required = {'listSessions','getSessionInfo','getSessionMessages'}
        if not required.issubset(capabilities.get('methods', [])):
            raise ImportError('Official Node SDK lacks required public session APIs')
        self.__version__ = 'TypeScript '+str(capabilities.get('version', 'unknown'))

    def _call(self, action, **payload):
        completed = subprocess.run([self.node,str(self.helper)],
            input=json.dumps({'action':action,**payload}),capture_output=True,
            text=True,encoding='utf-8',errors='replace',cwd=str(self.helper.parent),
            timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            response=json.loads(completed.stdout)
        except (ValueError,TypeError) as exc:
            raise RuntimeError(sanitize(completed.stderr.strip() or 'Official session helper returned invalid JSON')) from exc
        if completed.returncode or not response.get('ok'):
            raise RuntimeError(sanitize(response.get('error') or completed.stderr.strip() or 'Official session helper failed'))
        return response.get('result')

    def list_sessions(self, directory=None, limit=None, offset=0, include_worktrees=False):
        if include_worktrees:
            raise ValueError('Workspace native discovery does not expand worktrees')
        return self._call('list',directory=directory,limit=limit or 100,offset=offset)

    def get_session_info(self, session_id, directory=None):
        return self._call('info',session_id=session_id,directory=directory)

    def get_session_messages(self, session_id, directory=None, limit=None, offset=0):
        return self._call('history',session_id=session_id,directory=directory,
                          limit=limit or 200,offset=offset)


class _CancellationOwnershipChanged(RuntimeError):
    pass


class ClaudeAdapter(Adapter):
    agent = 'claude'

    def __init__(self, emit, executable='', **settings):
        super().__init__(emit, executable, **settings)
        self._process = None
        self._write_lock = threading.Lock()
        self._operation_lock = threading.RLock()
        self._send_generation = 0
        self._accepted_operation = None
        self._pending = {}
        self._approvals = {}
        self._tools = {}
        self._sessions = {}
        self._history = {}
        self._model_info = []
        self._model = None
        self._effort = None
        self._resume = False
        self._closed = False
        self._stopping = False
        self._turn_text = ''
        self._message_text = ''
        self._message_open = False
        self._message_id = ''
        self._completed_ids = set()
        self._idle = threading.Event()
        self._idle.set()
        self.handshake = {}
        self.backend_cwd = ''
        self._native_sessions = {}
        self._session_sdk = None
        self.session_sdk_version = ''
        self.native_sessions_error = ''
        self._last_stderr = ''
        self._mcp_snapshot = None

    def _event(self, kind, **data):
        clean = sanitize(data)
        if kind == 'message_delta' and isinstance(data.get('content'), str):
            # Core accumulates visible text in memory and sanitizes the whole
            # message before any UI/persistence boundary. Per-chunk filtering
            # would lose the prefix of credentials split across native deltas.
            clean['content'] = data['content']
        self.emit(kind, **clean)

    def _error(self, error):
        self.last_error = sanitize(str(error))
        self._event('error', content=self.last_error)
        self.set_state('Error')

    def _argv(self):
        args = [self.executable, '--print', '--input-format', 'stream-json',
                '--output-format', 'stream-json', '--include-partial-messages',
                '--verbose', '--permission-prompt-tool', 'stdio']
        if self.session_id:
            uuid.UUID(self.session_id)  # prevent option injection / accidental arbitrary IDs
            args.append(('--resume=' if self._resume else '--session-id=') + self.session_id)
        if self._model:
            args.append('--model=' + self._model)
        if self._effort:
            args.append('--effort=' + self._effort)
        servers = self.settings.get('session_mcp_servers')
        if servers is not None:
            # Explicit session-only STDIO entry. No config file or permission
            # rule is written; native MCP permissions remain authoritative.
            if not isinstance(servers, dict) or not servers:
                raise ValueError('Session MCP servers must be a nonempty mapping')
            for name, server in servers.items():
                if not isinstance(name, str) or not name or not all(c.isalnum() or c in '_-' for c in name):
                    raise ValueError('Invalid session MCP server name')
                if not isinstance(server, dict) or set(server) - {'command', 'args', 'type'}:
                    raise ValueError('Only explicit STDIO command/args are supported; no env, URL or credentials')
                command = server.get('command', '')
                arguments = server.get('args', [])
                if server.get('type', 'stdio') != 'stdio' or not isinstance(command, str) or not Path(command).is_absolute():
                    raise ValueError('Session MCP needs an absolute STDIO executable')
                if Path(command).suffix.lower() in ('.bat', '.cmd'):
                    raise ValueError('Session MCP shell wrappers are unsupported')
                if not isinstance(arguments, list) or not all(isinstance(arg, str) for arg in arguments):
                    raise ValueError('Session MCP args must be a string list')
            args.extend(['--mcp-config=' + json.dumps({'mcpServers': servers}, separators=(',', ':')),
                         '--strict-mcp-config', '--tools='])
        return args + self._extra_args()

    def _extra_args(self):
        return []

    def _process_env(self):
        return None

    def connect(self):
        if self._process and self._process.poll() is None:
            if self.state in ('Connected', 'Busy'):
                return self.capabilities
            raise RuntimeError('Previous Claude process is still closing; reconnect after it exits')
        if not self.cwd or not Path(self.cwd).is_dir():
            raise ValueError('Select an existing project working directory before connecting Claude')
        if not self.executable or Path(self.executable).suffix.lower() in ('.cmd', '.bat'):
            raise ValueError('Claude executable must be an official native executable, not a shell wrapper')
        self._closed = False
        self._stopping = False
        self.set_state('Connecting')
        try:
            env = self._process_env()
            self.version = subprocess.run([self.executable, '--version'], capture_output=True,
                text=True, encoding='utf-8', errors='replace', timeout=15,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), **({'env': env} if env is not None else {})).stdout.strip()
            self._process = subprocess.Popen(self._argv(), cwd=self.cwd, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8',
                errors='replace', bufsize=1, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), **({'env': env} if env is not None else {}))
            process = self._process
            self._stdout_thread = threading.Thread(target=self._read_stdout, args=(process,),
                                                   daemon=True, name='claude-events')
            self._stderr_thread = threading.Thread(target=self._read_stderr, args=(process,),
                                                   daemon=True, name='claude-errors')
            self._stdout_thread.start()
            self._stderr_thread.start()
            self.handshake = self._request({'subtype': 'initialize', 'hooks': None},
                                           timeout=float(self.settings.get('timeout', 45)))
            self._discover(self.handshake)
            self.last_error = ''
            self.set_state('Connected')
            self._event('event', content='Claude official initialize handshake completed',
                        summary='Backend handshake', cwd=self.cwd)
            return self.capabilities
        except Exception as exc:
            self._error(exc)
            if self._process and self._process.stdin and not self._process.stdin.closed:
                self._process.stdin.close()  # EOF, never kill an agent process
            raise

    def _discover(self, handshake):
        self._model_info = [m for m in handshake.get('models', []) if isinstance(m, dict)]
        models = []
        for item in self._model_info:
            value = item.get('value') or item.get('id') or item.get('model')
            if value:
                models.append(dict(item, id=value, name=item.get('displayName', value)))
        efforts = self.list_efforts(self._model)
        self.capabilities = Capabilities(
            supports_model_selection=bool(models), supports_effort=any(self.list_efforts(m['id']) for m in models),
            supports_sessions=True, supports_files=True, supports_tools=True,
            supports_project=True, supports_cancel=True, supports_streaming=True,
            supports_history=True, supports_approval=True, models=models, efforts=efforts,
            detail='Official Claude Code stream-json. Workspace history is always available. '
                   'Explicit native session discovery/history uses an official SDK helper; '
                   'no native sessions are scanned automatically. '
                   'Attachments: bounded UTF-8 text and PNG/JPEG/GIF/WebP images. '
                   'Other binary formats require native file tools.')
        self._event('capabilities', capabilities=self.capabilities.to_dict())

    def list_efforts(self, model=None):
        model = model or self._model or 'default'
        selected = [m for m in self._model_info if model in
                    (m.get('value'), m.get('id'), m.get('model'))]
        values = []
        for info in selected:
            if info.get('supportsEffort') is False:
                continue
            for effort in info.get('supportedEffortLevels', info.get('supportedReasoningEfforts', [])):
                value = effort if isinstance(effort, str) else effort.get('reasoningEffort')
                if value and value not in values:
                    values.append(value)
        return values

    def _write(self, message, *, expected_operation=None, dispatch_guard=None):
        with self._operation_lock, self._write_lock:
            if expected_operation is not None and self.active_operation_id() != expected_operation:
                raise _CancellationOwnershipChanged('Claude operation changed before interrupt dispatch')
            if self._closed or not self._process or self._process.poll() is not None or self._process.stdin.closed:
                raise RuntimeError('Claude disconnected')
            if dispatch_guard: dispatch_guard(final=True)
            self._process.stdin.write(json.dumps(message, ensure_ascii=False) + '\n')
            self._process.stdin.flush()

    def _request(self, request, timeout=30, *, expected_operation=None):
        request_id = 'acw_' + uuid.uuid4().hex
        ready = threading.Event()
        pending = {'ready': ready, 'response': None}
        self._pending[request_id] = pending
        try:
            options = {'expected_operation': expected_operation} if expected_operation is not None else {}
            self._write({'type': 'control_request', 'request_id': request_id, 'request': request}, **options)
            if not ready.wait(timeout):
                raise TimeoutError('Claude control request timed out: ' + request['subtype'])
            response = pending['response'] or {}
            if response.get('subtype') == 'error':
                raise RuntimeError(response.get('error', 'Claude control request failed'))
            return response.get('response', {})
        finally:
            self._pending.pop(request_id, None)

    def _read_stdout(self, process):
        try:
            for line in process.stdout:
                with self._operation_lock:
                    if process is not self._process or self._closed:
                        break
                try:
                    message = json.loads(line)
                except (ValueError, TypeError):
                    self._event('error', content='Claude returned invalid JSON: ' + line[:2000])
                    continue
                self._handle(message, process=process)
        except Exception as exc:
            with self._operation_lock:
                if process is self._process and not self._closed:
                    self._error(exc)
        finally:
            with self._operation_lock:
                if process is self._process:
                    self._accepted_operation = None
                    for pending in list(self._pending.values()):
                        pending['response'] = {'subtype': 'error', 'error': self.last_error or self._last_stderr or 'Claude process disconnected'}
                        pending['ready'].set()
                    self._idle.set()
                    if not self._closed:
                        self.set_state('Disconnected')
                        self._event('event', content='Claude process disconnected; reconnect preserves the recorded session')

    def _read_stderr(self, process):
        for line in process.stderr:
            with self._operation_lock:
                if process is not self._process or self._closed:
                    break
                if line.strip():
                    self._last_stderr = sanitize(line.rstrip())
                    self._event('event', role='system', content=self._last_stderr, stream='stderr')

    def _remember_session(self, session_id):
        if session_id:
            self.session_id = session_id
            self._sessions[session_id] = {'id': session_id, 'session_id': session_id,
                                          'cwd': self.cwd, 'agent': self.agent}
            self._event('session', session_id=session_id)

    def _finish_message(self, content=None):
        if content is not None:
            self._message_text = content
        if self._message_open or self._message_text:
            self._event('message_end', content=self._message_text, role='assistant',
                        message_id=self._message_id)
            if self._message_id:
                self._completed_ids.add(self._message_id)
            self._history.setdefault(self.session_id, []).append(
                {'role': 'assistant', 'content': sanitize(self._message_text)})
        self._message_open = False
        self._message_text = ''

    def _handle(self, original, *, process=None):
        with self._operation_lock:
            if process is not None and (process is not self._process or self._closed):
                return
            if (original.get('type') == 'result' and original.get('session_id')
                    and self.session_id and original['session_id'] != self.session_id):
                self._event('event', content='Ignored result from another Claude session', status='ignored')
                return
            return self._handle_current(original)

    def _handle_current(self, original):
        # Apply the persistence boundary before exposing raw events. In particular,
        # thinking and signature blocks are never forwarded to logs or the UI.
        message = self._safe_raw(original)
        self._event('raw', raw=message, redacted=(message != original))
        kind = message.get('type')
        if kind == 'control_response':
            response = message.get('response', {})
            pending = self._pending.get(response.get('request_id'))
            if pending:
                pending['response'] = response
                pending['ready'].set()
            return
        if kind == 'control_request':
            request = message.get('request', {})
            request_id = message.get('request_id', '')
            if request.get('subtype') == 'can_use_tool':
                # Preserve original input only in RAM to send back on explicit UI approval.
                self._approvals[request_id] = original['request']
                self._event('approval', request_id=request_id, details=request)
            else:
                self._write({'type': 'control_response', 'response': {'subtype': 'error',
                    'request_id': request_id, 'error': 'Unsupported host control request'}})
            return
        if kind == 'control_cancel_request':
            self._approvals.pop(message.get('request_id'), None)
            self._event('approval_cancelled', request_id=message.get('request_id'))
            return
        if message.get('session_id') and message['session_id'] != self.session_id:
            self._remember_session(message['session_id'])
        if kind == 'system':
            if message.get('subtype') == 'init':
                self.backend_cwd = message.get('cwd', '')
                # Names/statuses only: never expose MCP URLs, arguments or
                # credentials. This is an observed snapshot, not a tool test.
                self._mcp_snapshot = {
                    'source': 'Official Claude system init',
                    'servers': [{'name': str(s.get('name', '')),
                                 'status': str(s.get('status', 'unknown'))}
                                for s in (message.get('mcp_servers') or []) if isinstance(s, dict)],
                    'tool_names': [t for t in (message.get('tools') or [])
                                   if isinstance(t, str) and t.startswith('mcp__')],
                    'tool_execution_verified': False,
                }
                self._event('event', content='Claude initialized', cwd=self.backend_cwd,
                            model=message.get('model'), tools=message.get('tools', []),
                            mcp_servers=message.get('mcp_servers', []),
                            permission_mode=message.get('permissionMode'))
            else:
                self._event('event', content=message.get('subtype', 'system'), details=message)
        elif kind == 'stream_event':
            # The raw-log sanitizer intentionally omits incomplete stream fragments.
            # Decode only visible text in RAM for Core's whole-message filter.
            event = original.get('event', {})
            event_type = event.get('type')
            if event_type == 'message_start':
                self._finish_message()
                self._message_id = event.get('message', {}).get('id', '')
                self._message_open = True
                self._event('message_start', role='assistant', message_id=self._message_id)
            elif event_type == 'content_block_delta':
                delta = event.get('delta', {})
                if delta.get('type') == 'text_delta':
                    text = delta.get('text', '')
                    self._message_text += text
                    self._turn_text += text
                    self._event('message_delta', content=text, role='assistant',
                                message_id=self._message_id)
            elif event_type == 'message_stop':
                self._finish_message()
            # content_block_stop closes JSON generation, NOT tool execution.
        elif kind == 'assistant':
            body = message.get('message', {})
            blocks = body.get('content', [])
            text = ''.join(b.get('text', '') for b in blocks if b.get('type') == 'text')
            message_id = body.get('id', '')
            if text and message_id not in self._completed_ids:
                self._message_id = message_id
                if not self._message_open:
                    self._event('message_start', role='assistant', message_id=message_id)
                    self._message_open = True
                self._finish_message(text)
            for block in blocks:
                if block.get('type') == 'tool_use':
                    self._tool_start(block)
        elif kind == 'user':
            blocks = message.get('message', {}).get('content', [])
            if isinstance(blocks, list):
                for block in blocks:
                    if block.get('type') == 'tool_result':
                        self._tool_result(block, message.get('tool_use_result'))
        elif kind == 'result':
            with self._operation_lock:
                self._accepted_operation = None
                self._finish_message()
                self._resume = bool(self.session_id)
                status = 'interrupted' if self._stopping else ('error' if message.get('is_error') else 'completed')
                self._event('event', content='Claude turn ' + status, status=status,
                            duration_ms=message.get('duration_ms'), details=message)
                expected_interrupt = self._stopping and message.get('terminal_reason') == 'aborted_streaming'
                self._stopping = False
                if message.get('is_error') and not expected_interrupt:
                    self._error(message.get('result') or message.get('errors') or message.get('subtype'))
                else:
                    self.set_state('Connected')
                self._idle.set()


    def _tool_start(self, block):
        tool_id = block.get('id', '')
        if tool_id in self._tools:
            return
        info = dict(name=block.get('name', ''), arguments=block.get('input', {}),
                    started=time.time(), status='started', tool_id=tool_id)
        self._tools[tool_id] = info
        self._event('tool_start', **info)
        if info['name'] in ('Bash', 'PowerShell'):
            self._event('command', command=info['arguments'].get('command', ''), cwd=self.cwd,
                        status='started', started=info['started'], tool_id=tool_id)
        elif info['name'] in ('Read', 'Write', 'Edit', 'MultiEdit', 'NotebookEdit'):
            self._event('file', path=info['arguments'].get('file_path', info['arguments'].get('notebook_path', '')),
                        operation=info['name'], status='started', tool_id=tool_id)

    def _tool_result(self, block, native_result=None):
        tool_id = block.get('tool_use_id', '')
        info = self._tools.pop(tool_id, {})
        ended = time.time()
        data = dict(tool_id=tool_id, name=info.get('name', ''), result=block.get('content', ''),
                    status='error' if block.get('is_error') else 'completed', ended=ended,
                    duration=ended-info['started'] if info.get('started') else None)
        self._event('tool_result', **data)
        if info.get('name') in ('Bash', 'PowerShell'):
            details = native_result if isinstance(native_result, dict) else {}
            self._event('command', command=info.get('arguments', {}).get('command', ''),
                        cwd=self.cwd, started=info.get('started'), ended=ended,
                        status=data['status'], tool_id=tool_id,
                        stdout=details.get('stdout', block.get('content', '')),
                        stderr=details.get('stderr'), exit_code=details.get('exitCode', details.get('exit_code')),
                        result=block.get('content', ''))
        elif info.get('name') in ('Read', 'Write', 'Edit', 'MultiEdit', 'NotebookEdit'):
            self._event('file', path=info.get('arguments', {}).get('file_path', ''),
                        operation=info.get('name'), status=data['status'], tool_id=tool_id)

    @staticmethod
    def _safe_raw(value):
        """Exclude uploaded image bytes from audit records; preserve structural metadata."""
        clean = sanitize(value)
        def strip(node):
            if isinstance(node, dict):
                if node.get('type') in ('image', 'document') and isinstance(node.get('source'), dict):
                    source = node['source']
                    if 'data' in source:
                        source['data'] = '[OMITTED: attachment binary; original file retained]'
                for item in node.values():
                    strip(item)
            elif isinstance(node, list):
                for item in node:
                    strip(item)
        strip(clean)
        return clean

    def _prepare_content(self, content, attachments):
        if not attachments:
            return content
        roots = [self.cwd, *self.settings.get('attachment_roots', [])]
        blocks = [{'type': 'text', 'text': content}]
        media_types = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
                       '.gif': 'image/gif', '.webp': 'image/webp'}
        max_bytes = min(int(self.settings.get('max_attachment_bytes', 5*1024*1024)), 16*1024*1024)
        for path in attachments:
            file = safe_file(path, roots, max_bytes=max_bytes)
            suffix = file.suffix.lower()
            if suffix in media_types:
                data = file.read_bytes()
                valid = ((suffix == '.png' and data.startswith(b'\x89PNG\r\n\x1a\n')) or
                         (suffix in ('.jpg', '.jpeg') and data.startswith(b'\xff\xd8\xff')) or
                         (suffix == '.gif' and data.startswith((b'GIF87a', b'GIF89a'))) or
                         (suffix == '.webp' and data.startswith(b'RIFF') and data[8:12] == b'WEBP'))
                if not valid:
                    raise ValueError('Attachment bytes do not match declared image type: ' + file.name)
                blocks.append({'type': 'image', 'source': {'type': 'base64',
                              'media_type': media_types[suffix], 'data': base64.b64encode(data).decode('ascii')}})
            else:
                try:
                    text = file.read_text(encoding='utf-8-sig')
                except UnicodeError as exc:
                    raise ValueError('Attachment format unsupported; select UTF-8 text or PNG/JPEG/GIF/WebP') from exc
                if '\x00' in text:
                    raise ValueError('Binary attachment format unsupported; select text or an image')
                clean = sanitize(text)
                label = 'Attachment: ' + file.name + (' (secret redaction applied)' if clean != text else '')
                blocks.append({'type': 'text', 'text': label + '\n' + clean})
        return blocks

    def send_message(self, content, model=None, effort=None, attachments=None, dispatch_guard=None):
        if self.state != 'Connected':
            raise RuntimeError('Claude must be connected and idle before sending')
        outbound_content = self._prepare_content(content, attachments)
        if model and model not in [m['id'] for m in self.capabilities.models]:
            raise ValueError('Model was not advertised by the Claude backend')
        if effort and effort not in self.list_efforts(model or self._model):
            raise ValueError('Effort was not advertised for this Claude model')
        if effort != self._effort:
            self.disconnect()
            self._model, self._effort = model, effort
            self.connect()  # documented startup --effort, same persisted session
        elif model != self._model:
            self._request({'subtype': 'set_model', 'model': model})
            self._model = model
        with self._operation_lock:
            if self.state != 'Connected':
                raise RuntimeError('Claude operation changed during send preparation')
            if dispatch_guard: dispatch_guard()
            self._send_generation += 1
            token = (self._send_generation, id(self._process), self.session_id)
            self._accepted_operation = token
            self._turn_text = ''
            self._message_text = ''
            self._completed_ids.clear()
            self._stopping = False
            self._idle.clear()
            self.set_state('Busy')
            try:
                options = {'dispatch_guard': dispatch_guard} if dispatch_guard is not None else {}
                self._write({'type': 'user', 'message': {'role': 'user', 'content': outbound_content},
                             'parent_tool_use_id': None, 'session_id': self.session_id}, **options)
                self._history.setdefault(self.session_id, []).append({'role': 'user', 'content': sanitize(content)})
            except Exception as exc:
                if self._accepted_operation == token:
                    self._accepted_operation = None
                self._idle.set()
                self._error(exc)
                raise

    def active_operation_id(self):
        """RAM-only local send generation/process/session guard, not native authentication."""
        with self._operation_lock:
            token = self._accepted_operation
            if (self._closed or self.state != 'Busy' or token is None or
                    token != (self._send_generation, id(self._process), self.session_id)):
                return None
            return token

    def stop_if_owned(self, expected):
        with self._operation_lock:
            if expected is None or self.active_operation_id() != expected:
                return False
            self._stopping = True
        try:
            self._request({'subtype': 'interrupt'}, expected_operation=expected)
        except _CancellationOwnershipChanged:
            return False
        with self._operation_lock:
            if self.active_operation_id() != expected:
                return False
            self._event('event', content='Claude interrupt acknowledged; waiting for turn result', status='stopping')
        return True

    def stop(self):
        # Explicit manual Stop keeps its existing current-operation behavior.
        if self.state != 'Busy':
            return False
        self._stopping = True
        self._request({'subtype': 'interrupt'})
        self._event('event', content='Claude interrupt acknowledged; waiting for turn result', status='stopping')
        return True

    def approve(self, request_id, approved):
        request = self._approvals.pop(request_id, None)
        if request is None:
            raise ValueError('Claude approval request expired or unknown')
        response = {'behavior': 'allow', 'updatedInput': request['input']} if approved else {
            'behavior': 'deny', 'message': 'Denied by user in AI Collaboration Workspace'}
        self._write({'type': 'control_response', 'response': {'subtype': 'success',
                     'request_id': request_id, 'response': response}})
        self._event('event', content='Tool permission ' + ('allowed' if approved else 'denied'), request_id=request_id)

    def disconnect(self):
        process = self._process
        if process and process.poll() is None:
            if self.state == 'Busy':
                self.stop()
                if not self._idle.wait(15):
                    raise TimeoutError('Claude cancellation is pending; session remains attached')
            self._closed = True
            self._approvals.clear()
            if not process.stdin.closed:
                process.stdin.close()
            try:
                process.wait(timeout=15)
                self._stdout_thread.join(timeout=3)
                self._stderr_thread.join(timeout=3)
            except subprocess.TimeoutExpired:
                self._event('error', content='Claude did not exit after stdin EOF; no process kill issued')
                raise
        self._closed = True
        self._process = None
        self.set_state('Disconnected')

    def create_session(self):
        connected = self.state in ('Connected', 'Busy')
        self.disconnect()
        self.session_id = str(uuid.uuid4())
        self._resume = False
        self._remember_session(self.session_id)
        if connected:
            self.connect()
        return self.session_id

    def resume_session(self, session_id):
        uuid.UUID(session_id)
        self.disconnect()
        self.session_id = session_id
        self._resume = True
        self.connect()
        self._remember_session(session_id)
        return session_id

    def set_project(self, path, metadata=None):
        path = str(Path(path).resolve())
        if not Path(path).is_dir():
            raise ValueError('Claude working directory does not exist')
        if self.state == 'Busy':
            raise RuntimeError('Stop Claude before changing project')
        if self.cwd and self.cwd != path and self._process:
            self.disconnect()
        self.cwd = path

    def _native_sdk(self):
        """Load only Anthropic's public SDK API, never its CLI or authentication APIs."""
        if self._session_sdk is not None:
            return self._session_sdk
        node_error = ''
        helper = Path(__file__).resolve().parents[2]/'tools'/'claude-session-sdk'/'session-helper.mjs'
        runtime_node = Path(sys.executable).parent.parent/'node'/'bin'/'node.exe'
        node = self.settings.get('node_executable') or shutil.which('node') or (str(runtime_node) if runtime_node.is_file() else None)
        package = helper.parent/'node_modules'/'@anthropic-ai'/'claude-agent-sdk'/'package.json'
        if node and helper.is_file() and package.is_file():
            try:
                sdk = _NodeSessionSDK(helper,node)
                self._session_sdk = sdk
                self.session_sdk_version = sdk.__version__
                self.native_sessions_error = ''
                return sdk
            except (OSError,ValueError,RuntimeError,ImportError,subprocess.TimeoutExpired) as exc:
                node_error = sanitize(str(exc))
        try:
            sdk = importlib.import_module('claude_agent_sdk')
            required = {
                'list_sessions': {'directory', 'limit', 'offset', 'include_worktrees'},
                'get_session_info': {'session_id', 'directory'},
                'get_session_messages': {'session_id', 'directory', 'limit', 'offset'},
            }
            for name, parameters in required.items():
                function = getattr(sdk, name, None)
                if not callable(function) or not parameters.issubset(inspect.signature(function).parameters):
                    raise ImportError('Official SDK lacks the required bounded public ' + name + ' interface')
            self._session_sdk = sdk
            self.session_sdk_version = str(getattr(sdk, '__version__', 'unknown'))
            self.native_sessions_error = ''
            return sdk
        except (ImportError, ValueError, TypeError) as exc:
            self.native_sessions_error = sanitize(
                'Native Claude session discovery/history unavailable: install the optional official '
                '@anthropic-ai/claude-agent-sdk in tools/claude-session-sdk, or claude-agent-sdk '
                'with its Python dependencies. ' + str(exc) + (' Node helper: '+node_error if node_error else ''))
            raise NotImplementedError(self.native_sessions_error) from exc

    @staticmethod
    def _field(item, name, default=None):
        return item.get(name, default) if isinstance(item, dict) else getattr(item, name, default)

    def _native_scope(self):
        if not self.cwd or not Path(self.cwd).is_dir():
            raise ValueError('Select an existing project before native Claude session discovery')
        return str(Path(self.cwd).resolve())

    @staticmethod
    def _native_page(limit, offset):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError('Native session page limit must be between 1 and 500')
        if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 10000:
            raise ValueError('Native session page offset must be between 0 and 10000')

    def list_native_sessions(self, limit=100, offset=0):
        """Explicit read-only metadata discovery for exactly the selected project.

        This method neither connects nor changes session_id, task mapping, or the
        native files. SDK metadata can derive its title from a prompt; only the
        sanitized title is returned, and first_prompt is deliberately excluded.
        """
        self._native_page(limit, offset)
        directory = self._native_scope()
        sdk = self._native_sdk()
        results = sdk.list_sessions(directory=directory, limit=limit, offset=offset,
                                    include_worktrees=False)
        scope_key = os.path.normcase(directory)
        if offset == 0:
            self._native_sessions[scope_key] = {}
        cache = self._native_sessions.setdefault(scope_key, {})
        rows = []
        for item in results:
            session_id = self._field(item, 'session_id', '')
            try:
                uuid.UUID(session_id)
            except (ValueError, TypeError, AttributeError):
                continue
            cwd = self._field(item, 'cwd') or directory
            if os.path.normcase(str(Path(cwd).resolve())) != scope_key:
                continue
            title = self._field(item, 'custom_title') or self._field(item, 'summary') or session_id
            row = sanitize(dict(id=session_id, session_id=session_id, agent=self.agent,
                title=str(title), cwd=directory, source='native', read_only=True,
                git_branch=self._field(item, 'git_branch') or '',
                branch=self._field(item, 'git_branch') or '',
                last_modified=self._field(item, 'last_modified'),
                created_at=self._field(item, 'created_at'), file_size=self._field(item, 'file_size'),
                sdk_version=self.session_sdk_version))
            cache[session_id] = row
            rows.append(dict(row))
        return rows

    def native_history_capability(self):
        """Check public helper exports only; do not discover/read any session."""
        try:
            self._native_sdk()
        except NotImplementedError as exc:
            return dict(supported=False, available=False, read_only=True,
                        reason=sanitize(str(exc)), version='')
        return dict(supported=True, available=True, read_only=True,
                    source='Official Anthropic Agent SDK', version=self.session_sdk_version,
                    scope='Explicitly selected session in the current project', reason='')

    def get_native_history(self, session_id, limit=200, offset=0):
        """Read a specifically selected discovered session; never resume or send."""
        uuid.UUID(session_id)
        self._native_page(limit, offset)
        directory = self._native_scope()
        scope_key = os.path.normcase(directory)
        if session_id not in self._native_sessions.get(scope_key, {}):
            raise PermissionError('Discover and explicitly select this session in the current project before reading native history')
        sdk = self._native_sdk()
        # The public helper parses the whole transcript before applying pagination.
        # Refresh metadata and reject large transcripts before invoking that helper.
        info = sdk.get_session_info(session_id=session_id, directory=directory)
        if info is None:
            raise FileNotFoundError('Native Claude session is no longer available')
        if self._field(info, 'session_id') != session_id:
            raise PermissionError('Official SDK returned metadata for a different session')
        info_cwd = self._field(info, 'cwd') or directory
        if os.path.normcase(str(Path(info_cwd).resolve())) != scope_key:
            raise PermissionError('Native session belongs to a different project')
        size = self._field(info, 'file_size')
        max_bytes = min(int(self.settings.get('max_native_history_bytes', 16*1024*1024)), 32*1024*1024)
        if not isinstance(size, int) or size < 0 or size > max_bytes:
            raise ValueError('Native transcript exceeds the bounded history reader limit or its size is unavailable')
        messages = sdk.get_session_messages(session_id=session_id, directory=directory,
                                            limit=limit, offset=offset)
        rows = []
        for item in messages:
            item_session = self._field(item, 'session_id', '')
            if item_session and item_session != session_id:
                continue
            role = self._field(item, 'type', '')
            if role not in ('user', 'assistant'):
                continue
            body = self._safe_raw(self._field(item, 'message', {}))
            content = body.get('content', '') if isinstance(body, dict) else body
            if isinstance(content, list):
                visible = [block for block in content if isinstance(block, dict)
                           and block.get('type') not in ('omitted_reasoning', 'thinking', 'redacted_thinking')]
                rendered = '\n'.join(block.get('text', '') if block.get('type')=='text'
                                     else json.dumps(block, ensure_ascii=False) for block in visible)
            else:
                rendered = str(content or '')
            rows.append(sanitize(dict(id=self._field(item, 'uuid', ''), session_id=session_id,
                agent=self.agent, role=role, content=rendered, source='native', read_only=True,
                raw=body, parent_tool_use_id=self._field(item, 'parent_tool_use_id'))))
        return rows

    def list_sessions(self, *, native=False, limit=100, offset=0):
        if native:
            return self.list_native_sessions(limit=limit, offset=offset)
        return list(self._sessions.values())

    def get_history(self, session_id=None, *, native=False, limit=200, offset=0):
        if native:
            if not session_id:
                raise ValueError('Select a native session before reading its history')
            return self.get_native_history(session_id, limit=limit, offset=offset)
        return list(self._history.get(session_id or self.session_id, []))

    def diagnostics(self):
        return dict(super().diagnostics(), backend_cwd=self.backend_cwd,
                    models_source='Official initialize handshake',
                    history_scope='Workspace-owned history; explicit native reads via official SDK helper',
                    native_session_sdk_version=self.session_sdk_version,
                    native_history_supported=self._session_sdk is not None,
                    native_session_error=self.native_sessions_error,
                    last_stderr=self._last_stderr,
                    session_mcp_servers=list(self.settings.get('session_mcp_servers') or {}),
                    mcp_inventory=dict(self._mcp_snapshot, connection_state=self.state,
                                       snapshot_only=True) if self._mcp_snapshot is not None else
                                  {'status': 'Not yet reported by backend', 'snapshot_only': True,
                                   'tool_execution_verified': False},
                    native_session_scope='Selected cwd only; worktree expansion disabled; no automatic discovery')
