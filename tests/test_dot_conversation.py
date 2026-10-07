"""Root dot chat contract and bounded stress tests: zero real transport/credentials."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json,tempfile,unittest,threading,time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PySide6.QtWidgets import QApplication,QMessageBox
from acw.core import WorkspaceCore
from acw.adapters.dot import DotAdapter
from acw.ui import MainWindow
from scripts.dot_cli_entry import install_room_guard

class RootRunner:
    def __init__(self): self.calls=[];self.room='existing-room';self.fail_read=False;self.items=[]
    def __call__(self,op,**kw):
        self.calls.append((op,kw))
        if op=='list': return [{'id':'selected','display_name':'G8毛','messaging_room_id':self.room}]
        if op=='messages':
            if self.fail_read: raise RuntimeError('fixture read failure')
            return {'dot_id':'selected','messaging_room_id':self.room,'messages':self.items,
                    'lines':['dot: fixture']*len(self.items)}
        return {'id':'sent-user','dot_id':'selected','messaging_room_id':self.room}
    def page(self,start,count=32):
        self.items=[{'id':f'n-{i}','content':{'text':f'fixture {i}'},'created_at':f'2026-10-07T10:{i//60%60:02}:{i%60:02}Z'} for i in range(start,start+count)]

class RootConversationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.runner=RootRunner();self.runner.page(0)
        self.adapter=DotAdapter(lambda *a,**k:None,runner=self.runner)
        self.adapter._require_room_provenance=True
        self.adapter.configure_target('selected','G8毛')
        self.core=WorkspaceCore(Path(self.temp.name)/'data',{'dot':self.adapter});self.addCleanup(self.core.close)
        self.guard=patch('subprocess.Popen',side_effect=AssertionError('Real transport forbidden'));self.guard.start();self.addCleanup(self.guard.stop)
    def connect(self):
        self.adapter.authorize_manual_action('connect');return self.core.connect_dot_conversation()
    def task(self,name):
        p=Path(self.temp.name)/name;p.mkdir();project=self.core.create_project(name,p)
        return self.core.create_task(name,project['id'])
    def test_connect_loads_root_without_project_or_task(self):
        self.assertEqual(self.connect(),32)
        self.assertEqual([x[0] for x in self.runner.calls],['list','messages'])
        self.assertEqual(len(self.core.dot_conversation_messages()),32)
        self.assertTrue(all(x['task_id'] is None for x in self.core.dot_conversation_messages()))
        self.assertEqual(self.core.sessions('dot'),[])
    def test_connect_read_does_not_modify_task_mapping(self):
        task=self.task('alpha');self.connect();after=self.core.get_task(task['id'])
        self.assertEqual(after['dot_session'],task['dot_session'])
        self.assertEqual(self.core.messages(task['id'],'dot'),[])
    def test_connect_without_consent_has_no_transport(self):
        with self.assertRaises(PermissionError):self.core.connect_dot_conversation()
        self.assertEqual(self.runner.calls,[])
    def test_failed_identity_never_reads(self):
        self.adapter.settings['expected_room_id']='wrong-room'
        with self.assertRaises(RuntimeError):self.connect()
        self.assertEqual([x[0] for x in self.runner.calls],['list'])
    def test_missing_existing_room_never_creates(self):
        self.runner.room=''
        with self.assertRaises(RuntimeError):self.connect()
        self.assertEqual([x[0] for x in self.runner.calls],['list'])
    def test_failed_read_retains_cache_and_clears_root_scope(self):
        self.connect();self.runner.fail_read=True;self.adapter.authorize_manual_action('messages')
        with self.assertRaises(RuntimeError):self.core.read_dot_conversation()
        self.assertEqual(len(self.core.dot_conversation_messages()),32)
        self.assertIsNone(getattr(self.core._operation_context,'dot',None))
    def test_send_without_task_updates_exact_root_receipt(self):
        self.connect();self.adapter.authorize_manual_action('send');self.core.send_dot_conversation('hello')
        row=[x for x in self.core.dot_conversation_messages() if x['role']=='user'][0]
        self.assertIsNone(row['task_id']);self.assertEqual(row['metadata']['native_id'],'sent-user')
    def test_root_message_cannot_be_handoff_input(self):
        self.connect()
        with self.assertRaisesRegex(ValueError,'not associated'):
            self.core.prepare_handoff(self.core.dot_conversation_messages()[0]['id'],'codex')
    def test_switch_tasks_preserves_history_and_does_no_transport(self):
        self.connect();a=self.task('a');b=self.task('b');calls=len(self.runner.calls)
        for _ in range(50):
            self.core.select_agent_task('dot',a['id']);self.core.select_agent_task('dot',b['id'])
            self.assertEqual(len(self.core.dot_conversation_messages()),32)
        self.assertEqual(len(self.runner.calls),calls)
        self.assertEqual(self.core.messages(a['id'],'dot'),[]);self.assertEqual(self.core.messages(b['id'],'dot'),[])
    def test_repeated_reads_are_deduplicated_and_older_sorted(self):
        self.runner.page(32);self.connect();self.runner.page(0)
        for _ in range(100):
            self.adapter.authorize_manual_action('messages');self.core.read_dot_conversation(True)
        rows=self.core.dot_conversation_messages();self.assertEqual(len(rows),64)
        self.assertEqual([x['metadata']['native_id'] for x in rows],[f'n-{i}' for i in range(64)])
        self.assertEqual(len(self.core.get_history('dot','selected')),64)
    def test_changed_room_rejects_snapshot_before_import(self):
        self.connect();self.runner.room='another-room';self.runner.page(100)
        self.adapter.authorize_manual_action('messages')
        with self.assertRaisesRegex(RuntimeError,'provenance'):self.core.read_dot_conversation()
        self.assertEqual(len(self.core.dot_conversation_messages()),32)
    def test_root_context_is_thread_local_and_restored(self):
        task=self.task('bound');self.core._contexts['dot']={'task_id':task['id'],'session_id':'selected'}
        seen=[]
        with self.core._dot_root_operation():
            self.assertIsNone(self.core._context('dot')['task_id'])
            t=threading.Thread(target=lambda:seen.append(self.core._context('dot')['task_id']));t.start();t.join()
        self.assertEqual(seen,[task['id']]);self.assertEqual(self.core._context('dot')['task_id'],task['id'])
    def test_second_root_operation_refused(self):
        with self.core._dot_root_operation():
            with self.assertRaisesRegex(RuntimeError,'active'):
                with self.core._dot_root_operation():pass
    def test_reconnect_refuses_changed_verified_room_and_preserves_cache(self):
        self.connect();self.adapter.disconnect();self.runner.room='different-room'
        self.adapter.authorize_manual_action('connect')
        with self.assertRaises(RuntimeError):self.core.connect_dot_conversation()
        self.assertEqual(len(self.core.dot_conversation_messages()),32)
        self.assertEqual(self.runner.calls[-1][0],'list')
    def test_root_snapshot_supersedes_stale_task_copy(self):
        self.connect();task=self.task('legacy')
        self.core.store.insert('messages',dict(id='legacy-message',task_id=task['id'],agent='dot',session_id='selected',role='assistant',content='STALE',timestamp='2026-10-08T00:00:00Z',metadata={'native_id':'n-0','native_room_id':'existing-room'}))
        rows=self.core.dot_conversation_messages();self.assertEqual(len(rows),32)
        row=next(r for r in rows if r['metadata']['native_id']=='n-0')
        self.assertEqual(row['content'],'fixture 0');self.assertIsNone(row['task_id'])
    def test_unproven_legacy_cache_is_not_presented_as_current_room(self):
        self.connect()
        self.core.store.insert('messages',dict(id='unknown-room',task_id=None,agent='dot',session_id='selected',role='assistant',content='Unproven room',timestamp='2026-10-07T11:00:00Z',metadata={}))
        self.assertEqual(len(self.core.dot_conversation_messages()),32)
    def test_missing_send_receipt_never_reports_accepted(self):
        self.connect();original=self.adapter._runner
        self.adapter._runner=lambda op,**kw: {'dot_id':'selected','messaging_room_id':'existing-room'} if op=='send' else original(op,**kw)
        self.adapter.authorize_manual_action('send')
        with self.assertRaisesRegex(RuntimeError,'uncertain'):self.core.send_dot_conversation('uncertain text')
        self.assertFalse(any(e['type']=='send_ack' for e in self.core.events(agent='dot')))

    def test_no_selected_identity_never_shows_other_history(self):
        self.connect();self.adapter.disconnect();self.adapter.target=''
        self.assertEqual(self.core.dot_conversation_messages(),[])

class RoomGuardTests(unittest.TestCase):
    def cli(self,room='room'):
        return SimpleNamespace(resolve_dot=lambda *a,**k:{'id':'dot','messaging_room_id':room},dumps=json.dumps)
    def test_guard_preserves_identity_and_attaches_provenance(self):
        cli=self.cli();install_room_guard(cli,'dot','room');d=cli.resolve_dot(None,None,'dot')
        self.assertEqual(cli.ensure_room(None,None,d),'room')
        result=json.loads(cli.dumps({'messages':[]}));self.assertEqual(result['messaging_room_id'],'room')
    def test_guard_blocks_missing_changed_or_other_identity(self):
        for room in ('','other',None):
            cli=self.cli(room);install_room_guard(cli,'dot','room')
            with self.assertRaises(RuntimeError):cli.resolve_dot(None,None,'dot')
        cli=self.cli();install_room_guard(cli,'another','room')
        with self.assertRaises(RuntimeError):cli.resolve_dot(None,None,'dot')

class RootConversationUITests(RootConversationTests):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def window(self):
        w=MainWindow(self.core);self.addCleanup(w.close);return w
    def test_dot_controls_and_fresh_root_display(self):
        w=self.window();p=w.panels['dot']
        for control in (p.session,p.session_search,p.new_button,p.resume_button,p.rename_button,p.model,p.effort,p.stop_button):
            self.assertTrue(control.isHidden(),control.objectName())
        self.assertIn('尚未載入',p.empty.text());self.connect();w.reload_context()
        self.assertEqual(len(p.cards),32)
        self.assertEqual(p.state.text(),'通道已連接')
    def test_error_notice_survives_control_refresh(self):
        self.connect();w=self.window();p=w.panels['dot'];self.adapter.last_error='fixture error'
        p.set_state('Error');p.update_controls();self.assertEqual(p.notice.text(),'fixture error')
        p.set_monitor(True);self.assertEqual(p.notice.text(),'fixture error')
    def test_selection_change_clears_old_root_cards_and_draft(self):
        self.connect();w=self.window();p=w.panels['dot'];w.reload_context();p.input.setPlainText('private old draft')
        self.adapter.disconnect();p.set_state('Disconnected')
        self.adapter.configure_target('different-dot','G8毛');w.reload_context()
        self.assertEqual(len(p.cards),0);self.assertEqual(p.input.toPlainText(),'')
    def test_root_view_has_no_handoff_buttons(self):
        self.connect();w=self.window();w.reload_context()
        for card in w.panels['dot'].cards.values():self.assertFalse(hasattr(card,'forward_button'))
    def test_ten_thousand_cached_messages_render_bounded_window(self):
        self.connect()
        rows=[]
        for i in range(10000):
            rows.append((f'stress-{i}',None,'dot','selected','assistant','Synthetic stress message '+str(i)+' 測試'*40,'2026-10-07T11:00:00Z','', 'complete',json.dumps({'native_id':f'stress-{i}','native_room_id':'existing-room'})))
        with self.core.store.lock:
            self.core.store.db.executemany('INSERT INTO messages (id,task_id,agent,session_id,role,content,timestamp,raw_ref,status,metadata) VALUES (?,?,?,?,?,?,?,?,?,?)',rows)
            self.core.store.db.commit()
        start=time.perf_counter();w=self.window();w.reload_context();elapsed=time.perf_counter()-start
        self.assertEqual(len(w.panels['dot'].cards),200)
        self.assertEqual(len(self.core.dot_conversation_messages()),10032)
        self.assertLess(elapsed,20,'Bounded root render unexpectedly slow')
        print(f'OFFLINE_STRESS cached=10032 rendered=200 elapsed_seconds={elapsed:.3f}')

    def test_loaded_empty_page_is_not_labelled_unloaded(self):
        self.runner.items=[];self.connect();w=self.window();w.reload_context()
        self.assertIn('這一頁',w.panels['dot'].empty.text())
        self.assertNotIn('尚未載入',w.panels['dot'].empty.text())
    def test_root_draft_survives_task_change(self):
        self.connect();w=self.window();p=w.panels['dot'];p.input.setPlainText('unsent draft')
        self.task('another');w.reload_context();self.assertEqual(p.input.toPlainText(),'unsent draft')
        self.assertEqual(len(p.cards),32)

if __name__=='__main__':unittest.main()
