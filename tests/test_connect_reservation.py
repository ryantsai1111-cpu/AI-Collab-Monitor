"""Offline connection reservation regressions; no process or network transport."""
import tempfile, threading, unittest
from pathlib import Path
from acw.core import WorkspaceCore
from test_core import SyntheticAdapter

class ConnectReservationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.adapter=SyntheticAdapter('codex')
        self.core=WorkspaceCore(Path(self.tmp.name)/'data',{'codex':self.adapter})
        self.addCleanup(self.core.close)
        self.repo=Path(self.tmp.name)/'repo';self.repo.mkdir()
        self.project=self.core.create_project('fixture',self.repo)
    def test_connect_reserves_slow_setup_and_refuses_close_or_selection(self):
        self.core.select_project(self.project['id'])
        entered=threading.Event();release=threading.Event();errors=[]
        original=self.adapter.set_project
        def blocked(*a,**kw):
            entered.set()
            if not release.wait(5): raise AssertionError('barrier timed out')
            return original(*a,**kw)
        self.adapter.set_project=blocked
        def connect():
            try:self.core.connect('codex')
            except Exception as exc:errors.append(exc)
        t=threading.Thread(target=connect);t.start()
        try:
            self.assertTrue(entered.wait(3))
            self.assertIn('codex',self.core._operations)
            with self.assertRaises(RuntimeError):self.core.close()
            with self.assertRaises(RuntimeError):self.core.select_project(self.project['id'])
            self.assertFalse(self.core._closed)
        finally:release.set();t.join(5)
        self.assertFalse(t.is_alive());self.assertEqual(errors,[])
        self.assertEqual(self.adapter.state,'Connected')
    def test_default_project_is_selected_without_self_deadlock(self):
        self.core.set_setting('agent.codex',{'default_project':self.project['id']})
        self.core.connect('codex')
        self.assertEqual(self.core.agent_project('codex')['id'],self.project['id'])
        self.assertEqual(self.adapter.state,'Connected')
        self.assertEqual(self.core._operations,{})
    def test_closed_core_never_starts_handshake(self):
        self.core.close()
        with self.assertRaises(RuntimeError):self.core.connect('codex')
        self.assertNotIn('connect',self.adapter.calls)
    def test_project_switch_drains_callbacks_without_core_lock_or_new_task_leak(self):
        self.core.select_project(self.project['id'])
        old=self.core.create_task('old')
        other=self.repo.parent/'other';other.mkdir()
        project=self.core.create_project('other',other)
        new=self.core.create_task('new',project['id'],select=False)
        original=self.adapter.set_project
        def callback_then_join(*args,**kwargs):
            t=threading.Thread(target=lambda:self.adapter.emit('system',content='shutdown fixture'))
            t.start();t.join(1)
            self.assertFalse(t.is_alive(),'Adapter reader blocked behind Core lock')
            return original(*args,**kwargs)
        self.adapter.set_project=callback_then_join
        self.core.select_agent_task('codex',new['id'])
        rows=self.core.store.query("SELECT task_id FROM messages WHERE content='shutdown fixture'")
        self.assertEqual([row['task_id'] for row in rows],[old['id']])
        self.assertEqual(self.core.agent_task('codex')['id'],new['id'])
    def test_global_project_switch_drains_callbacks_in_old_context(self):
        self.core.select_project(self.project['id'])
        old=self.core.create_task('old')
        other=self.repo.parent/'other';other.mkdir()
        project=self.core.create_project('other',other)
        original=self.adapter.set_project
        def callback_then_join(*args,**kwargs):
            t=threading.Thread(target=lambda:self.adapter.emit('system',content='global shutdown fixture'))
            t.start();t.join(1)
            self.assertFalse(t.is_alive(),'Global sync blocked adapter reader')
            return original(*args,**kwargs)
        self.adapter.set_project=callback_then_join
        self.core.select_project(project['id'])
        rows=self.core.store.query("SELECT task_id FROM messages WHERE content='global shutdown fixture'")
        self.assertEqual([row['task_id'] for row in rows],[old['id']])
        self.assertEqual(self.core.current_project_id,project['id'])
        self.assertIsNone(self.core.current_task_id)
