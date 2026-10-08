"""Contract tests use explicit transport substitutes. --live uses the official CLI.

Run: python -m unittest discover -s tests -p test_claude.py
     python tests/test_claude.py --live <native-claude-exe>
"""
import json
import sys
import threading
import time
import unittest
import tempfile
import struct
import zlib
import io
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from acw.adapters.claude import ClaudeAdapter
from acw.security import sanitize


class ClaudeContractTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.adapter = ClaudeAdapter(lambda kind, **data: self.events.append((kind, data)), 'claude.exe')

    def stream(self, event):
        self.adapter._handle({'type': 'stream_event', 'event': event})

    def test_mcp_inventory_is_unknown_before_backend_reports_it(self):
        inventory = self.adapter.diagnostics()['mcp_inventory']
        self.assertEqual(inventory['status'], 'Not yet reported by backend')
        self.assertFalse(inventory['tool_execution_verified'])

    def test_session_mcp_is_opt_in_and_never_changes_permissions(self):
        baseline=self.adapter._argv()
        self.assertFalse(any(arg.startswith('--mcp-config') for arg in baseline))
        self.adapter.settings['session_mcp_servers']={'fixture':{'command':str(Path(sys.executable).resolve()),'args':['fixture.py']}}
        argv=self.adapter._argv()
        self.assertIn('--strict-mcp-config',argv)
        self.assertIn('--tools=',argv)
        self.assertEqual(json.loads(next(arg.split('=',1)[1] for arg in argv if arg.startswith('--mcp-config=')))['mcpServers']['fixture']['args'],['fixture.py'])
        self.assertFalse(any('allowed' in arg or 'permission-mode' in arg or 'skip-permissions' in arg for arg in argv))
        self.assertEqual(self.adapter.diagnostics()['session_mcp_servers'],['fixture'])

    def test_session_mcp_rejects_env_credentials_and_remote_config(self):
        self.adapter.settings['session_mcp_servers']={'fixture':{'command':str(Path(sys.executable).resolve()),'env':{'token':'CANARY'}}}
        with self.assertRaises(ValueError):self.adapter._argv()
        self.adapter.settings['session_mcp_servers']={'fixture':{'url':'https://invalid.example'}}
        with self.assertRaises(ValueError):self.adapter._argv()

    def test_mcp_inventory_projects_metadata_without_claiming_runtime_execution(self):
        self.adapter._handle({'type': 'system', 'subtype': 'init',
            'mcp_servers': [{'name': 'fixture-mcp', 'status': 'needs-auth',
                             'url': 'PRIVATE_ENDPOINT_CANARY', 'token': 'SECRET_CANARY'}],
            'tools': ['Read', 'mcp__fixture__read']})
        inventory = self.adapter.diagnostics()['mcp_inventory']
        self.assertEqual(inventory['servers'], [{'name': 'fixture-mcp', 'status': 'needs-auth'}])
        self.assertEqual(inventory['tool_names'], ['mcp__fixture__read'])
        self.assertTrue(inventory['snapshot_only'])
        self.assertFalse(inventory['tool_execution_verified'])
        self.assertEqual(inventory['connection_state'], 'Disconnected')
        self.assertNotIn('PRIVATE_ENDPOINT_CANARY', json.dumps(inventory))
        self.assertNotIn('SECRET_CANARY', json.dumps(inventory))

    def test_stream_and_full_message_are_not_duplicated(self):
        self.stream({'type': 'message_start', 'message': {'id': 'm1'}})
        self.stream({'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': 'Hello'}})
        self.stream({'type': 'message_stop'})
        self.adapter._handle({'type': 'assistant', 'message': {'id': 'm1', 'content': [{'type': 'text', 'text': 'Hello'}]}})
        self.assertEqual([d['content'] for k,d in self.events if k == 'message_delta'], ['Hello'])
        self.assertEqual([d['content'] for k,d in self.events if k == 'message_end'], ['Hello'])

    def test_models_and_efforts_only_come_from_backend(self):
        self.adapter._discover({'models': [{'value': 'backend-real', 'supportsEffort': True,
                                           'supportedEffortLevels': ['custom-effort']},
                                          {'value': 'no-effort', 'supportsEffort': False}]})
        self.assertEqual(self.adapter.list_models()[0]['id'], 'backend-real')
        self.assertEqual(self.adapter.list_efforts('backend-real'), ['custom-effort'])
        self.assertEqual(self.adapter.list_efforts('no-effort'), [])
        self.adapter._discover({})
        self.assertFalse(self.adapter.capabilities.supports_model_selection)
        self.assertFalse(self.adapter.capabilities.supports_effort)

    def test_thinking_and_credentials_never_reach_raw_callback(self):
        self.stream({'type': 'content_block_delta', 'delta': {'type': 'thinking_delta', 'thinking': 'PRIVATE_THOUGHT'}})
        self.adapter._handle({'type': 'event', 'token': 'SECRET_VALUE'})
        result = json.dumps(self.events)
        self.assertNotIn('PRIVATE_THOUGHT', result)
        self.assertNotIn('SECRET_VALUE', result)
        self.assertIn('redaction', result)

    def test_tool_closure_does_not_claim_execution_completed(self):
        self.adapter._handle({'type': 'assistant', 'message': {'content': [
            {'type': 'tool_use', 'id': 't1', 'name': 'Bash', 'input': {'command': 'echo fixture'}}]}})
        self.stream({'type': 'content_block_stop', 'index': 0})
        self.assertFalse(any(k == 'tool_result' for k,d in self.events))
        self.adapter._handle({'type': 'user', 'message': {'content': [
            {'type': 'tool_result', 'tool_use_id': 't1', 'content': 'fixture'}]},
            'tool_use_result': {'stdout': 'fixture', 'stderr': '', 'exitCode': 0}})
        command = [d for k,d in self.events if k == 'command'][-1]
        self.assertEqual(command['exit_code'], 0)
        self.assertEqual(command['stdout'], 'fixture')

    def test_permission_is_never_automatically_approved(self):
        sent = []
        self.adapter._write = sent.append
        self.adapter._handle({'type': 'control_request', 'request_id': 'approval1', 'request': {
            'subtype': 'can_use_tool', 'tool_name': 'Bash', 'input': {'command': 'echo fixture'}}})
        self.assertEqual(sent, [])
        self.assertTrue(any(k == 'approval' for k,d in self.events))
        self.adapter.approve('approval1', False)
        self.assertEqual(sent[-1]['response']['response']['behavior'], 'deny')

    def test_stop_only_sends_official_interrupt(self):
        sent = []
        self.adapter._request = lambda request: sent.append(request)
        self.adapter.state = 'Busy'
        self.assertTrue(self.adapter.stop())
        self.assertEqual(sent, [{'subtype': 'interrupt'}])
        self.assertEqual(self.adapter.state, 'Busy')  # drain result before another prompt
        self.adapter._handle({'type': 'result', 'is_error': False})
        self.assertEqual(self.adapter.state, 'Connected')

    def test_native_aborted_streaming_result_finishes_requested_stop(self):
        self.adapter.state='Busy'
        self.adapter._stopping=True
        self.adapter._idle.clear()
        self.adapter._handle({'type':'result','is_error':True,
            'subtype':'error_during_execution','terminal_reason':'aborted_streaming',
            'errors':['Cancellation diagnostic']})
        self.assertEqual(self.adapter.state,'Connected')
        self.assertTrue(self.adapter._idle.is_set())
        self.assertFalse(any(k=='error' for k,d in self.events))
        self.assertTrue(any(k=='event' and d.get('status')=='interrupted' for k,d in self.events))

    def test_nonfatal_stderr_does_not_overwrite_inference_status(self):
        process=SimpleNamespace(stderr=io.StringIO('SessionEnd hook cancelled\n'))
        self.adapter._process=process
        self.adapter._read_stderr(process)
        self.assertEqual(self.adapter.last_error,'')
        self.assertEqual(self.adapter._last_stderr,'SessionEnd hook cancelled')
        self.assertTrue(any(k=='event' and d.get('stream')=='stderr' for k,d in self.events))

    def test_resume_rejects_option_injection(self):
        with self.assertRaises(ValueError):
            self.adapter.resume_session('--dangerously-skip-permissions')

    def test_attachment_scope_redaction_and_image_wire_format(self):
        with tempfile.TemporaryDirectory(prefix='acw-claude-attachments-') as folder:
            self.adapter.set_project(folder)
            root = Path(folder)
            text = root/'fixture.txt'
            text.write_text('password=NOT_FOR_UPLOAD\nblue square', encoding='utf-8')
            image = root/'fixture.png'
            image.write_bytes(b'\x89PNG\r\n\x1a\nOFFLINE_TEST_IMAGE')
            blocks = self.adapter._prepare_content('Original prompt', [text,image])
            self.assertEqual(blocks[0]['text'], 'Original prompt')
            self.assertNotIn('NOT_FOR_UPLOAD', blocks[1]['text'])
            self.assertEqual(blocks[2]['source']['media_type'], 'image/png')
            self.assertEqual(blocks[2]['source']['type'], 'base64')
            raw = self.adapter._safe_raw({'type':'user','message':{'content':blocks}})
            self.assertNotEqual(raw['message']['content'][2]['source']['data'], blocks[2]['source']['data'])
            secret = root/'auth.json'
            with self.assertRaises(PermissionError):
                self.adapter._prepare_content('', [secret])
            with self.assertRaises(PermissionError):
                self.adapter._prepare_content('', [root.parent/'outside.txt'])

    def test_native_sessions_are_explicit_project_scoped_and_do_not_resume(self):
        """Public SDK contract substitute only; never accesses native user sessions."""
        with tempfile.TemporaryDirectory(prefix='acw-native-session-contract-') as folder:
            native_id = '11111111-2222-4333-8444-555555555555'
            calls = []
            def list_sessions(directory=None, limit=None, offset=0, include_worktrees=True):
                calls.append((directory,limit,offset,include_worktrees))
                return [SimpleNamespace(session_id=native_id,cwd=folder,
                    summary='password=DO_NOT_RECORD',first_prompt='PRIVATE_FIRST_PROMPT',
                    file_size=100,last_modified=123),
                    SimpleNamespace(session_id='aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee',
                    cwd=str(Path(folder).parent),summary='different project')]
            sdk = SimpleNamespace(list_sessions=list_sessions)
            self.adapter._session_sdk = sdk
            self.adapter.set_project(folder)
            self.adapter.session_id = '66666666-7777-4888-8999-000000000000'
            self.assertEqual(self.adapter.list_sessions(), [])
            self.assertEqual(calls, [])
            native = self.adapter.list_sessions(native=True,limit=10,offset=0)
            self.assertEqual(calls, [(str(Path(folder).resolve()),10,0,False)])
            self.assertEqual(len(native),1)
            self.assertEqual(native[0]['id'],native_id)
            self.assertEqual(native[0]['source'],'native')
            self.assertNotIn('DO_NOT_RECORD',json.dumps(native))
            self.assertNotIn('PRIVATE_FIRST_PROMPT',json.dumps(native))
            self.assertEqual(self.adapter.session_id,'66666666-7777-4888-8999-000000000000')
            self.assertEqual(self.adapter.state,'Disconnected')
            self.assertEqual(self.events,[])

    def test_native_history_requires_selected_session_and_strips_hidden_content(self):
        with tempfile.TemporaryDirectory(prefix='acw-native-history-contract-') as folder:
            native_id = '11111111-2222-4333-8444-555555555555'
            calls = []
            info = SimpleNamespace(session_id=native_id,cwd=folder,summary='fixture',file_size=150)
            def list_sessions(directory=None,limit=None,offset=0,include_worktrees=True): return [info]
            def get_session_info(session_id,directory=None):
                calls.append(('info',session_id,directory)); return info
            def get_session_messages(session_id,directory=None,limit=None,offset=0):
                calls.append(('history',session_id,directory,limit,offset))
                return [SimpleNamespace(type='assistant',uuid='original-message-id',session_id=native_id,
                    message={'role':'assistant','content':[
                        {'type':'thinking','thinking':'PRIVATE_REASONING'},
                        {'type':'text','text':'Original answer\npassword=SECRET_HISTORY_VALUE'}]})]
            self.adapter._session_sdk = SimpleNamespace(list_sessions=list_sessions,
                get_session_info=get_session_info,get_session_messages=get_session_messages)
            self.adapter.set_project(folder)
            with self.assertRaises(PermissionError): self.adapter.get_history(native_id,native=True)
            self.assertEqual(calls,[])
            self.adapter.list_sessions(native=True)
            history = self.adapter.get_history(native_id,native=True,limit=20,offset=0)
            self.assertEqual(history[0]['id'],'original-message-id')
            self.assertEqual(history[0]['session_id'],native_id)
            self.assertIn('Original answer',history[0]['content'])
            self.assertNotIn('PRIVATE_REASONING',json.dumps(history))
            self.assertNotIn('SECRET_HISTORY_VALUE',json.dumps(history))
            self.assertEqual(calls[-1],('history',native_id,str(Path(folder).resolve()),20,0))
            count=len(calls)
            info.file_size=33*1024*1024
            with self.assertRaises(ValueError): self.adapter.get_history(native_id,native=True)
            self.assertEqual(len(calls),count+1)  # metadata refreshed; huge transcript never read
            self.adapter.set_project(str(Path(folder).parent))
            with self.assertRaises(PermissionError): self.adapter.get_history(native_id,native=True)
            self.assertEqual(self.events,[])

    def test_missing_or_old_native_sdk_is_explicitly_unavailable(self):
        with tempfile.TemporaryDirectory(prefix='acw-native-missing-sdk-') as folder:
            self.adapter.set_project(folder)
            with patch('acw.adapters.claude._NodeSessionSDK',side_effect=ImportError('Test fixture: SDK unavailable')), patch('acw.adapters.claude.importlib.import_module',side_effect=ModuleNotFoundError("No module named 'mcp'")):
                with self.assertRaisesRegex(NotImplementedError,'optional official'):
                    self.adapter.list_sessions(native=True)
            self.assertIn('mcp',self.adapter.native_sessions_error)
            with patch('acw.adapters.claude._NodeSessionSDK',side_effect=ImportError('Test fixture: SDK unavailable')), patch('acw.adapters.claude.importlib.import_module',return_value=SimpleNamespace(list_sessions=lambda:[])):
                with self.assertRaisesRegex(NotImplementedError,'bounded public list_sessions'):
                    self.adapter.list_sessions(native=True)
            self.assertEqual(self.adapter.state,'Disconnected')

    def test_real_auth_error_fixture_survives_core_mapping(self):
        """Replay only the new, isolated official CLI failure; no network invocation."""
        fixture = Path(__file__).resolve().parents[1] / 'evidence' / 'claude-live-events.jsonl'
        if not fixture.is_file():
            self.skipTest('Run the opt-in live probe to create this sanitized owned-session fixture')
        from acw.core import WorkspaceCore
        rows = [json.loads(line) for line in fixture.read_text(encoding='utf-8').splitlines()]
        raw = [e['raw'] for e in rows if e['type']=='raw' and isinstance(e.get('raw'),dict)]
        failure = next((e for e in raw if e.get('type')=='result' and e.get('is_error')), None)
        if not failure:
            self.skipTest('Current live probe did not return an authentication failure')
        with tempfile.TemporaryDirectory(prefix='acw-claude-replay-') as folder:
            core = WorkspaceCore(Path(folder)/'data')
            try:
                core.set_adapter('claude', self.adapter)
                project = core.create_project('Claude replay fixture', folder)
                core.select_project(project['id'])
                task = core.create_task('Replay official authentication error')
                self.adapter._handle(failure)
                saved = core.store.query('SELECT * FROM messages WHERE task_id=? AND agent=?', (task['id'],'claude'))
                self.assertTrue(any('OAuth session expired' in m['content'] for m in saved))
                self.assertEqual(core.get_task(task['id'])['claude_session'], failure['session_id'])
                self.assertEqual(self.adapter.state, 'Error')
                self.assertFalse(any(m['status']=='streaming' for m in saved))
                self.assertTrue(core.events(agent='claude'))
            finally:
                core.store.close()


