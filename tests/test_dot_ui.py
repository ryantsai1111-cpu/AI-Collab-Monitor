"""Visible offline Qt interaction. Injected fixture runner; NEVER real CLI."""
import tempfile,time,unittest,json
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication,QMessageBox,QInputDialog
from PySide6.QtCore import Qt,QThread,QTimer
from PySide6.QtTest import QTest
from acw.core import WorkspaceCore
from acw.ui import MainWindow
from acw.adapters.dot import DotAdapter
from test_dot import FixtureRunner

OUT=Path(__file__).resolve().parents[1]/'evidence/dot-offline-ui'
class DotOfflineUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([]);OUT.mkdir(parents=True,exist_ok=True)
    def setUp(self):
        self.live_guard=patch('acw.adapters.dot.subprocess.Popen',side_effect=AssertionError('REAL DOT CLI FORBIDDEN'));self.live_guard.start()
        self.temp=tempfile.TemporaryDirectory(prefix='acw-dot-ui-offline-');self.root=Path(self.temp.name)
        self.runner=FixtureRunner();self.adapter=DotAdapter(lambda *a,**k:None,runner=self.runner)
        self.core=WorkspaceCore(self.root/'data',{'dot':self.adapter});self.core.set_setting('legacy.root',str(self.root/'absent'))
        repo=self.root/'repo';repo.mkdir();project=self.core.create_project('OFFLINE DOT UI — FIXTURE ONLY',repo)
        self.core.select_project(project['id']);self.core.create_task('OFFLINE TEST — NO LIVE BACKEND')
        self.core.desktop_sessions=lambda agent: []
        self.core.git_snapshot=lambda *args, **kwargs: dict(branch='', dirty=False, ahead=0, behind=0, status='', diff='', log='', is_git=False, error='')
        self.window=MainWindow(self.core);self.window.navigator.set_sessions('claude', []);self.window.resize(1500,1000);self.window.show();self.panel=self.window.panels['dot'];QTest.qWait(40)
    def wait(self):
        until=time.monotonic()+10
        while self.window.workers and time.monotonic()<until:
            QTest.qWait(20)
            # Explicitly release the GIL so Python-backed Qt workers can progress.
            time.sleep(.001)
        self.assertFalse(self.window.workers);self.window.poll_events();QTest.qWait(20)
        # Polling can enqueue a periodic read; drain it before closing the fixture.
        while self.window.workers and time.monotonic()<until:
            QTest.qWait(20)
            time.sleep(.001)
        self.assertFalse(self.window.workers)
    def tearDown(self):
        self.window.timer.stop();self.window.sync_timer.stop()
        self.wait();self.window.grab().save(str(OUT/(self._testMethodName+'.png')))
        self.panel.set_state('Disconnected');self.window.close();self.window.deleteLater();QTest.qWait(20)
        if not self.core._closed:self.core.close()
        self.temp.cleanup();self.live_guard.stop()
    def connect_fixture(self):
        self.adapter.configure_target('selected','G8毛');self.window.refresh_agent('dot')
        with patch.object(QMessageBox,'exec',return_value=QMessageBox.Yes):QTest.mouseClick(self.panel.connect_button,Qt.LeftButton)
        self.wait();self.assertEqual(self.adapter.state,'Connected')
    def test_startup_no_transport_and_truthful_controls(self):
        self.assertEqual(self.runner.calls,[]);self.assertTrue(self.panel.dot_select.isEnabled())
        self.assertFalse(self.panel.model.isEnabled());self.assertFalse(self.panel.effort.isEnabled())
        self.assertFalse(self.panel.dot_refresh.isEnabled());self.assertIn('非官方',self.panel.notice.text())
    def test_cancel_connect_never_calls_transport(self):
        self.adapter.configure_target('selected','G8毛');self.window.refresh_agent('dot')
        with patch.object(QMessageBox,'exec',return_value=QMessageBox.No):QTest.mouseClick(self.panel.connect_button,Qt.LeftButton)
        self.wait();self.assertEqual(self.runner.calls,[])
    def test_select_names_only_then_explicit_connect(self):
        with patch.object(QMessageBox,'exec',return_value=QMessageBox.Yes),patch.object(self.panel,'choose_dot',return_value={'id':'selected','name':'G8毛'}):
            QTest.mouseClick(self.panel.dot_select,Qt.LeftButton);self.wait()
        self.assertEqual(self.adapter.target,'selected');self.assertEqual(self.adapter.state,'Disconnected')
        self.assertEqual(len(self.runner.calls),1);self.assertTrue(self.panel.connect_button.isEnabled())
        self.assertFalse(self.panel.new_button.isEnabled())
    def test_selection_result_callback_runs_on_gui_thread(self):
        observed=[]
        def picker(*args,**kwargs):
            observed.append(QThread.currentThread()==self.app.thread())
            return {'id':'selected','name':'G8毛'}
        with patch.object(QMessageBox,'exec',return_value=QMessageBox.Yes),patch.object(self.panel,'choose_dot',side_effect=picker):
            QTest.mouseClick(self.panel.dot_select,Qt.LeftButton);self.wait()
        self.assertEqual(observed,[True],'Selection dialogs and widget updates must execute on the GUI thread')
        self.assertTrue(self.panel.connect_button.isEnabled())
    def test_real_selection_dialog_commit_saves_and_enables_connect(self):
        errors=[];timer=QTimer(self.window)
        def commit():
            dialog=self.app.activeModalWidget()
            if dialog is None or dialog.objectName()!='dot_selection_dialog':return
            timer.stop()
            try:
                from PySide6.QtWidgets import QPushButton
                control=dialog.findChild(QPushButton,'commit_dot_selection')
                self.assertTrue(control.isEnabled());QTest.mouseClick(control,Qt.LeftButton)
            except Exception as exc:errors.append(exc);dialog.reject()
        timer.timeout.connect(commit);timer.start(30)
        try:
            with patch.object(QMessageBox,'exec',return_value=QMessageBox.Yes):QTest.mouseClick(self.panel.dot_select,Qt.LeftButton);self.wait()
        finally:timer.stop()
        self.assertEqual(errors,[]);self.assertEqual(self.core.get_setting('agent.dot')['dot_id'],'selected')
        self.assertTrue(self.panel.connect_button.isEnabled());self.assertEqual(len(self.runner.calls),1)
        self.assertEqual(self.adapter.state,'Disconnected');self.assertEqual(self.adapter.session_id,'')
    def test_cancel_real_selection_keeps_disconnected_and_does_not_connect(self):
        timer=QTimer(self.window)
        def cancel():
            dialog=self.app.activeModalWidget()
            if dialog is not None and dialog.objectName()=='dot_selection_dialog':timer.stop();dialog.reject()
        timer.timeout.connect(cancel);timer.start(30)
        try:
            with patch.object(QMessageBox,'exec',return_value=QMessageBox.Yes):QTest.mouseClick(self.panel.dot_select,Qt.LeftButton);self.wait()
        finally:timer.stop()
        self.assertFalse(self.panel.connect_button.isEnabled());self.assertEqual(self.adapter.target,'');self.assertEqual(len(self.runner.calls),1)
    def test_selection_callback_error_visible_without_auth_or_silent_disable(self):
        with patch.object(QMessageBox,'exec',return_value=QMessageBox.Yes),patch.object(self.panel,'choose_dot',return_value={'id':'bad\x00id','name':'G8毛'}):
            QTest.mouseClick(self.panel.dot_select,Qt.LeftButton);self.wait()
        self.assertIn('Unsupported Dot identifier',self.window.footer.text())
        self.assertIn('selection was not saved',self.panel.notice.text());self.assertEqual(len(self.runner.calls),1)
    def identifier_chain(self, fixture_path):
        fixture=json.loads(fixture_path.read_text(encoding='utf-8'))
        native_id=fixture['cli_list'][0]['id'];calls=[]
        def offline_cli(operation,**kwargs):
            self.assertEqual(operation,'list','This chain must never Connect/read/send')
            calls.append((operation,kwargs));return json.loads(json.dumps(fixture['cli_list']))
        self.adapter._runner=offline_cli
        timer=QTimer(self.window);errors=[]
        def confirm():
            dialog=self.app.activeModalWidget()
            if dialog is None or dialog.objectName()!='dot_selection_dialog':return
            timer.stop()
            try:
                from PySide6.QtWidgets import QPushButton
                QTest.mouseClick(dialog.findChild(QPushButton,'commit_dot_selection'),Qt.LeftButton)
            except Exception as exc:errors.append(exc);dialog.reject()
        timer.timeout.connect(confirm);timer.start(30)
        try:
            with patch.object(QMessageBox,'exec',return_value=QMessageBox.Yes):QTest.mouseClick(self.panel.dot_select,Qt.LeftButton);self.wait()
        finally:timer.stop()
        self.assertEqual(errors,[]);saved=self.core.get_setting('agent.dot')
        self.assertEqual(saved['dot_id'],native_id);self.assertTrue(self.panel.connect_button.isEnabled())
        metadata=next(x for x in self.core.events(agent='dot') if x['type']=='dot_target_metadata')['payload']
        self.assertEqual(metadata['dot_id'],native_id);self.assertEqual(metadata['dot_id_type'],'str')
        self.assertNotEqual(native_id,fixture['cli_list'][0].get('messaging_room_id'))
        self.window.timer.stop();self.window.sync_timer.stop();self.wait()
        self.window.close();self.window.deleteLater();QTest.qWait(30)
        if not self.core._closed:self.core.close()
        self.adapter=DotAdapter(lambda *a,**k:None,runner=offline_cli,**saved)
        self.core=WorkspaceCore(self.root/'data',{'dot':self.adapter});self.core.desktop_sessions=lambda agent: []
        self.window=MainWindow(self.core)
        self.window.navigator.set_sessions('claude', []);self.window.resize(1500,1000);self.window.show();self.panel=self.window.panels['dot'];QTest.qWait(30)
        self.assertEqual(self.adapter.target,native_id);self.assertTrue(self.panel.connect_button.isEnabled())
        self.assertEqual(self.adapter.state,'Disconnected');self.assertEqual(self.adapter.session_id,'')
        self.assertFalse(self.core.current_task.get('dot_session'));self.assertEqual(len(calls),1)
    def test_source_opaque_contract_parse_selection_save_reload_connect_enabled(self):
        self.identifier_chain(Path(__file__).parent/'fixtures/g8-dot-contract-sample.json')
    @unittest.skipUnless((Path(__file__).parent/'fixtures/g8-dot-observed.json').exists(),'BLOCKED: actual non-secret G8 Dot identifier was not retained by old build; awaiting user value')
    def test_actual_observed_g8_parse_selection_save_reload_connect_enabled(self):
        fixture_path=Path(__file__).parent/'fixtures/g8-dot-observed.json'
        self.assertTrue(json.loads(fixture_path.read_text(encoding='utf-8'))['is_actual_user_identifier'])
        self.identifier_chain(fixture_path)
    def test_connected_ui_manual_snapshot_send_and_no_poll(self):
        self.connect_fixture();self.assertFalse(self.panel.new_button.isEnabled());self.assertFalse(self.panel.stop_button.isEnabled())
        self.assertFalse(self.panel.attach_button.isVisible());self.assertTrue(self.panel.dot_refresh.isEnabled())
        self.panel.input.setPlainText('A\nOFFLINE ORIGINAL')
        with patch.object(QMessageBox,'exec',return_value=QMessageBox.Yes):QTest.mouseClick(self.panel.send_button,Qt.LeftButton)
        self.wait();self.assertEqual(self.runner.sent,'A\nOFFLINE ORIGINAL');self.assertEqual(len(self.runner.calls),3)
        with patch.object(QMessageBox,'exec',return_value=QMessageBox.Yes):QTest.mouseClick(self.panel.dot_refresh,Qt.LeftButton)
        self.wait();self.assertEqual(len(self.core.dot_conversation_messages()),2)
        self.assertTrue(any(card.message.get('role')=='assistant' for card in self.panel.cards.values()))
        QTest.qWait(300);self.window.poll_events();self.assertEqual(len(self.runner.calls),4)
    def test_cancel_send_preserves_draft_and_does_not_send(self):
        self.connect_fixture();self.panel.input.setPlainText('UNSENT A')
        with patch.object(QMessageBox,'exec',return_value=QMessageBox.No):QTest.mouseClick(self.panel.send_button,Qt.LeftButton)
        self.wait();self.assertEqual(self.panel.input.toPlainText(),'UNSENT A');self.assertEqual(len(self.runner.calls),2)
    def test_monitor_mode_prohibits_select_read_send(self):
        self.connect_fixture();self.panel.set_monitor(True)
        for control in (self.panel.dot_select,self.panel.dot_refresh,self.panel.dot_older,self.panel.send_button):self.assertFalse(control.isEnabled())
        self.assertTrue(self.panel.input.isReadOnly());self.assertEqual(len(self.runner.calls),2)

if __name__=='__main__':unittest.main()
