"""File-request dispatch: lets the hermes-delegation skill's run.sh hand a Hermes step to the open workspace.

run.sh writes ``<data_dir>/requests/<label>.json`` and waits for ``<label>.result.json``. The workspace
(the one process that owns the sqlite file and the in-memory agent selections) turns the request into a
project, a fresh session, a message and events exactly as if it had been sent from the UI, projects the
run into the desktop Monitor's ``logs/`` and answers with a result file. See docs/DESIGN-hermes-single-entry.md §3.2.

No Qt here. ``poll()`` is meant to be called about once a second from any single thread at a time.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from .hermes_mask import LineMasker, mask
from .security import sanitize
from . import playbooks

HEARTBEAT = '.dispatcher.json'
LABEL = re.compile(r'(?!\.)[A-Za-z0-9._-]{1,64}')
EOL = '\r\n'
TOOL_INPUT_MAX = 120
DECISION_MAX = 160
RESULT_MAX = 1500
GRACE_SECONDS = 120          # added to run_budget before the workspace gives up on a run
EXPIRY_SECONDS = 180         # a request older than run_budget + this is dead: run.sh has stopped waiting
PARTIAL_JSON_SECONDS = 5     # an unparsable request younger than this may still be mid-write
MAX_BUDGET, MAX_TURNS = 86400, 1000
WANTED = ('message_start', 'message_delta', 'tool_start', 'tool_result', 'message_end', 'error', 'approval', 'approval_response')
# Reasons starting with one of these mean "the request itself is wrong": run.sh refuses (exit 3). Every other
# rejection means "this workspace cannot take it right now": run.sh falls back to starting hermes.exe directly.
REFUSAL_CODES = ('bad-label', 'bad-request', 'no-worktree', 'no-progress', 'dirty-worktree', 'git-failed', 'expired', 'no-spec')


def _iso():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def _clip(text, limit):
    text = ' '.join(str(text).split())
    return text if len(text) <= limit else text[:limit - 3] + '...'


def _norm(path):
    return os.path.normcase(os.path.normpath(str(Path(str(path)).resolve())))


def _positive(value, maximum):
    """A positive int within bounds, or None. Strings of digits are fine (run.sh passes env values)."""
    if isinstance(value, bool) or value is None or not re.fullmatch(r'[0-9]+', str(value)):
        return None
    number = int(str(value))
    return number if 1 <= number <= maximum else None


class MonitorProjection:
    """Writes one run into <root>/logs/hermes.log and timeline.log in hermes_stream_filter.py's format.

    UTF-8 without BOM, append only, CRLF. tool_result content is never printed. RUN_STARTED / RUN_ENDED are
    run.sh's, not ours. Every line is masked twice on its way out: the core's ``sanitize`` first, then
    ``hermes_mask.mask`` (a copy of the direct path's rules), so both entry points mask alike.
    """

    def __init__(self, label, root, provider='local'):
        self.label = label
        self.provider = provider
        self.turn_ended = False
        self.last_message = ''
        self.actor = 'CODEX' if provider == 'codex' else 'HERMES'
        self.hermes_log = self.timeline_log = None
        if isinstance(root, str) and root and Path(root).is_dir():
            logs = Path(root) / 'logs'
            try:
                logs.mkdir(parents=True, exist_ok=True)
                self.hermes_log, self.timeline_log = logs / ('codex.log' if provider == 'codex' else 'hermes.log'), logs / 'timeline.log'
            except OSError:
                pass
        self.done = 0        # complete lines of the accumulated assistant text already written
        self.carry = ''      # the part of an unfinished line that a flush already wrote
        self.latest = ''     # the core's newest accumulated (already redacted) text
        self.seen = set()
        self.masker = LineMasker()

    @property
    def active(self):
        return self.hermes_log is not None

    @staticmethod
    def _append(path, line):
        if path is None:
            return
        try:
            with open(path, 'ab') as handle:
                handle.write((line.replace('\r\n', '\n').replace('\n', EOL) + EOL).encode('utf-8'))
        except OSError:
            pass

    def clean(self, text):
        """sanitize, then mask, line by line (multi-line PEM blocks stay masked across lines)."""
        return '\n'.join(self.masker.render(line) for line in sanitize(str(text)).split('\n'))

    def say(self, text):
        clean = self.clean(text)
        self._append(self.hermes_log, clean)
        return clean

    def timeline(self, event, message):
        message = mask(sanitize(message))
        if (event, message) in self.seen:
            return
        self.seen.add((event, message))
        self._append(self.timeline_log, '%s | %s | %s | %s | %s' % (_iso(), self.label, self.actor, event, message))

    def scan(self, line):
        if '[DECISION NEEDED]' in line:
            self.timeline('DECISION_NEEDED', _clip(line, DECISION_MAX))
        if 'Repetition Detected' in line:
            self.timeline('REPETITION_DETECTED', _clip(line, DECISION_MAX))

    def line(self, text):
        self.scan(self.say(text.rstrip('\r')))

    def flush(self):
        """Write the unfinished last line (if any), as the direct path does before a tool line or at the end."""
        lines = self.latest.split('\n')
        rest = lines[self.done] if self.done < len(lines) else ''
        if rest.startswith(self.carry):
            rest = rest[len(self.carry):]
        if rest:
            self.line(rest)
            self.carry += rest

    def text(self, accumulated):
        """``accumulated`` is the core's whole redacted assistant text so far.

        Only complete lines are written, and always taken from the newest whole text: the core may rewrite
        earlier characters when a secret turns out to span deltas, so nothing is kept from older deltas.
        """
        self.latest = accumulated
        lines = accumulated.split('\n')[:-1]
        while self.done < len(lines):
            line = lines[self.done]
            if self.carry and line.startswith(self.carry):
                line = line[len(self.carry):]
            self.carry = ''
            self.done += 1
            self.line(line)

    def reset(self):
        self.done, self.carry, self.latest = 0, '', ''

    def event(self, event, status):
        """Project one buffered core event. ``status`` is the exit meaning of a message_end (0 or 1)."""
        kind = event['type']
        if self.hermes_log is None:
            return
        if kind == 'message_delta':
            self.text(str(event.get('content') or ''))
            return
        if self.provider == 'codex' and kind == 'message_end':
            # Completed text can arrive without deltas, or replace their last fragment.
            self.text(str(event.get('content') or self.latest))
        self.flush()
        if self.provider == 'codex':
            if kind == 'message_end':
                self.last_message = str(event.get('content') or self.latest)
                self.say('')
                self.reset()
                return
            if kind == 'command':
                if event.get('status') == 'inProgress':
                    self.say('[CMD] ' + _clip(self.clean(event.get('command') or ''), 120))
                else:
                    self.say('[CMD DONE] status=%s exit=%s' % (event.get('status'), event.get('exit_code')))
                return
            if kind == 'file':
                action = event.get('action') or ''
                if isinstance(action, dict):
                    action = action.get('type', '')
                self.say('[FILE] %s %s' % (action, event.get('path') or ''))
                return
            if kind == 'diff':
                self.say('[DIFF] %s files' % event.get('file_count', 0))
                return
            if kind == 'test':
                self.say('[TEST] %s %s' % (event.get('name') or '', event.get('result') or ''))
                return
        if kind == 'message_start':
            self.reset()                         # the core starts a fresh accumulated text
            return
        if kind == 'tool_start':
            try:
                detail = json.dumps(event.get('input'), ensure_ascii=False) if 'input' in event else ''
            except (TypeError, ValueError):
                detail = ''
            self.say('[TOOL] %s %s' % (str(event.get('name', 'unknown')), _clip(self.clean(detail), TOOL_INPUT_MAX)))
        elif kind == 'tool_result':
            duration = event.get('duration_ms')
            self.say('[TOOL DONE] %s %sms error=%s' % (str(event.get('name', 'unknown')),
                     '?' if duration is None else duration, str(bool(event.get('is_error'))).lower()))
        elif kind == 'message_end':
            reply = self.clean(event.get('content') or '')
            if len(reply) > RESULT_MAX:
                reply = reply[:RESULT_MAX] + '...'
            # The reply was already streamed line by line above; print only its first line here.
            lines = [line for line in reply.splitlines() if line.strip()]
            summary = _clip(lines[0], 200) if lines else ''
            if len(lines) > 1:
                summary += ' (+%d more lines, streamed above)' % (len(lines) - 1)
            self.say('[RESULT exit=%s] %s' % (status, summary))
            for line in reply.splitlines():
                self.scan(line)
        elif kind == 'error':
            self.say('[ERROR] ' + _clip(self.clean(event.get('content') or ''), RESULT_MAX))


    def end_turn(self, status, successful, *, inferred=False):
        if self.turn_ended:
            return
        self.turn_ended = True
        self.flush()
        reply = self.clean(self.latest or self.last_message)
        first = reply.splitlines()[0] if reply.splitlines() else ''
        self.say('[RESULT exit=%s] %s' % (0 if successful else 1, _clip(first, 200)))
        self.timeline('TURN_END', status)
        if inferred:
            self.timeline('TURN_END_INFERRED', status)


class RequestDispatcher:
    def __init__(self, core, directory=None, agent='local', clock=time.monotonic):
        self.core = core
        self.default_agent = agent
        self.directory = Path(directory) if directory else Path(core.data_dir) / 'requests'
        self.clock = clock                      # monotonic seconds; tests replace it
        self._poll_lock = threading.Lock()
        self._seen = set()                      # (file name, mtime_ns) of requests already decided
        self._run = None
        self._buffer = deque(maxlen=20000)
        self._active_task = None
        core._event_taps.append(self._on_event)

    @property
    def agent(self):
        return self._run['agent'] if self._run else self.default_agent

    def active(self):
        """Return a detached public snapshot without exposing adapter/run internals."""
        run = self._run
        return {key: run[key] for key in ('label', 'worktree', 'task_id', 'started')} if run else None

    # ------------------------------------------------------------------ event tap
    def _on_event(self, event):
        """Called by Core._record for every event; only buffers the active run's few event types.

        The persisted ``events`` rows deliberately drop message_delta text, so the Monitor projection
        cannot be rebuilt from the database. The buffer is drained by ``poll()``.
        """
        task_id = self._active_task
        if task_id is None or event.get('agent') != self.agent or event.get('task_id') != task_id:
            return
        kind = event.get('type')
        codex = self._run is not None and self._run['provider'] == 'codex'
        if codex:
            # Even an unprojected output notification means the turn is still active.
            self._run['last_activity'] = self.clock()
        if codex and kind in ('event', 'state', 'command', 'file', 'diff', 'test'):
            if kind == 'event' and not str(event.get('summary') or '').startswith('Turn '):
                return
            keys = {
                'event': ('summary', 'status', 'turn_id'), 'state': ('state',),
                'command': ('command', 'status', 'exit_code'), 'file': ('path', 'action'),
                'diff': (), 'test': ('name', 'result'),
            }[kind]
            slim = dict(type=kind, **{key: event[key] for key in keys if key in event})
            if kind == 'diff':
                paths = event.get('paths') or ([event['path']] if event.get('path') else [])
                # Retain only a count from aggregate unified diffs, never patch content.
                patch = str(event.get('diff') or event.get('content') or '')
                slim['file_count'] = len(set(paths)) if paths else len(re.findall(r'^diff --git ', patch, re.M))
                if not slim['file_count']:
                    slim['file_count'] = len(re.findall(r'^\+\+\+ (?!/dev/null)', patch, re.M))
            elif kind == 'test' and not event.get('name'):
                slim['name'] = event.get('framework') or 'test'
                slim['result'] = ' '.join('%s=%s' % (key, event[key]) for key in ('passed', 'failed', 'skipped', 'exit_code') if key in event)
        elif kind in WANTED:
            slim = {key: event.get(key) for key in ('type', 'content', 'name', 'input', 'is_error', 'duration_ms', 'status', 'request_id', 'details', 'approved')
                    if key in event}
        else:
            return
        if codex and kind in ('message_start', 'message_delta', 'message_end'):
            slim['message_id'] = event.get('message_id')
        if slim['type'] == 'tool_result':
            slim.pop('content', None)           # tool output is never projected
        slim['at'] = self.clock()
        self._buffer.append(slim)

    # ------------------------------------------------------------------ files
    def _result_path(self, label):
        return self.directory / (label + '.result.json')

    def _write_result(self, label, status, reason='', *, session_id='', task_id='', started=None, codex=None):
        ended = _iso()
        result = {'label': label, 'status': status, 'reason': sanitize(reason),
                  'exit_code': 0 if status == 'complete' else 1,
                  'session_id': session_id or '', 'task_id': task_id or '',
                  'started': started or ended, 'ended': ended}
        if codex is not None:
            result.update(codex)
        path = self._result_path(label)
        temporary = path.with_name(path.name + '.tmp')
        temporary.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8', newline='')
        os.replace(temporary, path)             # run.sh must never read half a file
        return result

    def _pending(self):
        found = []
        try:
            for p in self.directory.iterdir():
                if p.suffix == '.json' and not p.name.startswith('.') and not p.name.endswith('.result.json'):
                    try:                        # run.sh may withdraw a request between listing and stat
                        if p.is_file():
                            found.append((p.stat().st_mtime_ns, p.name, p))
                    except OSError:
                        continue
        except OSError:
            return []
        return [p for _, _, p in sorted(found, key=lambda item: item[:2])]

    # ------------------------------------------------------------------ poll
    def poll(self):
        """Advance the single running request, or start the next pending one. Returns result dicts written."""
        if getattr(self.core, '_closed', False):
            return []
        self._heartbeat()
        if not self._poll_lock.acquire(blocking=False):
            return []
        try:
            if self._run is not None:
                return self._advance()
            return self._start_next()
        finally:
            self._poll_lock.release()
            self._heartbeat()                   # a slow launch must not look like a dead dispatcher

    def _heartbeat(self, busy=None):
        """Tell run.sh that this dispatcher is alive: requests/.dispatcher.json, rewritten on every poll.

        Also called before the slow steps of a launch (git status, preparing the conversation, sending),
        with ``busy=True``, so a long guard never looks like a dead dispatcher.

        A GUI that is open but runs older code (or hangs) has a live pid in workspace.lock and no fresh
        heartbeat; run.sh then uses the direct path instead of waiting for a result that never comes.
        Never raises.
        """
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.directory / HEARTBEAT
            temporary = path.with_name('%s.%d.%d.tmp' % (HEARTBEAT, os.getpid(), threading.get_ident()))
            if busy is None:
                busy = self._run is not None
            temporary.write_text(json.dumps({'pid': os.getpid(), 'at': _iso(), 'busy': bool(busy)}),
                                 encoding='utf-8', newline='')
            os.replace(temporary, path)
        except Exception:
            pass

    def _start_next(self):
        for path in self._pending():
            try:
                key = (path.name, path.stat().st_mtime_ns)
            except OSError:
                continue
            if key in self._seen:
                continue
            try:
                answered = self._result_path(path.name[:-len('.json')]).stat().st_mtime_ns >= key[1]
            except OSError:
                answered = False
            if answered:                        # e.g. the workspace restarted before run.sh removed its request
                self._seen.add(key)
                continue
            try:
                outcome = self._begin(path, key)
            except Exception as exc:            # decided here, so a bad request is not retried every second
                label = path.name[:-len('.json')]
                outcome = self._reject(label, 'prepare-failed', sanitize(str(exc)) or type(exc).__name__)
            if outcome == 'retry':
                continue
            self._seen.add(key)
            return outcome or []                # one request per poll
        return []

    def _reject(self, label, code, text, started=None, **ids):
        return [self._write_result(label, 'rejected', code + ': ' + text, started=started, **ids)]

    def _begin(self, path, key):
        label = path.name[:-len('.json')]
        started = _iso()
        try:
            age = time.time() - path.stat().st_mtime
        except OSError:
            return 'retry'                      # withdrawn by run.sh meanwhile
        if not LABEL.fullmatch(label) or label.endswith('.result'):
            return self._reject(label, 'bad-label', 'label 只接受 [A-Za-z0-9._-]{1,64}', started)
        try:
            request = json.loads(path.read_text(encoding='utf-8-sig'))
            if not isinstance(request, dict):
                raise ValueError('not an object')
        except (OSError, ValueError):
            if age < PARTIAL_JSON_SECONDS:
                return 'retry'
            return self._reject(label, 'bad-request', '請求檔不是有效的 JSON 物件', started)
        if str(request.get('label', label)) != label:
            return self._reject(label, 'bad-request', '請求內的 label 與檔名不一致', started)
        agent = request.get('agent', self.default_agent)
        try:
            provider = self.core.provider(agent)
        except (ValueError, TypeError):
            provider = None
        if provider not in ('local', 'codex'):
            return self._reject(label, 'bad-request', 'agent 必須是 Hermes 或 Codex instance', started)
        if type(request.get('use_playbook', True)) is not bool:
            return self._reject(label, 'bad-request', 'use_playbook 必須是布林值', started)
        limits = playbooks.load(self.core, agent)['limits']
        timeout = request.get('timeout_seconds', limits['timeout_seconds']) if provider == 'codex' else None
        if timeout is not None:
            timeout = _positive(timeout, 2147483647)
            if timeout is None:
                return self._reject(label, 'bad-request', 'timeout_seconds 必須是正整數', started)
        prompt = request.get('prompt')
        budget_value, turns_value = request.get('run_budget'), request.get('max_turns')
        if provider == 'local':
            if budget_value in (None, ''): budget_value = limits['run_budget']
            if turns_value in (None, ''): turns_value = limits['max_turns']
        budget = None if budget_value in (None, '') else _positive(budget_value, MAX_BUDGET)
        turns = None if turns_value in (None, '') else _positive(turns_value, MAX_TURNS)
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 20000:
            return self._reject(label, 'bad-request', 'prompt 必須是非空字串（上限 20000 字）', started)
        if (budget_value not in (None, '') and budget is None) or \
           (turns_value not in (None, '') and turns is None):
            return self._reject(label, 'bad-request', 'run_budget／max_turns 必須是範圍內的正整數', started)
        wait = (timeout if provider == 'codex' else budget or 600) + EXPIRY_SECONDS
        if age > wait:
            return self._reject(label, 'expired', '請求已過期（run.sh 已不再等待）', started)
        try:
            given = Path(str(request.get('worktree') or ''))
            worktree = given.resolve() if given.is_absolute() else None
        except (OSError, ValueError):
            worktree = None
        if worktree is None or not worktree.is_dir():
            return self._reject(label, 'no-worktree', 'worktree 必須是存在的絕對路徑：' + str(request.get('worktree')), started)
        relative = request.get('spec') if provider == 'codex' else request.get('briefs')
        relative = relative.strip() if isinstance(relative, str) else ''
        candidate = worktree / relative if relative else None
        target = candidate if provider == 'codex' or candidate is None else candidate / 'PROGRESS.md'
        try:
            inside = bool(target and not Path(relative).is_absolute() and target.resolve().is_relative_to(worktree))
        except (OSError, ValueError):
            inside = False
        if provider == 'codex':
            if not inside or not target.is_file():
                return self._reject(label, 'no-spec', 'spec 必須是 worktree 內存在的相對檔案路徑', started)
        else:
            if relative and not inside:
                return self._reject(label, 'bad-request', 'briefs 必須是 worktree 內的相對路徑', started)
            if target is None or not target.is_file():
                return self._reject(label, 'no-progress', '找不到 %s/PROGRESS.md' % (relative or '(未指定)'), started)
        allow_dirty = request.get('allow_dirty') is True or str(request.get('allow_dirty')).lower() in ('1', 'true')
        self._heartbeat(True)                   # git status can take a while on a big tree
        dirty = self._dirty(worktree)
        if dirty is None:
            return self._reject(label, 'git-failed', '無法執行 git status', started)
        if dirty and not allow_dirty:
            return self._reject(label, 'dirty-worktree', '工作樹不乾淨：' + _clip(dirty, 200), started)
        adapter = self.core.adapters.get(agent)
        state = getattr(adapter, 'state', 'Disconnected')
        if adapter is not None and state in ('Error', 'Disconnected'):
            # A failed earlier run leaves the adapter in Error until someone reconnects; try that once here.
            # Busy / Connecting are never touched.
            self._heartbeat(True)
            try:
                self.core.connect(agent)
            except Exception:
                pass
            adapter = self.core.adapters.get(agent)
            state = getattr(adapter, 'state', 'Disconnected')
        if adapter is None or state != 'Connected':
            return self._reject(label, 'local-not-connected' if provider == 'local' else 'agent-not-connected', '協作站的 %s agent 目前不是 Connected（狀態 %s）' % (agent, state), started)
        return self._launch(label, request, worktree, prompt, budget, turns, started, timeout=timeout)

    @staticmethod
    def _dirty(worktree):
        """Porcelain output ('' = clean), or None when git could not tell."""
        try:
            done = subprocess.run(['git', '-C', str(worktree), 'status', '--porcelain'], stdin=subprocess.DEVNULL,
                                  capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60,
                                  creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except (OSError, subprocess.TimeoutExpired):
            return None
        return done.stdout.strip() if done.returncode == 0 else None

    # ------------------------------------------------------------------ launch
    def _launch(self, label, request, worktree, prompt, budget, turns, started, *, timeout=None):
        core, agent = self.core, request.get('agent', self.default_agent)
        provider = core.provider(agent)
        task_id = ''
        try:
            self._heartbeat(True)
            if request.get('use_playbook', True):
                prompt = playbooks.compose_prompt(core, agent, prompt)
            target = _norm(worktree)
            project = next((p for p in core.list_projects() if p.get('repo_path') and _norm(p['repo_path']) == target), None)
            if project is None:
                project = core.create_project(worktree.name or 'hermes', str(worktree))
            core.select_agent_project(agent, project['id'])
            self._heartbeat(True)
            task = core.prepare_conversation(agent, fresh=True)
            task_id = task['id']
            try:
                core.update_task(task_id, title=sanitize(core.agent_name(agent) + ' · ' + label))
            except Exception:
                pass                              # a missing nicer title is not a reason to refuse
            adapter = core.adapters[agent]
            monitor_root = request.get('monitor_root')
            run = {'agent': agent, 'provider': provider, 'label': label, 'worktree': str(worktree), 'task_id': task_id, 'started': started, 'adapter': adapter, 'saved': {},
                   'budget': budget or _positive(adapter.settings.get('run_budget', 600), MAX_BUDGET) or 600,
                   'monitor': MonitorProjection(label, monitor_root if isinstance(monitor_root, str) else '', provider),
                   'timeout': timeout, 'paused': 0.0, 'pause_start': None, 'approvals': set(), 'approval_seen': set(),
                   'session_id': '', 'operation': None, 'end': None, 'end_deferred': False, 'errors': [],
                   'result_pending': None, 'flushed': False, 'turn_status': None, 'messages': 0, 'message_ids': set(),
                   'last_state': None, 'idle_transition': False, 'last_activity': self.clock()}
        except Exception as exc:
            return self._reject(label, 'prepare-failed', sanitize(str(exc)) or type(exc).__name__, started, task_id=task_id)
        # Everything that can fail is built above; from here on the run slot, the tap filter and the settings
        # override are all undone by _clear() on any exception.
        self._buffer.clear()
        self._run = run
        self._active_task = task_id
        try:
            # A request carries its own limits for this run only. The adapter reads run_budget/max_turns from its
            # settings dict when it builds argv, which is also what the user's saved agent config feeds; the saved
            # config must not change, so the override is a temporary edit of the live dict, undone when the run ends.
            for key, value in ((('run_budget', budget), ('max_turns', turns)) if provider == 'local' else ()):
                if value is not None:
                    run['saved'][key] = adapter.settings.get(key, _MISSING)
                    adapter.settings[key] = value
            self._heartbeat(True)
            run['t0'] = self.clock()
            run['operation'] = core.send_message(agent, prompt)
            if provider == 'codex':
                identity = getattr(adapter, 'active_operation_id', None)
                if callable(identity):
                    run['operation'] = identity()
        except Exception as exc:
            self._clear(run)
            return self._reject(label, 'send-failed', sanitize(str(exc)) or type(exc).__name__, started, task_id=task_id)
        current = core.agent_task(agent) or {}
        run['session_id'] = current.get(agent + '_session', '') or ''
        return []

    def _release(self, run):
        """Undo what a run changed outside the store: the tap filter and the settings override."""
        self._active_task = None
        for key, value in list(run['saved'].items()):
            if value is _MISSING:
                run['adapter'].settings.pop(key, None)
            else:
                run['adapter'].settings[key] = value
        run['saved'] = {}
        self._buffer.clear()

    def _clear(self, run):
        self._release(run)
        if self._run is run:
            self._run = None

    # ------------------------------------------------------------------ progress
    def _advance(self):
        run = self._run
        if run['result_pending'] is not None:   # the run is over; only its result file could not be written
            return self._finish(run, *run['result_pending'])
        monitor = run['monitor']
        events = []
        while True:
            try:
                events.append(self._buffer.popleft())
            except IndexError:
                break
        for event in events:
            kind = event['type']
            if run['provider'] == 'codex' and kind in ('approval', 'approval_response'):
                request_id = str(event.get('request_id') or '')
                at = max(run['t0'], event['at'])
                if request_id and kind == 'approval' and request_id not in run['approval_seen']:
                    run['approval_seen'].add(request_id)
                    if not run['approvals']:
                        run['pause_start'] = at
                    run['approvals'].add(request_id)
                    summary = _clip(event.get('details') or event.get('content') or '', 160)
                    monitor.timeline('APPROVAL_NEEDED', request_id + ' ' + summary)
                elif request_id in run['approvals'] and kind == 'approval_response':
                    run['approvals'].remove(request_id)
                    monitor.timeline('APPROVAL_RESOLVED', request_id)
                    if not run['approvals']:
                        run['paused'] += at - run['pause_start']
                        run['pause_start'] = None
            if kind == 'error':
                run['errors'].append(sanitize(str(event.get('content') or '')))
            if run['provider'] == 'codex':
                if kind == 'state':
                    state = event.get('state')
                    run['idle_transition'] = state == 'Connected' and (run['idle_transition'] or run['last_state'] == 'Busy')
                    run['last_state'] = state
                elif kind in ('message_start', 'message_delta', 'message_end'):
                    message_id = event.get('message_id')
                    if message_id and message_id not in run['message_ids']:
                        run['message_ids'].add(message_id)
                        run['messages'] += 1
                elif kind == 'event' and run['turn_status'] is None:
                    run['turn_status'] = str(event.get('status') or event.get('summary', 'Turn unknown')[5:])
            elif kind == 'message_end':
                status = 'complete' if event.get('status') not in ('interrupted', 'cancelled') else 'interrupted'
                run['end'] = status
            monitor.event(event, 0 if (kind == 'message_end' and run['end'] == 'complete') else 1)
        if run['provider'] == 'codex':
            terminal = run['turn_status']
            if terminal is not None:
                status = 'complete' if terminal == 'completed' else 'interrupted' if terminal in ('interrupted', 'cancelled') else 'error'
                reason = (run['errors'][-1] if run['errors'] else 'Turn ' + terminal) if status == 'error' else ''
                return self._finish(run, status, reason)
            if (run['idle_transition'] and not run['approvals'] and
                    getattr(run['adapter'], 'state', None) == 'Connected' and
                    self.clock() - run['last_activity'] > 5):
                run['turn_status'] = 'completed'
                monitor.end_turn('completed', True, inferred=True)
                return self._finish(run, 'complete', '')
        if run['end'] == 'complete':
            return self._finish(run, 'complete', '')
        if run['end'] is not None:
            # The adapter reports a failed run as message_end(interrupted) and then an error event; give that
            # event one poll to arrive before deciding between "stopped" and "failed".
            if run['errors']:
                return self._finish(run, 'error', run['errors'][-1])
            if run['end_deferred']:
                return self._finish(run, 'interrupted', self.core.agent_name(run['agent']) + ' 工作被中止')
            run['end_deferred'] = True
            return []
        elapsed = self.clock() - run['t0'] - run['paused']
        if run['pause_start'] is not None:
            elapsed -= self.clock() - run['pause_start']
        timeout = run['timeout'] if run['timeout'] is not None else run['budget'] + GRACE_SECONDS
        if elapsed > timeout:
            self._stop(run)
            monitor.flush()
            monitor.say('[ERROR] 協作站等候逾時，已要求停止此工作')
            return self._finish(run, 'interrupted', '超過 %d 秒有效執行時間仍未收到完成事件，已要求停止' % timeout)
        return []

    @staticmethod
    def _stop(run):
        adapter = run['adapter']
        try:
            owned = getattr(adapter, 'stop_if_owned', None)
            if callable(owned):
                owned(run['operation'])
            else:
                adapter.stop()
        except Exception:
            pass

    def _finish(self, run, status, reason):
        """Answer run.sh. The result file is written (3 tries) BEFORE the run slot is freed; if it still fails the
        run stays in ``_run`` marked result_pending and the next poll tries again, so run.sh is not left waiting."""
        if run['provider'] == 'codex':
            if run['turn_status'] is None:
                run['turn_status'] = 'interrupted' if status == 'interrupted' else 'failed'
            run['monitor'].end_turn(run['turn_status'], status == 'complete')
        if not run['flushed']:
            run['monitor'].flush()
            run['flushed'] = True
        self._release(run)                      # the Hermes run itself is over; give the settings back now
        session_id = run['session_id']
        try:
            session_id = (self.core.get_task(run['task_id']) or {}).get(self.agent + '_session', session_id) or session_id
        except Exception:
            pass
        result = None
        for attempt in range(3):
            try:
                result = self._write_result(run['label'], status, reason, session_id=session_id,
                                            task_id=run['task_id'], started=run['started'],
                                            **({'codex': {'turn_status': run['turn_status'], 'messages': run['messages']}}
                                               if run['provider'] == 'codex' else {}))
                break
            except OSError:
                if attempt < 2:
                    time.sleep(0.5)
        if result is None:
            run['result_pending'] = (status, reason)
            return []
        self._clear(run)
        return [result]

    def close(self):
        """Called by Core.close(): a request still running is answered `interrupted` so run.sh does not hang."""
        got = self._poll_lock.acquire(timeout=5)
        try:
            run = self._run
            if run is not None:
                self._stop(run)
                try:
                    run['monitor'].flush()
                    run['monitor'].say('[ERROR] 協作站已關閉，此工作被中止')
                    self._finish(run, 'interrupted', '協作站關閉時此工作仍在執行')
                except Exception:
                    self._clear(run)
            try:
                self.core._event_taps.remove(self._on_event)
            except ValueError:
                pass
            try:
                (self.directory / HEARTBEAT).unlink()   # run.sh should see a closed workspace at once
            except OSError:
                pass
        finally:
            if got:
                self._poll_lock.release()


_MISSING = object()