def minimal_message_check(executable):
    """One explicit no-tools inference check; no login, retry, or auth-file access."""
    root = Path(__file__).resolve().parents[1]
    target = root/'tests'/'sandbox-claude'
    target.mkdir(parents=True,exist_ok=True)
    events=[]
    def emit(kind,**payload):
        events.append({'type':kind,**sanitize(payload)})
        if kind in ('state','error'): print(json.dumps({'type':kind,**sanitize(payload)}),flush=True)
    adapter=ClaudeAdapter(emit,executable)
    report={'scope':'single authorized no-tools inference check','cwd':str(target),
            'prompt':'Isolated acceptance test. Do not use any tools. Reply exactly ACW_CLAUDE_POSTLOGIN_OK.',
            'status':'BLOCKED','timestamp':time.time()}
    try:
        adapter.set_project(str(target)); adapter.create_session(); adapter.connect()
        report['handshake']='PASS'
        adapter.send_message(report['prompt'])
        if not adapter._idle.wait(50):
            report['error']='Inference timeout; no retry requested'
            adapter.stop(); adapter._idle.wait(15)
        else:
            report['error']=adapter.last_error
            report['status']='PASS' if adapter.state=='Connected' and any(
                e['type']=='message_end' and e.get('content','').strip()=='ACW_CLAUDE_POSTLOGIN_OK'
                for e in events) else 'BLOCKED'
        report['session_id']=adapter.session_id
        report['backend_cwd']=adapter.backend_cwd
    except Exception as exc: report['error']=sanitize(str(exc))
    finally:
        try: adapter.disconnect()
        except Exception as exc: report['disconnect_error']=sanitize(str(exc))
        report['last_backend_error']=adapter.last_error
        report['event_counts']={kind:sum(e['type']==kind for e in events) for kind in sorted({e['type'] for e in events})}
        stem='claude-message-check-'+str(time.time_ns())
        folder=root/'evidence'; folder.mkdir(exist_ok=True)
        (folder/(stem+'.json')).write_text(json.dumps(sanitize(report),indent=2),encoding='utf-8')
        (folder/(stem+'-events.jsonl')).write_text(''.join(json.dumps(sanitize(e))+'\n' for e in events),encoding='utf-8')
        print(json.dumps({'report':str(folder/(stem+'.json')),**sanitize(report)},indent=2),flush=True)
    return report


