"""Visible, isolated metadata UI tests. No backend, private history or network."""
import json, tempfile, time, unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication, QPushButton
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from acw.core import WorkspaceCore
from acw.presentation import session_display, project_label, timestamp
from acw.ui import MainWindow, NativeSessionDialog, SessionHistoryDialog, SessionDetailsDialog, HandoffDialog
from test_core import SyntheticAdapter

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'evidence/session-labels-ui'

class HumanSessionLabels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([]); OUT.mkdir(parents=True, exist_ok=True)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='acw-readable-sessions-')
        self.root = Path(self.temp.name)
        self.adapters = {a: SyntheticAdapter(a) for a in ('claude','dot','codex','local')}
        self.core = WorkspaceCore(self.root/'data', self.adapters)
        self.core.set_setting('legacy.root', str(self.root/'no-legacy'))
        self.projects=[]
        for parent in ('台灣訂單','海外訂單'):
            repo=self.root/parent/'order-system'; repo.mkdir(parents=True)
            self.projects.append(self.core.create_project('訂單管理', repo))
        self.core.select_project(self.projects[0]['id'])
        self.task=self.core.create_task('修復查詢與訂單流程（隔離測試）')
        self.saved=[]
        for agent in self.adapters:
            for i, project in enumerate(self.projects):
                sid=f'opaque-{agent}-{i}'
                row=dict(id=sid,agent=agent,title=sid,task_id=self.task['id'],project_id=project['id'],
                         cwd=project['repo_path'],created_at='2026-01-01T00:00:00Z',
                         updated_at=f'2026-10-0{i+1}T12:00:00Z',metadata={})
                self.core.store.insert('sessions', row); self.saved.append(row)
                self.core.store.insert('messages',dict(id=f'm-{agent}-{i}',task_id=self.task['id'],agent=agent,
                    session_id=sid,role='user',content='檢查訂單搜尋，不修改程式',timestamp='2026-10-01T00:00:00Z'))
        self.window=MainWindow(self.core);self.window.resize(1750,1100);self.window.show();QTest.qWait(40)

    def wait(self):
        until=time.monotonic()+5
        while self.window.workers and time.monotonic()<until:
            QTest.qWait(20)
            # Explicitly release the GIL so Python-backed Qt workers can progress.
            time.sleep(.001)
        self.assertFalse(self.window.workers);self.window.poll_events();QTest.qWait(20)

    def tearDown(self):
        self.wait(); self.window.grab().save(str(OUT/(self._testMethodName+'.png')))
        self.window.close();self.window.deleteLater();QTest.qWait(20)
        if not self.core._closed:self.core.close()
        self.temp.cleanup()

    def test_three_panels_readable_preview_duplicate_project_paths_and_time(self):
        for agent,panel in self.window.panels.items():
            texts=[panel.session.itemText(i) for i in range(1,panel.session.count())]
            self.assertTrue(all('訂單管理' in t and '檢查訂單搜尋' in t and agent.title() in t for t in texts))
            self.assertTrue(any('台灣訂單' in t for t in texts))
            if agent != 'dot':
                self.assertFalse(any('海外訂單' in t for t in texts), 'The Agent picker is scoped to its own Project')
            all_labels = [session_display(row, agent, self.projects, preview='檢查訂單搜尋')['label'] for row in self.saved if row['agent'] == agent]
            self.assertTrue(any('台灣訂單' in t for t in all_labels))
            self.assertTrue(any('海外訂單' in t for t in all_labels))
            self.assertTrue(all('opaque-' not in t for t in texts))
            self.assertEqual(panel.session.itemData(1),f'opaque-{agent}-' + ('1' if agent == 'dot' else '0'))
            self.assertTrue(all('2026-10-' in t for t in texts))
            panel.session.setCurrentIndex(panel.session.findData(f'opaque-{agent}-0'))
            self.assertIn('檢查訂單搜尋',panel.session.currentText())
        self.assertTrue(all(a.calls==[] for a in self.adapters.values()))

    def test_unknown_project_title_and_cwd_never_fabricates_name_or_id(self):
        display=session_display({'id':'secret-looking-opaque-id'},'dot')
        self.assertIn('未知專案',display['label']);self.assertIn('未命名對話',display['label'])
        self.assertIn('工作目錄未知',display['label']);self.assertNotIn('secret-looking',display['label'])
        native=session_display({'id':'id','cwd':r'C:\other\repo'},'codex')
        self.assertIn('repo',native['label']);self.assertIn(r'C:\other\repo',native['label'])

    def test_long_chinese_safe_preview_and_native_epoch_sort(self):
        row={'id':'id','title':'中文標題'*80,'updatedAt':1791158400000,'source':'Official metadata'}
        display=session_display(row,'claude')
        self.assertLessEqual(len(display['title']),110);self.assertIn('…',display['title'])
        self.assertGreater(display['sort_time'],0);self.assertIsNotNone(timestamp('2026-10-05T01:00:00Z'))
        safe=session_display({'id':'id'},'claude',preview='API_KEY=sk-testvalue123456\n查詢訂單')
        self.assertNotIn('sk-testvalue123456',safe['label'])

    def test_sort_refresh_and_active_header_preserve_exact_identity(self):
        panel=self.window.panels['codex'];sid='opaque-codex-0'
        panel.refresh_sessions(self.core.sessions('codex'),sid)
        self.assertEqual(panel.session.currentData(),sid)
        self.assertIn('台灣訂單',panel.current_session_label.text())
        self.assertNotIn(sid,panel.current_session_label.text())
        panel.refresh_sessions(list(reversed(self.core.sessions('codex'))),sid)
        self.assertEqual(panel.session.currentData(),sid)
        self.assertIn(sid,panel.session.toolTip())

    def test_search_excludes_selection_without_sending_or_changing_draft(self):
        panel=self.window.panels['claude'];panel.input.setPlainText('尚未送出的中文內容')
        panel.session.setCurrentIndex(panel.session.findData('opaque-claude-0'))
        QTest.mouseClick(panel.session_search,Qt.LeftButton)
        panel.session_search.setText('海外訂單');QTest.qWait(20)
        self.assertIsNone(panel.session.currentData());self.assertEqual(panel.session.count(),1)
        panel.session_search.setText('台灣訂單');QTest.qWait(20)
        self.assertEqual(panel.session.count(),2)
        self.assertEqual(panel.input.toPlainText(),'尚未送出的中文內容')
        self.assertEqual(self.adapters['claude'].calls,[])

    def test_resume_uses_id_not_duplicate_display_and_rejects_other_repo(self):
        adapter=self.adapters['codex'];adapter.state='Connected';self.window.refresh_agent('codex')
        panel=self.window.panels['codex'];panel.session.setCurrentIndex(panel.session.findData('opaque-codex-0'))
        QTest.mouseClick(panel.resume_button,Qt.LeftButton);self.wait()
        self.assertEqual(adapter.session_id,'opaque-codex-0');self.assertEqual(adapter.calls,['resume_session'])
        with self.assertRaisesRegex(ValueError,'不同工作目錄'):
            self.core.resume_session('codex','opaque-codex-1')
        self.assertEqual(adapter.session_id,'opaque-codex-0');self.assertEqual(adapter.calls,['resume_session'])

    def test_details_copy_exact_opaque_id_only_when_clicked(self):
        display=session_display({'id':'opaque:abc+/==','title':'中文對話'},'dot')
        dialog=SessionDetailsDialog(display,self.window);dialog.show();dialog.raise_();dialog.activateWindow();QTest.qWait(150)
        clicked=[];copy=dialog.findChild(QPushButton,'copy_session_id');copy.clicked.connect(lambda: clicked.append(True))
        QTest.mouseClick(copy,Qt.LeftButton);QTest.qWait(50)
        self.assertEqual(clicked,[True],'The actual Copy ID control must receive the click')
        self.assertEqual(self.app.clipboard().text(),'opaque:abc+/==');dialog.close()

    def test_offline_cross_project_history_filter_preview_select_no_resume(self):
        dialog=SessionHistoryDialog(self.window,'dot');dialog.show();QTest.qWait(20)
        self.assertEqual(dialog.table.topLevelItemCount(),2)
        first=dialog.table.topLevelItem(0);dialog.table.setCurrentItem(first);QTest.qWait(20)
        self.assertIn('檢查訂單搜尋',dialog.transcript.toPlainText())
        self.assertNotIn('opaque-',first.text(0)+first.text(1))
        QTest.mouseClick(dialog.findChild(QPushButton,'select_history_session'),Qt.LeftButton)
        self.assertEqual(self.window.panels['dot'].session.currentData(),'opaque-dot-1')
        self.assertEqual(self.adapters['dot'].calls,[])
        dialog.close()

    def test_native_metadata_dialog_keeps_row_identity_and_search_offline(self):
        dialog=NativeSessionDialog(self.window,'claude');dialog.show()
        rows=[{'id':'native-1','cwd':self.projects[0]['repo_path'],'firstPrompt':'審查中文程式','updatedAt':1791158400000},
              {'id':'native-2','cwd':self.projects[1]['repo_path'],'title':'審查中文程式','updatedAt':1791158300000}]
        dialog.set_sessions(rows)
        first=dialog.table.topLevelItem(0);self.assertEqual(first.data(0,Qt.UserRole)['id'],'native-1')
        self.assertNotIn('native-1',' '.join(first.text(i) for i in range(5)))
        self.assertIn('台灣訂單',first.text(0));self.assertEqual(first.text(1),'審查中文程式')
        dialog.table.setCurrentItem(first);dialog.search.setText('海外訂單');QTest.qWait(20)
        self.assertIsNone(dialog.table.currentItem());self.assertTrue(first.isHidden());dialog.close()
        self.assertEqual(self.adapters['claude'].calls,[])

    def test_imported_first_prompt_directory_and_time_survive_offline_reload(self):
        record={'id':'native-imported','firstPrompt':'真正索引提供的標題',
                'directory':self.projects[0]['repo_path'],'updatedAt':1791158400000,'source':'Official existing metadata'}
        row=self.core.import_session('claude',record)
        self.assertEqual(row['title'],record['firstPrompt']);self.assertEqual(row['cwd'],record['directory'])
        self.window.close();self.window.deleteLater();QTest.qWait(20)
        if not self.core._closed:self.core.close()
        self.core=WorkspaceCore(self.root/'data',self.adapters)
        self.window=MainWindow(self.core);self.window.resize(1750,1100);self.window.show();QTest.qWait(20)
        panel=self.window.panels['claude'];index=panel.session.findData('native-imported')
        self.assertGreater(index,0);self.assertIn('真正索引提供的標題',panel.session.itemText(index))
        self.assertEqual(panel.session.itemData(index),'native-imported')
        self.assertEqual(self.adapters['claude'].calls,[])

    def test_project_task_handoff_names_and_ids_remain_separate(self):
        projecttext=self.window.project_combo.currentText();tasktext=self.window.task_combo.currentText()
        self.assertIn('訂單管理',projecttext);self.assertIn('台灣訂單',projecttext)
        self.assertIn('修復查詢',tasktext);self.assertNotIn(self.task['id'],tasktext)
        self.core.store.update('messages',{'id':'m-claude-0'},{'role':'assistant'})
        message=self.core.store.get('messages',{'id':'m-claude-0'})
        dialog=HandoffDialog(self.window,message,'dot');dialog.show();QTest.qWait(20)
        self.assertEqual(dialog.preview['source_session'],'opaque-claude-0')
        self.assertEqual(dialog.preview['source_message'],message['content'])
        self.assertEqual(dialog.preview['status'],'prepared');dialog.close()

