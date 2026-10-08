"""OFFLINE FIXTURES ONLY. No real Dot CLI, credential reads or network calls."""
import json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from acw.adapters.dot import DotAdapter
from acw.core import WorkspaceCore

class FixtureRunner:
    def __init__(self): self.calls=[];self.sent='';self.missing=False;self.fail=False
    def __call__(self,op,**kw):
        self.calls.append((op,kw))
        if self.fail: raise RuntimeError('Synthetic failure; token=FAKE_CANARY')
        if op=='list': return [] if self.missing else [{'id':'selected','display_name':'G8毛','preview':'PRIVATE_OTHER_NOT_PERSISTED'},{'id':'other','display_name':'Other','preview':'PRIVATE_OTHER_NOT_PERSISTED'}]
        if op=='send': self.sent=kw['text'];return {'id':'m-user'}
        return {'messages':[{'id':'m-user','content':{'text':self.sent or 'A'},'created_at':'2026-10-05T00:00:00Z'},{'id':'m-dot','content':{'text':'OFFLINE TEST RESPONSE\npassword=FAKE_CANARY'},'created_at':'2026-10-05T00:00:01Z'}], 'lines':['dot: OFFLINE TEST RESPONSE','you: A']}

class DotOfflineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='acw-dot-offline-');self.root=Path(self.temp.name)
        self.runner=FixtureRunner();self.adapter=DotAdapter(lambda *a,**k:None,runner=self.runner)
        self.core=WorkspaceCore(self.root/'data',{'dot':self.adapter})
        repo=self.root/'repo';repo.mkdir();project=self.core.create_project('OFFLINE DOT FIXTURE',repo)
        self.core.select_project(project['id']);self.core.create_task('OFFLINE ONLY')
    def tearDown(self): self.core.close();self.temp.cleanup()
    def configured(self): self.adapter.configure_target('selected','G8毛')
    def connected(self):
        self.configured();self.adapter.authorize_manual_action('connect');self.assertTrue(self.core.connect('dot'))
    def test_startup_diagnostics_history_project_do_not_call_transport(self):
        self.adapter.diagnostics();self.core.get_history('dot');self.adapter.set_project('ignored',{'project_name':'test'})
        self.assertEqual(self.runner.calls,[])
    def test_default_real_transport_never_called_without_ticket(self):
        with patch('acw.adapters.dot.subprocess.Popen',side_effect=AssertionError('LIVE FORBIDDEN')):
            a=DotAdapter(lambda *a,**k:None);self.assertFalse(a.connect());a.configure_target('selected','G8毛')
            with self.assertRaises(PermissionError):a.connect()
    def test_one_use_and_action_specific_consent(self):
        self.configured();self.adapter.authorize_manual_action('messages')
        with self.assertRaises(PermissionError):self.adapter.connect()
        self.assertEqual(self.runner.calls,[])
        self.adapter.authorize_manual_action('connect');self.adapter.connect()
        with self.assertRaises(PermissionError):self.adapter.connect()
    def test_wrong_target_and_renaming_cannot_redirect(self):
        with self.assertRaises(ValueError):self.adapter.configure_target('other','Other')
        with self.assertRaises(ValueError):self.adapter.configure_target('bad\x00id','G8毛')
        self.configured();self.runner.missing=True;self.adapter.authorize_manual_action('connect')
        with self.assertRaises(RuntimeError):self.adapter.connect()
        self.assertNotEqual(self.adapter.state,'Connected')
    def test_opaque_native_id_and_normalized_name_survive_restart_without_auth(self):
        self.adapter.configure_target('native.dot~1',' \uff27\uff18毛 ')
        a=DotAdapter(lambda *a,**k:None,runner=self.runner,dot_id=self.adapter.target,dot_name=self.adapter.target_name)
        self.assertEqual(a.target,'native.dot~1');self.assertEqual(a.target_name,'G8毛')
        self.assertTrue(a.capabilities.supports_sessions);self.assertEqual(a.state,'Disconnected');self.assertEqual(self.runner.calls,[])
        for bad in ('','bad\nline','bad\x00line',123,{'id':'selected'},'a'*16385):
            with self.assertRaises(ValueError):a.configure_target(bad,'G8毛')
    def test_identifier_contract_matches_pinned_source_not_uuid_guess(self):
        import ast
        from acw.adapters.dot import DOT_ID_PATTERN,valid_dot_id
        tree=ast.parse((Path(__file__).resolve().parents[1]/'tools/chatgpt-dot-cli-pinned/chatgpt_dot/api.py').read_text(encoding='utf-8'))
        assignment=next(x for x in tree.body if isinstance(x,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='_ID' for t in x.targets))
        self.assertEqual(DOT_ID_PATTERN,ast.literal_eval(assignment.value))
        for value in ('tbo~prefix-opaque_1.v2','opaque:YWJj+/==','-option','http://example','x/y','x?y','x#y','x%2fy','x=y','x+y','a'*201):self.assertTrue(valid_dot_id(value))
        request=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='request_json')
        self.assertEqual(request.body[0].value.func.id,'assert_allowed')
        for value in ('opaque:YWJj+/==','http://example','../target'):
            self.assertIsNone(__import__('re').fullmatch(DOT_ID_PATTERN,value))
    def test_metadata_discovery_strips_all_previews(self):
        self.adapter.authorize_manual_action('list');items=self.adapter.discover_targets()
        self.assertEqual(set(items[0]),{'id','name'})
        self.assertNotIn('PRIVATE_OTHER',json.dumps(self.core.events()))
    def test_handshake_maps_native_dot_identity_and_capabilities(self):
        self.connected();self.assertEqual(self.core.current_task['dot_session'],'selected')
        caps=self.core.capabilities('dot')
        for key in ('supports_streaming','supports_cancel','supports_files','supports_effort','supports_model_selection'):self.assertFalse(caps[key])
        with self.assertRaises(NotImplementedError):self.adapter.create_session()
        with self.assertRaises(NotImplementedError):self.adapter.stop()
    def test_exact_send_ack_not_fake_assistant_or_auto_read(self):
        self.connected();self.adapter.authorize_manual_action('send');text='A\n保留原文 -- $()'
        self.core.send_message('dot',text);self.assertEqual(self.runner.sent,text)
        self.assertEqual([c[0] for c in self.runner.calls],['list','send'])
        self.assertFalse(any(x['role']=='assistant' for x in self.core.messages(agent='dot')))
    def test_manual_snapshot_deduplicates_send_and_repeat_read(self):
        self.connected();self.adapter.authorize_manual_action('send');self.core.send_message('dot','A')
        for _ in range(2):self.adapter.authorize_manual_action('messages');self.adapter.refresh_messages()
        # Native snapshots belong to the root chat, never implicitly to this task.
        task_messages=self.core.messages(agent='dot')
        self.assertEqual([x['role'] for x in task_messages],['user'])
        messages=self.core.store.query("SELECT * FROM messages WHERE agent='dot' AND task_id IS NULL ORDER BY rowid")
        self.assertEqual(len(messages),2)
        self.assertEqual([x['role'] for x in messages],['user','assistant'])
        self.assertNotIn('FAKE_CANARY',json.dumps(messages));self.assertNotIn('message_delta',[x['type'] for x in self.core.events()])
    def test_manual_older_page_and_read_never_poll(self):
        self.connected();self.adapter.authorize_manual_action('messages');self.adapter.refresh_messages()
        self.adapter.authorize_manual_action('messages');self.adapter.refresh_messages(True)
        self.assertEqual(self.runner.calls[-1][1],{'dot_id':'selected','before':'m-user'})
        count=len(self.runner.calls);self.core.get_history('dot');self.assertEqual(len(self.runner.calls),count)
    def test_failed_send_redacts_error_and_does_not_retry(self):
        self.connected();self.runner.fail=True;self.adapter.authorize_manual_action('send')
        with self.assertRaises(RuntimeError):self.core.send_message('dot','A')
        self.assertEqual(len(self.runner.calls),2);self.assertNotIn('FAKE_CANARY',json.dumps(self.core.events()))
    def test_handoff_preserves_source_and_requires_separate_consent(self):
        self.connected();self.core.store.insert('messages',{'id':'source','task_id':self.core.current_task_id,'agent':'claude','session_id':'s','role':'assistant','content':'A','timestamp':'2026-10-05T00:00:00Z'})
        preview=self.core.prepare_handoff('source','dot')
        self.adapter.authorize_manual_action('send');self.core.send_handoff(preview)
        self.assertIn('A',self.runner.sent);self.assertEqual(self.core.store.get('messages',{'id':'source'})['content'],'A')
    def test_bounded_launcher_exact_text_pin_validation_no_cli_execution(self):
        import sys
        from scripts import dot_cli_entry
        original=list(sys.argv);original_path=list(sys.path);calls=[]
        try:
            with patch.object(sys,'argv',['entry','send','--dot-id','selected','--expected-room','fixture-room','--','A\n--auth SECRET_IS_NOT_CONFIG']),patch.object(dot_cli_entry.runpy,'run_module',side_effect=lambda *a,**kw:calls.append(list(sys.argv))),patch.object(dot_cli_entry,'install_room_guard') as guard:
                dot_cli_entry.main()
                self.assertEqual(guard.call_args.args[1:],('selected','fixture-room'))
            self.assertEqual(calls,[['chatgpt-dot-cli','--json','send','--dot-id=selected','--','A\n--auth SECRET_IS_NOT_CONFIG']])
            with patch.object(sys,'argv',['entry','list','--auth','forbidden']),patch.object(dot_cli_entry.runpy,'run_module',side_effect=AssertionError('CLI FORBIDDEN')):
                with self.assertRaises(ValueError):dot_cli_entry.main()
        finally:sys.argv=original;sys.path[:]=original_path

if __name__=='__main__':unittest.main()