def attachment_message_check(executable):
    """Real text+image acceptance, using deterministic nonsensitive test assets."""
    root=Path(__file__).resolve().parents[1]
    target=root/'tests'/'sandbox-claude'; target.mkdir(parents=True,exist_ok=True)
    text_file=target/'acw-attachment-fixture.txt'
    image_file=target/'acw-blue-fixture.png'
    text_file.write_text('ACW_ATTACHMENT_TEXT_OK\n',encoding='utf-8')
    def chunk(kind,data):
        return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',64,64,8,2,0,0,0))
    png+=chunk(b'IDAT',zlib.compress((b'\x00'+b'\x00\x00\xff'*64)*64))+chunk(b'IEND',b'')
    image_file.write_bytes(png)
    events=[]
    adapter=ClaudeAdapter(lambda kind,**data:events.append({'type':kind,**sanitize(data)}),executable)
    report={'scope':'new isolated no-tools official text/image attachment test','cwd':str(target),
            'attachments':[str(text_file),str(image_file)],'status':'BLOCKED'}
    try:
        adapter.set_project(str(target));adapter.create_session();adapter.connect()
        prompt='Isolated attachment acceptance test. Do not use any tools. Repeat the marker in the attached text and state the single solid color of the attached image.'
        report['prompt']=prompt
        adapter.send_message(prompt,attachments=[text_file,image_file])
        if not adapter._idle.wait(75):
            report['error']='Attachment inference timeout';adapter.stop();adapter._idle.wait(15)
        else:
            answer='\n'.join(e.get('content','') for e in events if e['type']=='message_end')
            report['response']=answer
            report['status']='PASS' if adapter.state=='Connected' and 'ACW_ATTACHMENT_TEXT_OK' in answer and 'blue' in answer.lower() else 'FAIL'
        report['session_id']=adapter.session_id
        report['error']=adapter.last_error
    except Exception as exc:report['error']=sanitize(str(exc))
    finally:
        try:adapter.disconnect()
        except Exception as exc:report['disconnect_error']=sanitize(str(exc))
        report['approval_requests']=sum(e['type']=='approval' for e in events)
        report['tool_calls']=sum(e['type']=='tool_start' for e in events)
        report['stream_deltas']=sum(e['type']=='message_delta' for e in events)
        stem='claude-attachments-'+str(time.time_ns());folder=root/'evidence'
        report['report_path']=str(folder/(stem+'.json'))
        (folder/(stem+'.json')).write_text(json.dumps(sanitize(report),indent=2),encoding='utf-8')
        (folder/(stem+'-events.jsonl')).write_text(''.join(json.dumps(sanitize(e))+'\n' for e in events),encoding='utf-8')
        print(json.dumps(sanitize(report),indent=2),flush=True)
    return report