class WorkerWaitHelperTests(unittest.TestCase):
    """Check the real helpers without starting windows or changing their budgets."""
    def helpers(self):
        import test_dot_ui
        import test_session_labels
        return ((test_dot_ui, test_dot_ui.DotOfflineUITests, 10),
                (test_session_labels, HumanSessionLabels, 5))

    def test_worker_polling_yields_and_drains_completion(self):
        from types import SimpleNamespace
        for module, case_type, budget in self.helpers():
            with self.subTest(helper=case_type.__name__):
                case=case_type('runTest'); workers={object()}; events=[]
                case.window=SimpleNamespace(workers=workers, poll_events=lambda:events.append('poll'))
                def qwait(milliseconds):
                    self.assertEqual(milliseconds,20)
                    events.append('qt')
                    if 'yield' in events:workers.clear()
                def sleep(seconds):
                    self.assertEqual(seconds,.001);events.append('yield')
                with patch.object(module.time,'monotonic',side_effect=[100,100,100]), \
                        patch.object(module.time,'sleep',side_effect=sleep), \
                        patch.object(module.QTest,'qWait',side_effect=qwait):
                    case.wait()
                self.assertEqual(events,['qt','yield','qt','yield','poll','qt'])
                self.assertFalse(workers)

    def test_worker_timeout_still_fails_at_original_deadline(self):
        from types import SimpleNamespace
        for module, case_type, budget in self.helpers():
            with self.subTest(helper=case_type.__name__):
                case=case_type('runTest'); workers={object()}; polled=[]
                case.window=SimpleNamespace(workers=workers, poll_events=lambda:polled.append(True))
                with patch.object(module.time,'monotonic',side_effect=[100,100+budget]), \
                        patch.object(module.time,'sleep') as sleep, \
                        patch.object(module.QTest,'qWait') as qwait:
                    with self.assertRaises(AssertionError):case.wait()
                self.assertTrue(workers);self.assertEqual(polled,[])
                sleep.assert_not_called();qwait.assert_not_called()

if __name__=='__main__':unittest.main()
