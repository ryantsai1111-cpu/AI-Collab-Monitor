"""Hermes one-shot JSONL transport; Workspace owns stable conversation identities.

Only explicit Connect probes the CLI. Prompts travel through UTF-8 files, never a
shell. Hermes owns provider credentials and tool approvals; this transport does
not claim an interactive permission bridge or modify Hermes configuration.
"""
from __future__ import annotations

import csv
from datetime import datetime
import io
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid

from ._proc import popen_hidden, run_hidden
from .base import Adapter, Capabilities
from ..security import sanitize


SESSION = re.compile(r'hermes-[0-9a-f]{32}')
NATIVE_SESSION = re.compile(r'(?:[0-9]{8}_[0-9]{6}_[0-9a-f]{6,32}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})')
DETAIL = ('Hermes CLI · provider／模型留白沿用 Hermes 設定；工具核准由 Hermes 管理，'
          '本視窗無法逐次核准，既有單次模式設定可能自動允許工具。')
MAX_LINE = 1024 * 1024
# Shared with the hermes-delegation skill's run.sh: one JSON line
# {pid,label,worktree,hermes_exe,started}; pid is the launcher, not hermes.exe.
DEFAULT_LOCK = 'C:/tools/hermes/runs/hermes.lock'
LOCK_ENV = 'ACW_HERMES_LOCK'


def hermes_settings(settings):
    """Ignore legacy routing at runtime without rewriting saved user settings."""
    result = dict(settings or {})
    legacy = (result.get('harness') in ('claude', 'codex')
              or (result.get('harness') != 'hermes' and 'base_url' in result))
    if legacy:
        for key in ('executable', 'provider', 'model', 'default_model', 'default_effort'):
            result.pop(key, None)
    for key in ('base_url', 'api_key_env', 'max_output_tokens', 'context_tokens',
                'codex_executable', 'claude_executable'):
        result.pop(key, None)
    result['harness'] = 'hermes'
    for key, value in (('executable', ''), ('provider', ''), ('model', ''),
                       ('run_budget', 600), ('max_turns', 60)):
        result.setdefault(key, value)
    return result


def find_hermes():
    executable = shutil.which('hermes') or ''
    if executable and Path(executable).suffix.lower() not in ('.cmd', '.bat', '.ps1'):
        return executable
    if os.name == 'nt':
        local = os.environ.get('LOCALAPPDATA')
        if local:
            candidate = Path(local) / 'hermes/hermes-agent/.hermes/bin/hermes.exe'
            if candidate.is_file():
                return str(candidate)
    return ''


def lock_path(settings):
    """Settings override the environment, which overrides run.sh's default path."""
    value = (settings or {}).get('lock_file') or os.environ.get(LOCK_ENV) or DEFAULT_LOCK
    return Path(str(value))