def live_probe(executable):
    """Owned-session acceptance probe, no permission grants and no real repo reads."""
    root = Path(__file__).resolve().parents[1]
    sandbox = root / 'tests' / 'sandbox-claude'
    sandbox.mkdir(parents=True, exist_ok=True)
    (sandbox / 'acw-fixture.txt').write_text('ACW_READ_FIXTURE_BLUE_42\n', encoding='utf-8')
    evidence = root / 'evidence'
    evidence.mkdir(exist_ok=True)
    events = []
    report = {'backend': 'official Claude Code stream-json', 'cwd': str(sandbox),
              'tests': {}, 'prompts': [], 'no_permission_grants': True}
    event_lock = threading.Lock()
    def emit(kind, **data):
        with event_lock:
            events.append({'type': kind, 'time': time.time(), **sanitize(data)})
        if kind in ('state', 'error'):
            print(json.dumps({'type': kind, **sanitize(data)}), flush=True)
    adapter = ClaudeAdapter(emit, executable)
    def turn(prompt, model=None, effort=None, timeout=90):
        report['prompts'].append(prompt)
        before = len(events)
        adapter.send_message(prompt, model=model, effort=effort)
        deadline = time.monotonic() + timeout
        while not adapter._idle.wait(.1):
            if adapter._approvals:
                report['tests']['permission_request_observed'] = 'PASS (request denied; no automatic approval)'
                for request_id in list(adapter._approvals):
                    adapter.approve(request_id, False)
            if time.monotonic() > deadline:
                adapter.stop()
                raise TimeoutError('Live Claude turn exceeded limit')
        if adapter.state != 'Connected':
            raise RuntimeError(adapter.last_error or 'Claude inference failed')
        return events[before:]
    try:
        adapter.set_project(str(sandbox))
        session = adapter.create_session()
        adapter.connect()
        report['version'] = adapter.version
        report['session_id'] = session
        report['capabilities'] = adapter.capabilities.to_dict()
        report['tests']['handshake'] = 'PASS'
        report['tests']['model_discovery'] = 'PASS' if adapter.list_models() else 'UNSUPPORTED'
        report['tests']['effort_discovery'] = 'PASS' if adapter.list_efforts() else 'UNSUPPORTED'
        first = turn('This is an isolated acceptance test. Do not use tools. Reply with ACW_CLAUDE_STREAM_OK and one short sentence about blue squares.')
        report['tests']['message'] = 'PASS' if any(e['type']=='message_end' and 'ACW_CLAUDE_STREAM_OK' in e.get('content','') for e in first) else 'FAIL'
        report['tests']['streaming'] = 'PASS' if sum(e['type']=='message_delta' for e in first) > 0 else 'FAIL'
        report['tests']['cwd'] = 'PASS' if Path(adapter.backend_cwd).resolve() == sandbox.resolve() else 'FAIL'
        second = turn('Use the Read tool to read only acw-fixture.txt in the current working directory, then repeat its content. Do not inspect any other files or use other tools.')
        report['tests']['tool_events'] = 'PASS' if any(e['type']=='tool_start' for e in second) and any(e['type']=='tool_result' for e in second) else 'BLOCKED'
        report['tests']['tool_fixture'] = 'PASS' if any(e['type']=='message_end' and 'ACW_READ_FIXTURE_BLUE_42' in e.get('content','') for e in second) else 'BLOCKED'
        adapter.disconnect()
        adapter.resume_session(session)
        resumed = turn('Without tools, name the fixture marker you read earlier in this same conversation.')
        report['tests']['resume'] = 'PASS' if adapter.session_id == session and any(e['type']=='message_end' and 'ACW_READ_FIXTURE_BLUE_42' in e.get('content','') for e in resumed) else 'FAIL'
        # Exercise a real backend-reported model and its own advertised effort.
        models = adapter.list_models()
        chosen = next((m['id'] for m in models if m['id'] == 'default'), models[0]['id'] if models else None)
        efforts = adapter.list_efforts(chosen)
        if chosen and efforts:
            chosen_effort = efforts[0]
            configured = turn('Do not use tools. Reply exactly ACW_MODEL_EFFORT_OK.', model=chosen, effort=chosen_effort)
            report['tests']['model_effort'] = 'PASS' if any(e['type']=='message_end' and 'ACW_MODEL_EFFORT_OK' in e.get('content','') for e in configured) else 'FAIL'
            report['selected_model'] = chosen
            report['selected_effort'] = chosen_effort
        else:
            report['tests']['model_effort'] = 'UNSUPPORTED (not advertised by backend)'
        prompt = 'Do not use tools. Write 1500 numbered lines, each line containing its number and the words blue square, with no introduction.'
        report['prompts'].append(prompt)
        before = len(events)
        adapter.send_message(prompt, model=adapter._model, effort=adapter._effort)
        deadline = time.monotonic()+25
        while time.monotonic() < deadline and adapter.state == 'Busy':
            if any(e['type']=='message_delta' for e in events[before:]):
                break
            time.sleep(.1)
        interrupted = adapter.stop()
        drained = adapter._idle.wait(30)
        report['tests']['stop'] = 'PASS' if interrupted and drained and adapter.state == 'Connected' else 'FAIL'
        report['tests']['session_list'] = 'PASS (Workspace-owned session scope)' if any(s['id']==session for s in adapter.list_sessions()) else 'FAIL'
        report['tests']['history'] = 'PASS (Workspace-owned in-memory history; Core handles persistence)' if adapter.get_history(session) else 'FAIL'
    except Exception as exc:
        report['blocker'] = sanitize(str(exc))
        report['tests']['remaining_live_acceptance'] = 'BLOCKED'
    finally:
        try:
            adapter.disconnect()
        except Exception as exc:
            report['disconnect_error'] = sanitize(str(exc))
        report['tests'].setdefault('cwd', 'PASS' if adapter.backend_cwd and Path(adapter.backend_cwd).resolve()==sandbox.resolve() else 'BLOCKED')
        for test_name in ('message','streaming','tool_events','tool_fixture','resume','model_effort','stop'):
            report['tests'].setdefault(test_name, 'BLOCKED (backend authentication/inference not available)')
        report['tests']['native_external_session_list'] = 'NOT EXERCISED in this run; official SDK helper validation is separate'
        report['tests']['native_external_history'] = 'NOT EXERCISED in this run; official SDK helper validation is separate'
        report['tests']['attachments'] = 'NOT EXERCISED in this run; attachment acceptance is separate'
        report['event_counts'] = {kind: sum(e['type']==kind for e in events) for kind in sorted({e['type'] for e in events})}
        # This sanitized log is exclusively from new isolated acceptance sessions.
        stem='claude-live-run-'+str(time.time_ns())
        report['report_path']=str(evidence/(stem+'.json'))
        report['events_path']=str(evidence/(stem+'-events.jsonl'))
        report['last_stderr']=adapter._last_stderr
        (evidence/(stem+'-events.jsonl')).write_text(''.join(json.dumps(sanitize(e),ensure_ascii=False)+'\n' for e in events), encoding='utf-8')
        (evidence/(stem+'.json')).write_text(json.dumps(sanitize(report),indent=2,ensure_ascii=False), encoding='utf-8')
        print(json.dumps(report, indent=2), flush=True)
    return report


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--live':
        live_probe(sys.argv[2])
    elif len(sys.argv) == 3 and sys.argv[1] == '--message-check':
        result=minimal_message_check(sys.argv[2])
        sys.exit(0 if result['status']=='PASS' else 1)
    elif len(sys.argv) == 3 and sys.argv[1] == '--attachments-check':
        result=attachment_message_check(sys.argv[2])
        sys.exit(0 if result['status']=='PASS' else 1)
    else:
        unittest.main()
