"""Real Qt + real SQLite/Git integration; backend SyntheticAdapter is explicitly a test double.
No official agent is started by this suite. All files/repos/data are isolated.
"""
import unittest,tempfile,time,json,zipfile,subprocess
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication,QDialog,QMessageBox,QPushButton,QToolButton,QPlainTextEdit,QLineEdit,QTabWidget,QCheckBox,QSpinBox,QComboBox,QDialogButtonBox,QTreeWidget,QSystemTrayIcon,QTreeWidgetItem,QLabel
from PySide6.QtCore import Qt,QTimer,QPoint,QPointF,QMimeData,QUrl
from PySide6.QtGui import QDragEnterEvent,QDropEvent
from PySide6.QtTest import QTest
from acw.core import WorkspaceCore
from acw.ui import MainWindow,MessageCard,EventCard,HandoffDialog
from acw.adapters.dot import DotAdapter
from test_core import SyntheticAdapter
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'evidence/ui-acceptance';OUT.mkdir(exist_ok=True)

class WorkspaceIntegrationUITests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
 def setUp(self):
  self.modal_errors=[];self.modal_timers=[];self.temp=tempfile.TemporaryDirectory(prefix='acw-ui-integration-');self.root=Path(self.temp.name);self.repo=self.root/'repo';self.repo.mkdir();self.second=self.root/'second';self.second.mkdir();self.git=r'C:\Program Files\Git\cmd\git.exe'
  self.gitcmd('init','-b','acceptance-ui');(self.repo/'fixture.txt').write_text('baseline\n',encoding='utf-8');self.gitcmd('add','fixture.txt');self.gitcmd('-c','user.name=ACW Isolated Test','-c','user.email=acw@example.invalid','commit','-m','fixture baseline')
  self.adapters={a:SyntheticAdapter(a) for a in ('claude','codex')};self.adapters['dot']=DotAdapter(lambda *args,**kwargs:None)
  self.core=WorkspaceCore(self.root/'data',self.adapters);self.core.set_setting('legacy.root',str(self.root/'nonexistent-legacy'))
  self.project=self.core.create_project('UI REAL STORE TEST',self.repo);self.core.select_project(self.project['id']);self.task=self.core.create_task('First stored task',branch='acceptance-ui');self.window=MainWindow(self.core);self.window.resize(1400,1000);self.window.show();QTest.qWait(30)
 def gitcmd(self,*args):return subprocess.run([self.git,'-C',str(self.repo),*args],capture_output=True,text=True,encoding='utf-8',check=True)
 def wait(self):
  deadline=time.monotonic()+20
  while self.window.workers and time.monotonic()<deadline:QTest.qWait(20)
  self.assertFalse(self.window.workers);self.window.poll_events();QTest.qWait(20)
  if self.modal_errors:raise self.modal_errors.pop(0)
 def tearDown(self):
  for timer in self.modal_timers:timer.stop()
  self.wait()
  for pane in self.window.panels.values():pane.set_state('Disconnected')
  self.window.close();self.window.deleteLater();QTest.qWait(10)
  if not self.core._closed:self.core.close()
  self.temp.cleanup()
 def snap(self,suffix=''):
  self.app.processEvents();self.window.grab().save(str(OUT/(self._testMethodName+suffix+'.png')))
 def click(self,text,parent=None):
  parent=parent or self.window
  control=next(x for x in parent.findChildren(QPushButton) if x.text().replace('&','').replace('…','...')==text)
  QTest.mouseClick(control,Qt.LeftButton);return control
 def modal(self,action):
  timer=QTimer(self.window);timer.setSingleShot(False);self.modal_timers.append(timer)
  def handle():
   dialog=self.app.activeModalWidget()
   if dialog is None:return
   timer.stop()
   try:action(dialog)
   except Exception as exc:
    self.modal_errors.append(exc)
    dialog.reject()
  timer.timeout.connect(handle);timer.start(40)
 def response(self,agent='claude',text='ORIGINAL_A'):
  if not self.adapters[agent].session_id:self.core.connect(agent);self.core.create_session(agent)
  self.core.ingest_event(agent,'message_start');self.core.ingest_event(agent,'message_delta',content=text);self.core.ingest_event(agent,'message_end');self.window.poll_events();QTest.qWait(20)
  return next(x for x in reversed(self.core.messages(agent=agent)) if x['role']=='assistant')
 def test_ui_project_selection_syncs_real_core_and_discards_only_confirmed_draft(self):
  second=self.core.create_project('SECOND ISOLATED',self.second);self.window.reload_context();panel=self.window.panels['claude'];panel.input.setPlainText('UNSENT_DRAFT')
  self.modal(lambda d:QTest.mouseClick(d.button(QMessageBox.No),Qt.LeftButton));self.window.project_combo.setCurrentIndex(self.window.project_combo.findData(second['id']));self.assertEqual(self.core.current_project_id,self.project['id']);self.assertEqual(panel.input.toPlainText(),'UNSENT_DRAFT')
  self.modal(lambda d:QTest.mouseClick(d.button(QMessageBox.Yes),Qt.LeftButton));self.window.project_combo.setCurrentIndex(self.window.project_combo.findData(second['id']));self.wait();self.assertEqual(self.core.current_project_id,second['id']);self.assertEqual(panel.input.toPlainText(),'');self.assertEqual(self.adapters['claude'].cwd,str(self.second));self.assertEqual(self.adapters['codex'].cwd,str(self.second));self.assertEqual(self.adapters['dot'].cwd,'');self.assertEqual(self.adapters['dot'].metadata['project_name'],second['name'])
 def test_new_task_dialog_stores_real_task_without_transmitting_notes(self):
  def handle(d):
   editor=d.findChild(QLineEdit);editor.setText('Created through actual Qt dialog');d.accept()
  self.modal(handle);self.click('+ Task');self.wait();self.assertEqual(self.core.current_task['title'],'Created through actual Qt dialog');self.assertFalse(any(a.sent for a in self.adapters.values() if hasattr(a,'sent')))
 def test_session_new_rename_select_and_explicit_resume_use_real_mapping(self):
  panel=self.window.panels['codex'];QTest.mouseClick(panel.connect_button,Qt.LeftButton);self.wait();QTest.mouseClick(panel.new_button,Qt.LeftButton);self.wait();sid=self.adapters['codex'].session_id;self.assertEqual(self.core.current_task['codex_session'],sid)
  self.modal(lambda d:(d.findChild(QLineEdit).setText('UI renamed isolated session'),d.accept()));QTest.mouseClick(panel.rename_button,Qt.LeftButton);self.wait();self.assertEqual(self.core.sessions('codex')[0]['title'],'UI renamed isolated session')
  QTest.mouseClick(panel.resume_button,Qt.LeftButton);self.wait();self.assertEqual(self.adapters['codex'].calls[-1],'resume_session');self.assertEqual(self.core.current_task['codex_session'],sid)
 def test_copy_plain_metadata_and_open_raw_are_actual_readonly_widgets(self):
  msg=self.response(text='EXACT ORIGINAL\nUnicode: \u6e2c\u8a66');panel=self.window.panels['claude'];card=panel.cards[msg['id']];card.copy();self.assertEqual(self.app.clipboard().text(),msg['content']);card.copy(True);self.assertIn(msg['id'],self.app.clipboard().text());self.assertTrue(self.app.clipboard().text().endswith(msg['content']))
  def check(d):
   editor=d.findChild(QPlainTextEdit);self.assertTrue(editor.isReadOnly());self.assertIn('EXACT ORIGINAL',editor.toPlainText());d.grab().save(str(OUT/(self._testMethodName+'-raw.png')));self.click('Close',d)
  self.modal(check);self.window.open_raw(msg)
 def test_raw_event_index_renders_sanitized_store_record(self):
  self.core.ingest_event('codex','error',content='ISOLATED actionable error',password='UI_SECRET_CANARY');self.window.poll_events()
  def check(d):
   index=d.findChild(QTreeWidget);self.assertGreater(index.topLevelItemCount(),0);index.setCurrentItem(index.topLevelItem(0));QTest.qWait(10);raw=d.findChild(QPlainTextEdit);self.assertTrue(raw.isReadOnly());self.assertNotIn('UI_SECRET_CANARY',raw.toPlainText());d.grab().save(str(OUT/(self._testMethodName+'-raw-index.png')));self.click('Close',d)
  self.modal(check);self.window.show_agent_events('codex')
 def test_event_rendering_replays_public_claude_tool_and_command_fields(self):
  fixture=ROOT/'evidence/claude-live-run-1791165118613641100-events.jsonl';replayed=[]
  for line in fixture.read_text(encoding='utf-8').splitlines():
   event=json.loads(line)
   if event['type'] in ('tool_start','tool_result','file'):
    kind=event.pop('type');event['evidence_replay']='Recorded official event; no backend running';self.core.ingest_event('claude',kind,**event);replayed.append(event)
  for kind in ['system','error','event','command']:
   self.core.ingest_event('codex',kind,command='fixture command' if kind=='command' else '',cwd=str(self.repo),started=1,completed=2,exit_code=0,status='completed',content='DISPLAY_'+kind)
  self.window.poll_events();QTest.qWait(20);cards=self.window.findChildren(EventCard)
  bodies='\n'.join(c.body.toPlainText() for c in cards);self.assertIn('Read',bodies);self.assertIn('arguments',bodies);self.assertIn('started',bodies);self.assertIn('ended',bodies);self.assertIn('duration',bodies);self.assertIn('ACW_READ_FIXTURE_BLUE_42',bodies);self.assertIn('fixture command',bodies);self.assertIn('exit_code',bodies);self.assertIn('DISPLAY_error',bodies)
  self.assertTrue(all(c.body.isReadOnly() for c in cards));self.assertGreaterEqual(len(cards),8);self.snap('-replay')
 def test_timeline_contains_each_recorded_semantic_event(self):
  kinds=['prompt_sent','message_end','tool_start','tool_result','command','file','handoff','session_changed','project_changed','error','stop']
  for kind in kinds:self.core.ingest_event('codex',kind,content='timeline-'+kind)
  self.window.mode.setCurrentText('Timeline');self.window.refresh_timeline();seen={self.window.timeline.topLevelItem(i).text(2) for i in range(self.window.timeline.topLevelItemCount())};self.assertTrue(set(kinds).issubset(seen));self.snap('-timeline')
 def test_history_filters_search_and_double_click_restore_real_store(self):
  self.response('codex','HISTORY_NEEDLE');first=self.core.current_task;self.core.update_task(first['id'],status='DONE');self.core.ingest_event('codex','error',content='history-error');second=self.core.create_task('Unrelated second task',branch='other');self.window.reload_context();self.window.show_history();self.window.history_status.setCurrentText('DONE');self.window.history_project.setChecked(True);self.window.history_branch.setText('acceptance-ui');self.window.history_date.setText(first['created_at'][:10]);self.window.history_errors.setChecked(True);self.window.refresh_history();self.assertEqual(self.window.history_table.topLevelItemCount(),1);item=self.window.history_table.topLevelItem(0);self.window.history_table.scrollToItem(item);QTest.qWait(30);rect=self.window.history_table.visualItemRect(item);self.assertTrue(self.window.history_table.viewport().rect().intersects(rect));QTest.mouseClick(self.window.history_table.viewport(),Qt.LeftButton,pos=rect.center());QTest.qWait(10);QTest.mouseDClick(self.window.history_table.viewport(),Qt.LeftButton,pos=rect.center());self.wait();self.assertEqual(self.core.current_task_id,first['id']);self.assertEqual(self.core.current_task['codex_session'],first['codex_session'])
  self.window.show_history('codex');self.window.history_errors.setChecked(False);self.window.search.setText('HISTORY_NEEDLE');QTest.keyClick(self.window.search,Qt.Key_Return);self.assertGreater(self.window.history_table.topLevelItemCount(),0);self.snap('-history')
 def test_notes_and_assisted_handoff_keep_source_and_annotation_separate(self):
  message=self.response();self.core.connect('codex');self.core.create_session('codex');self.window.refresh_agent('codex')
  self.modal(lambda d:(d.findChild(QPlainTextEdit).setPlainText('LOCAL_ONLY_NOTE'),QTest.mouseClick(d.findChild(QDialogButtonBox).button(QDialogButtonBox.Save),Qt.LeftButton)));self.click('Task notes');self.assertEqual(self.core.current_task['notes'],'LOCAL_ONLY_NOTE');self.assertEqual(self.adapters['codex'].sent,[])
  dialog=HandoffDialog(self.window,message,'codex');dialog.show();QTest.qWait(20);self.assertEqual(dialog.findChild(QPlainTextEdit,'handoff_source').toPlainText(),message['content']);self.assertTrue(dialog.findChild(QPlainTextEdit,'handoff_source').isReadOnly());dialog.annotation.setPlainText('Separate annotation plus LOCAL_ONLY_NOTE');self.assertEqual(dialog.preview['source_message'],message['content']);self.assertEqual(self.adapters['codex'].sent,[]);self.assertIn('source_session',dialog.outgoing.toPlainText());self.assertIn(self.project['name'],dialog.outgoing.toPlainText());dialog.grab().save(str(OUT/(self._testMethodName+'-preview.png')));QTest.mouseClick(dialog.send_button,Qt.LeftButton);self.assertEqual(dialog.result(),QDialog.Accepted);self.core.send_handoff(dialog.preview);self.assertIn(message['content'],self.adapters['codex'].sent[-1]);self.assertEqual(self.core.handoffs()[0]['annotation'],'Separate annotation plus LOCAL_ONLY_NOTE');dialog.close()
 def test_each_agent_stop_and_global_stop_requires_actual_confirmation(self):
  for agent in ('claude','codex'):
   self.core.connect(agent);self.adapters[agent].state='Busy';self.window.refresh_agent(agent)
   def stop(agent=agent):self.adapters[agent].calls.append('stop');self.adapters[agent].set_state('Connected')
   self.adapters[agent].stop=stop
  self.window.panels['codex'].stop_button.click();self.wait();self.assertIn('stop',self.adapters['codex'].calls);self.assertNotIn('stop',self.adapters['claude'].calls)
  self.modal(lambda d:QTest.mouseClick(d.button(QMessageBox.No),Qt.LeftButton));self.click('Stop current task...');self.assertNotIn('stop',self.adapters['claude'].calls)
  self.modal(lambda d:QTest.mouseClick(d.button(QMessageBox.Yes),Qt.LeftButton));self.click('Stop current task...');self.wait();self.assertIn('stop',self.adapters['claude'].calls)
  for a in ('claude','codex'):self.adapters[a].state='Connected';self.window.refresh_agent(a)
 def test_exports_actual_task_all_four_formats_through_ui_and_redact(self):
  self.response('codex','EXPORT_ORIGINAL');self.core.ingest_event('codex','error',content='Actionable export fixture',password='UI_EXPORT_SECRET_CANARY');self.window.poll_events()
  for suffix in ['md','json','zip','html']:
   target=self.root/('export.'+suffix)
   with patch('acw.ui.QFileDialog.getSaveFileName',return_value=(str(target),'')):self.click('Export')
   self.wait();self.assertTrue(target.exists())
   if suffix=='zip':
    with zipfile.ZipFile(target) as z:payload=b'\n'.join(z.read(name) for name in z.namelist())
   else:payload=target.read_bytes()
   self.assertIn(b'EXPORT_ORIGINAL',payload);self.assertNotIn(b'UI_EXPORT_SECRET_CANARY',payload)
 def test_settings_all_pages_save_only_local_values_and_gate_backend_choices(self):
  self.core.connect('claude');self.window.refresh_agent('claude')
  def handle(d):
   tabs=d.findChild(QTabWidget);names={tabs.tabText(i) for i in range(tabs.count())};self.assertEqual(names,{'Agents','Projects','Paths','Logs','Permissions','Appearance','Retention','Advanced'})
   for i in range(tabs.count()):tabs.setCurrentIndex(i);QTest.qWait(5);d.grab().save(str(OUT/(self._testMethodName+'-'+tabs.tabText(i)+'.png')))
   agents=tabs.widget(next(i for i in range(tabs.count()) if tabs.tabText(i)=='Agents'));fields=agents.findChildren(QComboBox);self.assertTrue(any(x.findData('synthetic-model')>=0 for x in fields));self.assertTrue(any(x.findData('synthetic-effort')>=0 for x in fields));self.assertFalse(d.findChild(QComboBox,'default_model_dot').isEnabled());self.assertFalse(d.findChild(QComboBox,'default_effort_dot').isEnabled())
   retention=tabs.widget(next(i for i in range(tabs.count()) if tabs.tabText(i)=='Retention'));spins=retention.findChildren(QSpinBox);spins[0].setValue(14);spins[1].setValue(2);retention.findChild(QCheckBox).setChecked(False)
   QTest.mouseClick(d.findChild(QDialogButtonBox).button(QDialogButtonBox.Save),Qt.LeftButton)
  self.modal(handle);self.click('Settings');self.assertEqual(self.core.get_setting('retention.days'),14);self.assertEqual(self.core.get_setting('retention.max_mb'),2);self.assertFalse(self.core.get_setting('retention.archive'));self.assertEqual(self.adapters['codex'].calls,[])
 def test_diagnostics_shows_version_session_cwd_error_and_exports_safe_zip(self):
  self.core.connect('claude');self.core.create_session('claude');a=self.adapters['claude'];a.version='PUBLIC_TEST_VERSION';a.last_error='PUBLIC_TEST_ERROR';self.core.ingest_event('claude','error',content='PUBLIC_TEST_ERROR',api_key='UI_DIAGNOSTIC_SECRET');self.window.poll_events()
  def handle(d):
   text=d.findChild(QPlainTextEdit);body=text.toPlainText();self.assertTrue(text.isReadOnly());self.assertIn('PUBLIC_TEST_VERSION',body);self.assertIn('PUBLIC_TEST_ERROR',body);self.assertIn(str(self.repo).replace('\\','\\\\'),body);self.assertNotIn('UI_DIAGNOSTIC_SECRET',body);d.grab().save(str(OUT/(self._testMethodName+'-diagnostics.png')))
   self.click('Close',d)
  self.modal(handle);self.click('Diagnostics');target=self.root/'diagnostics.zip';self.core.export_diagnostics(target)
  with zipfile.ZipFile(target) as z:self.assertNotIn(b'UI_DIAGNOSTIC_SECRET',b'\n'.join(z.read(name) for name in z.namelist()))
 def test_offline_history_and_actionable_backend_error_remain_visible(self):
  message=self.response('codex','OFFLINE_HISTORY_CONTENT');a=self.adapters['codex'];a.last_error='ISOLATED Sandbox setup failed';a.state='Offline';self.window.refresh_agent('codex');self.assertEqual(self.window.panels['codex'].state.text(),'Offline');self.assertIn('Reconnect',self.window.panels['codex'].connect_button.text());self.window.reload_context();self.assertIn(message['id'],self.window.panels['codex'].cards);self.assertIn('OFFLINE_HISTORY_CONTENT',self.window.panels['codex'].cards[message['id']].body.toPlainText());self.window.run(lambda:(_ for _ in ()).throw(RuntimeError('ISOLATED Sandbox setup failed')),agent='codex');self.wait();self.assertIn('ISOLATED Sandbox setup failed',self.window.panels['codex'].notice.text());self.assertEqual(self.window.panels['claude'].state.text(),'Disconnected')
 def test_window_geometry_fullscreen_topmost_minimize_and_no_default_tray(self):
  self.window.resize(1234,876);self.window.move(50,50);QTest.qWait(20);self.window.close();self.assertTrue(self.core.get_setting('ui.geometry'));self.window=MainWindow(self.core);self.window.show();QTest.qWait(30);self.assertEqual(self.window.size().width(),1234);self.assertEqual(self.window.size().height(),876);QTest.keyClick(self.window,Qt.Key_F11);QTest.qWait(30);self.assertTrue(self.window.isFullScreen());QTest.keyClick(self.window,Qt.Key_F11);QTest.qWait(30);self.assertFalse(self.window.isFullScreen());self.window.setWindowFlag(Qt.WindowStaysOnTopHint,True);self.window.show();self.assertTrue(self.window.windowFlags() & Qt.WindowStaysOnTopHint);self.window.showMinimized();QTest.qWait(30);self.assertTrue(self.window.isMinimized());self.window.showNormal();self.assertEqual(self.window.findChildren(QSystemTrayIcon),[]);self.snap('-restored')
 def test_close_reopen_restores_task_project_session_history_without_resend(self):
  message=self.response('codex','RESTART_ORIGINAL');task=self.core.current_task;sent=list(self.adapters['codex'].sent);self.window.close();self.core.close();self.core=WorkspaceCore(self.root/'data',self.adapters);self.window=MainWindow(self.core);self.window.show();QTest.qWait(30);self.assertEqual(self.core.current_task_id,task['id']);self.assertEqual(self.core.current_project_id,self.project['id']);self.assertEqual(self.core.current_task['codex_session'],task['codex_session']);self.assertIn(message['id'],self.window.panels['codex'].cards);self.assertEqual(self.adapters['codex'].sent,sent);self.assertIn(self.project['name'],self.window.project_combo.currentText())
 def test_git_branch_dirty_divergence_and_non_git_display(self):
  (self.repo/'fixture.txt').write_text('changed\n',encoding='utf-8');snapshot=self.core.git_snapshot();self.assertEqual(snapshot['branch'],'acceptance-ui');self.assertTrue(snapshot['dirty']);self.assertIsNone(snapshot['ahead']);self.assertIsNone(snapshot['behind']);text=self.window.branch_text(snapshot);self.assertIn('acceptance-ui',text);self.assertIn('True',text)
  self.core.sync_project();self.window.reload_context();self.assertIn('acceptance-ui',self.window.panels['claude'].branch_label.text());self.assertIn('acceptance-ui',self.window.panels['codex'].branch_label.text());self.assertEqual(self.window.branch_text({'is_git':False}),'Git: not a repository')
 def test_comparison_shows_two_original_responses_without_verdict(self):
  self.response('claude','CLAUDE_ORIGINAL');self.response('codex','CODEX_ORIGINAL')
  def handle(d):
   bodies=[x.toPlainText() for x in d.findChildren(QPlainTextEdit)];self.assertIn('CLAUDE_ORIGINAL',bodies);self.assertIn('CODEX_ORIGINAL',bodies);self.assertIn('no automatic verdict',d.windowTitle());self.assertTrue(all(x.isReadOnly() for x in d.findChildren(QPlainTextEdit)));d.grab().save(str(OUT/(self._testMethodName+'-compare.png')));d.accept()
  self.modal(handle);self.click('Compare')

 def test_agent_settings_actual_controls_store_discovered_defaults_and_fixed_audit_policy(self):
  self.core.connect('claude');self.window.refresh_agent('claude')
  def handle(d):
   d.findChild(QCheckBox,'default_enabled_claude').setChecked(False)
   d.findChild(QLineEdit,'executable_claude').setText('ISOLATED_SYNTHETIC_PATH')
   d.findChild(QSpinBox,'timeout_claude').setValue(35)
   for name,value in [('default_model_claude','synthetic-model'),('default_effort_claude','synthetic-effort'),('default_project_claude',self.project['id'])]:
    control=d.findChild(QComboBox,name);self.assertGreaterEqual(control.findData(value),0);control.setCurrentIndex(control.findData(value))
   text='\n'.join(x.text() for x in d.findChildren(QLabel));self.assertIn('SyntheticAdapter',text);self.assertIn('Enabled when backend supports streaming',text);self.assertIn('Safety-filtered audit always enabled',text)
   QTest.mouseClick(d.findChild(QDialogButtonBox).button(QDialogButtonBox.Save),Qt.LeftButton)
  self.modal(handle);self.click('Settings');setting=self.core.get_setting('agent.claude');self.assertEqual(setting,{'enabled':False,'executable':'ISOLATED_SYNTHETIC_PATH','timeout':35,'default_project':self.project['id'],'default_model':'synthetic-model','default_effort':'synthetic-effort'});self.assertFalse(self.window.panels['claude'].connect_button.isEnabled())
  self.assertNotIn('streaming',setting);self.assertNotIn('raw_log',setting);self.snap('-agent-config')

 def test_actual_local_drop_requires_capability_and_dispatches_attachment_contract(self):
  self.core.connect('codex');self.core.create_session('codex');adapter=self.adapters['codex'];adapter.capabilities.supports_files=True;self.window.refresh_agent('codex');panel=self.window.panels['codex'];path=self.repo/'fixture.txt'
  mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(str(path))]);enter=QDragEnterEvent(QPoint(10,10),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier);QApplication.sendEvent(panel.input.viewport(),enter);self.assertTrue(enter.isAccepted());drop=QDropEvent(QPointF(10,10),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier);QApplication.sendEvent(panel.input.viewport(),drop);self.assertEqual([Path(p) for p in panel.attachments],[path]);self.assertTrue(panel.input.acceptDrops())
  calls=[]
  def send(content,**kwargs):calls.append((content,kwargs));adapter.set_state('Connected')
  adapter.send_message=send;panel.input.setPlainText('Exact attachment prompt');QTest.mouseClick(panel.send_button,Qt.LeftButton);self.wait();self.assertEqual([Path(p) for p in calls[0][1]['attachments']],[path])
  adapter.capabilities.supports_files=False;self.window.refresh_agent('codex');self.assertFalse(panel.input.acceptDrops());self.assertFalse(panel.attach_button.isVisible())
  with patch.object(self.window,'show_error') as error:panel.add_attachments([str(path)]);error.assert_called_once_with('This backend does not support attachments.')
  self.assertEqual(panel.attachments,[])

 def test_actual_utility_buttons_resolve_logs_project_and_scoped_diff_file(self):
  from acw.ui import QDesktopServices
  panel=self.window.panels['codex']
  with patch.object(QDesktopServices,'openUrl',return_value=True) as native:
   self.click('Logs',panel);self.assertEqual(Path(native.call_args[0][0].toLocalFile()),self.core.logs_path('codex'))
   self.click('Files',panel);self.assertEqual(Path(native.call_args[0][0].toLocalFile()),self.repo)
   files=QTreeWidget();item=QTreeWidgetItem(['M','fixture.txt']);item.setData(0,Qt.UserRole,'fixture.txt');files.addTopLevelItem(item);files.setCurrentItem(item);self.window.open_changed_file(files);self.assertEqual(Path(native.call_args[0][0].toLocalFile()),self.repo/'fixture.txt')
   outside=QTreeWidgetItem(['M','../outside.txt']);outside.setData(0,Qt.UserRole,'../outside.txt');files.addTopLevelItem(outside);files.setCurrentItem(outside);count=native.call_count
   with patch.object(self.window,'show_error') as error:self.window.open_changed_file(files);self.assertTrue(error.called)
   self.assertEqual(native.call_count,count)
  # OS handler is intentionally mocked: this proves UI/Core scoped dispatch, not Explorer launch.

 def test_diff_copy_and_save_write_real_safe_patch_and_original_repo_unchanged(self):
  before=(self.repo/'fixture.txt').read_bytes();diff='--- a/fixture.txt\n+++ b/fixture.txt\n@@ -1 +1 @@\n-baseline\n+proposed\n';target=self.root/'reviewed.patch'
  with patch('acw.ui.QFileDialog.getSaveFileName',return_value=(str(target),'Patch (*.patch)')):self.window.save_patch(diff)
  self.wait();self.assertEqual(target.read_text(encoding='utf-8'),diff);self.assertEqual((self.repo/'fixture.txt').read_bytes(),before)
  # The actual Diff dialog copy control is inspected via its real dialog below.
  (self.repo/'fixture.txt').write_text('proposed\n',encoding='utf-8')
  def handle(d):
   self.wait();self.click('Copy diff',d);self.assertIn('+proposed',self.app.clipboard().text());self.assertTrue(all(x.isReadOnly() for x in d.findChildren(QPlainTextEdit)));d.grab().save(str(OUT/(self._testMethodName+'-diff-copy.png')));self.click('Close',d)
  self.modal(handle);self.click('Diff / Tests')

 def test_forward_menu_lists_other_agents_and_blocked_dot_preview_is_disabled(self):
  self.response('claude','FORWARD_EXACT');self.response('codex','RETURN_EXACT')
  for source,targets in [('claude',{'Dot','Codex'}),('codex',{'Claude','Dot'})]:
   card=next(x for x in self.window.panels[source].cards.values() if x.message.get('role')=='assistant');self.assertEqual({a.text() for a in card.forward_button.menu().actions()},targets);self.assertTrue(card.forward_button.isVisible())
  msg=next(m for m in self.core.messages(agent='claude') if m['role']=='assistant');dialog=HandoffDialog(self.window,msg,'dot');self.assertFalse(dialog.send_button.isEnabled());self.assertEqual(dialog.findChild(QPlainTextEdit,'handoff_source').toPlainText(),msg['content']);dialog.close()

 def test_legacy_monitor_actual_incremental_logs_and_timeline_are_readonly(self):
  import hashlib
  legacy=self.root/'legacy';logs=legacy/'logs';logs.mkdir(parents=True)
  for agent in ('claude','dot','codex','timeline'):(logs/(agent+'.log')).write_text('LEGACY_'+agent+'\n',encoding='utf-8')
  before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in logs.iterdir()};self.core.set_setting('legacy.root',str(legacy));self.window.mode.setCurrentText('Monitor');self.window.poll_events();self.wait()
  for agent in ('claude','dot','codex'):self.assertIn('LEGACY_'+agent,self.window.panels[agent].cards['legacy-'+agent].body.toPlainText());self.assertTrue(self.window.panels[agent].input.isReadOnly())
  self.assertTrue(any(e['type']=='legacy' and 'LEGACY_timeline' in e['payload'].get('content','') for e in self.core.store.query('SELECT * FROM events')));self.assertEqual(before,{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in logs.iterdir()});self.assertEqual(self.core.poll_legacy(legacy),[]);self.snap('-legacy')

 def test_state_capability_no_fake_web_terminal_voice_and_known_branch_counts(self):
  panel=self.window.panels['codex'];self.core.connect('codex');self.window.refresh_agent('codex');panel.set_state('Connecting');self.assertEqual(panel.state.text(),'Connecting');self.assertFalse(panel.send_button.isEnabled());panel.set_state('Connected');self.assertTrue(panel.send_button.isEnabled());panel.set_state('Busy');self.assertTrue(panel.stop_button.isEnabled());panel.set_state('Error');self.assertEqual(panel.connect_button.text(),'Reconnect');self.assertEqual(self.window.panels['claude'].state.text(),'Disconnected')
  controls={x.text() for x in panel.findChildren(QPushButton)};self.assertFalse({'Web','Voice','Terminal','MCP'} & controls)
  snapshot={'is_git':True,'branch':'acceptance-ui','dirty':True,'ahead':2,'behind':3}
  for agent in ('claude','codex'):
   self.window.panels[agent].branch_label.setText(self.window.branch_text(snapshot));text=self.window.panels[agent].branch_label.text();self.assertIn('acceptance-ui',text);self.assertIn('True',text);self.assertIn('2',text);self.assertIn('3',text)
  for agent in ('claude','codex'):self.window.panels[agent].set_state('Disconnected')