def pid_alive(pid):
    """Match only the PID column of tasklist's CSV output, like run.sh's alive()."""
    pid = int(pid)
    if os.name != 'nt':
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    try:
        completed = run_hidden(
            ['tasklist', '/FI', f'PID eq {pid}', '/NH', '/FO', 'CSV'], stdin=subprocess.DEVNULL,
            capture_output=True, text=True, errors='replace', timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return True  # Unknown liveness must not let a second Hermes start.
    for row in csv.reader(io.StringIO(completed.stdout or '')):
        if len(row) >= 2 and row[1].strip() == str(pid):
            return True
    return False


def _parse_lock(text):
    line = (text or '').strip().splitlines()[:1]
    try:
        data = json.loads(line[0]) if line else None
    except ValueError:
        return None
    if isinstance(data, dict) and type(data.get('pid')) is int and data['pid'] > 0:
        return data
    return None


def read_lock(path):
    """Return the holder record, None when absent; a competitor may still be writing."""
    for attempt in range(5):
        try:
            data = _parse_lock(Path(path).read_text(encoding='utf-8', errors='replace'))
        except FileNotFoundError:
            return None
        except OSError:
            data = None
        if data:
            return data
        if attempt < 4:
            time.sleep(0.2)
    raise RuntimeError(f'Hermes 鎖檔無法解讀，不啟動：{path}')


class HermesLock:
    """The run.sh mutex, written by Workspace for the lifetime of its own child."""

    def __init__(self, path, label, worktree, executable):
        self.path = Path(path)
        self.label = str(label)
        self.worktree = Path(worktree).as_posix() if worktree else ''
        self.executable = Path(executable).name if executable else ''
        self.held = False

    def _line(self):
        return json.dumps({
            'pid': os.getpid(), 'label': self.label, 'worktree': self.worktree,
            'hermes_exe': self.executable,
            'started': datetime.now().astimezone().isoformat(timespec='seconds'),
        }, ensure_ascii=False) + '\n'

    def _create(self):
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0)
        try:
            handle = os.open(str(self.path), flags, 0o644)
        except FileExistsError:
            return False
        try:
            os.write(handle, self._line().encode('utf-8'))
        finally:
            os.close(handle)
        self.held = True
        return True

    @staticmethod
    def describe(holder):
        label = str(holder.get('label') or '?')
        owner = f'本程式的 {label}' if label.startswith('acw:') else f'run.sh 的 {label}'
        return f'Hermes 正由 {owner} 使用中（pid {holder["pid"]}）'

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            if self._create():
                return
            holder = read_lock(self.path)
            if holder is None:
                continue  # Removed between our attempt and our read; try once more.
            pid = holder['pid']
            if pid == os.getpid() or pid_alive(pid):
                raise RuntimeError(self.describe(holder))
            # Stale: move it aside, confirm it is still the dead record we read
            # (not a competitor's fresh lock), then drop only that copy.
            stale = self.path.with_name(f'{self.path.name}.stale.{os.getpid()}.{uuid.uuid4().hex[:8]}')
            try:
                os.replace(self.path, stale)
            except OSError:
                raise RuntimeError('Hermes 鎖剛被其他程序取得，請稍後再試') from None
            try:
                moved = _parse_lock(stale.read_text(encoding='utf-8', errors='replace'))
            except OSError:
                moved = None
            if not moved or moved['pid'] != pid:
                try:
                    os.replace(stale, self.path)
                except OSError:
                    pass
                raise RuntimeError('Hermes 鎖剛被其他程序取得，請稍後再試')
            stale.unlink(missing_ok=True)
            print(f'[acw] 殘留的 Hermes 鎖已移除：{holder.get("label", "?")}（pid {pid} 已結束）',
                  file=sys.stderr, flush=True)
        raise RuntimeError('Hermes 鎖剛被其他程序取得，請稍後再試')

    def release(self):
        """Delete the file only while it still carries this launcher's own record."""
        if not self.held:
            return
        self.held = False
        try:
            holder = _parse_lock(self.path.read_text(encoding='utf-8', errors='replace'))
        except OSError:
            return
        if holder and holder['pid'] == os.getpid() and holder.get('label') == self.label:
            try:
                self.path.unlink()
            except OSError:
                pass


class HermesAdapter(Adapter):
    agent = 'local'
    local_harness = 'hermes'

    def __init__(self, emit, executable='', **settings):
        options = hermes_settings(dict(settings, executable=executable))
        super().__init__(emit, options.pop('executable'), **options)
        self._process = None
        self._thread = None
        self._operation_lock = threading.RLock()
        self._operation = None
        self._cancelled = False
        self._timeout_error = ''
        self._closed = False
        self._native_session_id = ''
        self._sessions = {}
        self._stderr_tail = ''
        self._last_probe = None
        self._hermes_lock = None
        model = str(self.settings.get('model') or '').strip()
        self.capabilities = Capabilities(
            supports_model_selection=bool(model), models=[model] if model else [],
            supports_sessions=True, supports_create_session=True,
            supports_project=True, supports_cancel=True, supports_tools=True,
            supports_streaming=True, supports_history=True, supports_approval=False,
            detail=DETAIL)

    @property
    def configured(self):
        return True  # Provider/model may come from the existing Hermes config.

    def active_operation_id(self):
        with self._operation_lock:
            return self._operation if self._process is not None else None

    def _event(self, kind, **data):
        if self._closed:
            return
        # Core sanitizes the accumulated text so split secrets cannot evade it.
        self.emit(kind, **(data if kind == 'message_delta' else sanitize(data)))

    def _error(self, error):
        self.last_error = sanitize(str(error))
        self._event('error', content=self.last_error)
        if not self._closed:
            self.set_state('Error')

    def _limits(self):
        values = []
        for key, default, maximum in (('run_budget', 600, 86400), ('max_turns', 60, 1000)):
            value = self.settings.get(key, default)
            if isinstance(value, bool) or not re.fullmatch(r'[0-9]+', str(value)):
                raise ValueError(f'Hermes {key} 必須是正整數')
            value = int(value)
            if not 1 <= value <= maximum:
                raise ValueError(f'Hermes {key} 必須介於 1 與 {maximum}')
            values.append(value)
        return values

    @staticmethod
    def _option(value, name):
        value = str(value or '').strip()
        if len(value) > 256 or any(ord(c) < 32 for c in value):
            raise ValueError(f'Hermes {name} 格式不正確')
        return value

    def probe(self):
        """Check the installed protocol without requesting inference or login."""
        self._limits()
        executable = self.executable or find_hermes()
        if not executable:
            raise FileNotFoundError('找不到 Hermes CLI；請在設定選擇 hermes.exe')
        if Path(executable).suffix.lower() in ('.cmd', '.bat', '.ps1'):
            raise ValueError('請選擇 Hermes 原生 executable，不支援 shell wrapper')
        completed = run_hidden(
            [executable, 'chat', '--help'], stdin=subprocess.DEVNULL,
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=20)
        required = ('--query-file', '--format', 'stream-json', '--resume', '--in',
                    '--no-restore-cwd', '--source', '--run-budget', '--max-turns')
        if completed.returncode or any(flag not in completed.stdout for flag in required):
            raise RuntimeError('Hermes CLI 不支援必要的 stream-json 協定；請檢查 executable 與版本')
        self.executable = executable
        self._last_probe = {'executable': executable, 'detail': DETAIL, 'protocol': 'stream-json'}
        return dict(self._last_probe)

    def connect(self):
        if self.state in ('Connected', 'Busy'):
            return self.capabilities
        self._closed = False
        self.set_state('Connecting')
        try:
            self.probe()
        except Exception as exc:
            self._error(exc)
            raise
        self.last_error = ''
        self._event('capabilities', capabilities=self.capabilities.to_dict())
        self.set_state('Connected')
        return self.capabilities

    def _idle(self):
        if self._process is not None or self.state == 'Busy':
            raise RuntimeError('請先停止或等待 Hermes 工作完成')

    def set_project(self, path, metadata=None):
        self._idle()
        target = str(Path(path).resolve())
        if self.cwd and os.path.normcase(self.cwd) != os.path.normcase(target):
            self.session_id = self._native_session_id = ''
        self.cwd = target

    def _publish_session(self):
        self._sessions[self.session_id] = {
            'id': self.session_id, 'cwd': self.cwd,
            'native_session_id': self._native_session_id,
            'local_harness': 'hermes', 'title': self.session_id}
        self._event('session', session_id=self.session_id,
                    native_session_id=self._native_session_id, cwd=self.cwd,
                    local_harness='hermes')

    def create_session(self):
        self._idle()
        if self.state != 'Connected':
            raise RuntimeError('請先連線 Hermes')
        self.session_id = 'hermes-' + uuid.uuid4().hex
        self._native_session_id = ''
        self._publish_session()
        return self.session_id

    def restore_session_metadata(self, session_id, metadata):
        if not SESSION.fullmatch(str(session_id)):
            raise ValueError('舊 harness 的對話無法由 Hermes 接續；請建立新對話')
        native = str(metadata.get('native_session_id') or '')
        if native and not NATIVE_SESSION.fullmatch(native):
            raise ValueError('Hermes native session ID 格式不正確')
        cwd = metadata.get('cwd') or self.cwd
        if os.path.normcase(str(Path(cwd).resolve())) != os.path.normcase(str(Path(self.cwd).resolve())):
            raise ValueError('Hermes 對話不屬於目前 Project')
        self._sessions[session_id] = dict(metadata, id=session_id, cwd=cwd, native_session_id=native)

    def resume_session(self, session_id):
        self._idle()
        if self.state != 'Connected':
            raise RuntimeError('請先連線 Hermes')
        row = self._sessions.get(session_id)
        if not row or not SESSION.fullmatch(str(session_id)):
            raise ValueError('找不到 Workspace 保存的 Hermes 對話')
        if os.path.normcase(str(Path(row['cwd']).resolve())) != os.path.normcase(str(Path(self.cwd).resolve())):
            raise ValueError('Hermes 對話不屬於目前 Project')
        self.session_id = session_id
        self._native_session_id = row.get('native_session_id', '')
        self._publish_session()
        return session_id

    def list_sessions(self):
        return [dict(row) for row in self._sessions.values() if row['cwd'] == self.cwd]

    def _lock_label(self):
        # Core does not pass the instance key; an explicit `instance` setting names it.
        return 'acw:' + str(self.settings.get('instance') or 'hermes')

    def _argv(self, prompt, model=None):
        budget, turns = self._limits()
        args = [self.executable, 'chat', '--query-file', str(prompt), '-Q',
                '--format', 'stream-json', '--in', self.cwd, '--no-restore-cwd',
                '--source', 'tool', '--run-budget', str(budget), '--max-turns', str(turns)]
        for flag, value in (('provider', self.settings.get('provider')),
                            ('model', model or self.settings.get('model'))):
            value = self._option(value, flag)
            if value:
                args.append('--' + flag + '=' + value)
        if self._native_session_id:
            if not NATIVE_SESSION.fullmatch(self._native_session_id):
                raise ValueError('Hermes native session ID 格式不正確')
            args.append('--resume=' + self._native_session_id)
        return args

    def send_message(self, content, model=None, effort=None, attachments=None, dispatch_guard=None):
        with self._operation_lock:
            self._idle()
            if self.state != 'Connected' or not self.executable:
                raise RuntimeError('請先連線 Hermes')
            if attachments:
                raise ValueError('Hermes 目前不支援面板附件；請在提示中指定專案內的檔案')
            if effort:
                raise ValueError('Hermes reasoning 使用既有設定')
            if not isinstance(content, str) or not content.strip():
                raise ValueError('Message is empty')
            if not self.cwd or not Path(self.cwd).is_dir():
                raise ValueError('請先選擇有效的 Project 資料夾')
            if not self.session_id:
                self.create_session()
            temporary = tempfile.TemporaryDirectory(prefix='acw-hermes-')
            try:
                prompt = Path(temporary.name) / 'query.txt'
                prompt.write_text(content, encoding='utf-8', newline='')
                argv = self._argv(prompt, model)
                env = os.environ.copy()
                env['PYTHONUTF8'] = '1'
                env['PYTHONIOENCODING'] = 'utf-8'
                # Ambient integration flags must not attach this child to another
                # dispatcher or silently enable yolo / hook approval.
                for key in list(env):
                    if key.startswith(('HERMES_KANBAN_', 'HERMES_TURN_')) or key in (
                            'HERMES_YOLO_MODE', 'HERMES_ACCEPT_HOOKS', 'HERMES_SESSION_ID',
                            'HERMES_INTERACTIVE', 'HERMES_TUI'):
                        env.pop(key)
                if dispatch_guard:
                    dispatch_guard(final=True)
                lock = self._hermes_lock = HermesLock(
                    lock_path(self.settings), self._lock_label(), self.cwd, self.executable)
                lock.acquire()
                self._cancelled = False
                self._timeout_error = self._stderr_tail = ''
                self._operation = uuid.uuid4().hex
                process = popen_hidden(
                    argv, env, cwd=self.cwd, stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, encoding='utf-8', errors='replace', shell=False,
                    start_new_session=os.name != 'nt')
                self._process = process
            except Exception:
                if self._hermes_lock is not None:
                    self._hermes_lock.release()
                temporary.cleanup()
                raise
            try:
                self.set_state('Busy')
                self._event('message_start', role='assistant')
                self._thread = threading.Thread(target=self._read_run,
                    args=(process, temporary, self._operation, lock), daemon=True,
                    name='acw-hermes-stream')
                self._thread.start()
            except Exception as exc:
                try:
                    self._terminate(process)
                finally:
                    for pipe in (process.stdout, process.stderr):
                        pipe.close()
                    temporary.cleanup()
                    lock.release()
                    self._process = None
                    self._thread = None
                    self._event('message_end', content='', status='interrupted')
                    self._error(exc)
                raise
            return self._operation

    def _read_stderr(self, process):
        try:
            while chunk := process.stderr.read(2048):
                self._stderr_tail = (self._stderr_tail + chunk)[-8192:]
        except (OSError, ValueError):
            pass

    def _accept_native(self, value):
        if not isinstance(value, str) or not NATIVE_SESSION.fullmatch(value):
            raise RuntimeError('Hermes 回傳無效的 session ID')
        self._native_session_id = value
        self._publish_session()

    def _read_run(self, process, temporary, operation, lock=None):
        stderr = threading.Thread(target=self._read_stderr, args=(process,), daemon=True)
        timer = threading.Timer(self._limits()[0] + 30, self._expire, args=(operation,))
        timer.daemon = True
        result = None
        text = ''
        failure = ''
        try:
            stderr.start()
            timer.start()
            while line := process.stdout.readline(MAX_LINE + 1):
                if len(line) > MAX_LINE:
                    raise RuntimeError('Hermes JSONL 事件超過 1 MiB 上限')
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    raise RuntimeError('Hermes stdout 未遵循 stream-json 協定') from None
                if not isinstance(event, dict):
                    raise RuntimeError('Hermes 回傳無效的 JSONL 事件')
                kind = event.get('type')
                if result is not None:
                    raise RuntimeError('Hermes 在完成事件後仍回傳資料')
                if kind == 'system' and event.get('subtype') == 'init':
                    self._accept_native(event.get('session_id'))
                elif kind == 'text':
                    delta = event.get('text')
                    if not isinstance(delta, str):
                        raise RuntimeError('Hermes 文字事件格式不正確')
                    text += delta
                    self._event('message_delta', content=delta)
                elif kind == 'tool_use':
                    self._event('tool_start', name=event.get('name', 'unknown'),
                                tool_id=event.get('tool_call_id', ''), input=event.get('input', {}))
                elif kind == 'tool_result':
                    self._event('tool_result', name=event.get('name', 'unknown'),
                                tool_id=event.get('tool_call_id', ''), content=event.get('output', ''),
                                is_error=bool(event.get('is_error')), duration_ms=event.get('duration_ms'))
                elif kind == 'result':
                    if type(event.get('exit_code')) is not int or not isinstance(event.get('text'), str):
                        raise RuntimeError('Hermes 完成事件格式不正確')
                    self._accept_native(event.get('session_id'))
                    result = event
                # Unknown events (including private reasoning) are never persisted.
            returncode = process.wait()
            stderr.join(timeout=1)
            if self._timeout_error:
                raise RuntimeError(self._timeout_error)
            if not self._cancelled:
                if not result:
                    raise RuntimeError(f'Hermes 未回傳完成事件（exit {returncode}）')
                if returncode or result['exit_code'] or result.get('error'):
                    raise RuntimeError(f'Hermes 工作失敗（exit {returncode}/{result["exit_code"]}）：'
                                       + str(result.get('error') or self._stderr_tail[-1500:]))
        except Exception as exc:
            failure = sanitize(str(exc))
            self._terminate(process)
        finally:
            timer.cancel()
            if stderr.ident is not None:
                stderr.join(timeout=1)
            for pipe in (process.stdout, process.stderr):
                try:
                    pipe.close()
                except (OSError, ValueError):
                    pass
            temporary.cleanup()
            if lock is not None:
                lock.release()
            if self._operation == operation:
                interrupted = self._cancelled or bool(failure)
                final_text = result['text'] if result else text
                self._event('message_end', content=final_text,
                            status='interrupted' if interrupted else 'complete')
                self._process = None
                if failure and not self._cancelled:
                    self._error(failure)
                elif not self._closed:
                    self.set_state('Connected')

    @staticmethod
    def _terminate(process):
        """Terminate only this invocation's owned process tree, never by name."""
        if process.poll() is not None:
            return
        try:
            if os.name == 'nt':
                run_hidden(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                    capture_output=True, timeout=5)
            else:
                os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)

    def _expire(self, operation):
        with self._operation_lock:
            if self._operation != operation or self._process is None:
                return
            self._timeout_error = 'Hermes 超過本次執行時間上限，已停止此工作'
            process = self._process
        self._terminate(process)

    def stop_if_owned(self, expected):
        with self._operation_lock:
            if expected != self._operation or self._process is None:
                return False
            self._cancelled = True
            process = self._process
        self._terminate(process)
        return True

    def stop(self):
        return self.stop_if_owned(self._operation)

    def disconnect(self):
        self.stop()
        if self._thread and self._thread.ident is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=8)
        self._closed = True
        self.set_state('Disconnected')

    def diagnostics(self):
        return dict(super().diagnostics(), harness='hermes',
                    native_session_id=self._native_session_id,
                    lock_file=str(lock_path(self.settings)),
                    lock_held=bool(self._hermes_lock and self._hermes_lock.held),
                    stderr_tail=sanitize(self._stderr_tail), probe=self._last_probe,
                    approval_owner='Hermes configuration (no Workspace approval bridge)')
