"""Fourth-role UI acceptance using the established offline substitutes."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QLineEdit, QMenu, QTabWidget

from acw.core import WorkspaceCore
from acw.ui import AGENTS, MessageCard
from tests.test_ui_refresh import OfflineAdapter, OfflineWindow


def offline_window(root):
    adapters = {agent: OfflineAdapter(agent) for agent in AGENTS}
    core = WorkspaceCore(root / 'data', adapters)
    core.git_snapshot = lambda *args, **kwargs: {
        'branch': 'fixture-branch', 'dirty': False, 'ahead': 0, 'behind': 0,
        'status': '', 'diff': '', 'log': '', 'is_git': False, 'error': ''}
    project = core.create_project('Offline UI acceptance', root)
    core.select_project(project['id'], sync=False)
    core.create_task('Local LLM panel acceptance')
    core.drain_events()
    return core, adapters, OfflineWindow(core)


class LocalUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.guards = [patch(target, side_effect=AssertionError('External I/O forbidden'))
                       for target in ('subprocess.Popen', 'socket.socket.connect', 'urllib.request.urlopen')]
        for guard in self.guards:
            guard.start()
        self.temp = tempfile.TemporaryDirectory()
        self.core, self.adapters, self.window = offline_window(Path(self.temp.name))
        self.window.show()
        self.settle()

    def tearDown(self):
        self.window.timer.stop()
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.core.close()
        self.temp.cleanup()
        for guard in reversed(self.guards):
            guard.stop()

    def settle(self):
        for _ in range(4):
            self.app.processEvents()
        QTest.qWait(10)

    def test_startup_and_event_poll_never_call_local_adapter(self):
        self.assertEqual([], self.adapters['local'].calls)
        self.window.poll_events()
        self.settle()
        self.assertEqual([], self.adapters['local'].calls)
        self.assertEqual('Local LLM', self.window.session_tabs.tabText(3))
        self.assertIn('Local LLM', self.window.role_tabs.tabText(3))
        panel = self.window.panels['local']
        self.assertEqual('請先在設定填入本地端點與模型名稱', panel.notice.text())
        self.assertFalse(panel.connect_button.isEnabled())

    def test_auto_layout_four_visible_wide_one_visible_narrow_without_scroll(self):
        self.window.resize(1900, 950)
        self.settle()
        self.window.update_workspace_layout()
        self.assertEqual(4, sum(panel.isVisible() for panel in self.window.panels.values()))
        for panel in self.window.panels.values():
            self.assertGreaterEqual(panel.width(), 300)
            self.assertTrue(panel.title.isVisible())
            self.assertTrue(panel.input.isVisible())
        self.window.resize(760, 720)
        self.settle()
        self.window.update_workspace_layout()
        self.assertEqual(1, sum(panel.isVisible() for panel in self.window.panels.values()))
        self.assertEqual(0, self.window.workspace_scroll.horizontalScrollBar().maximum())
        self.window.role_tabs.setCurrentIndex(3)
        self.settle()
        self.assertTrue(self.window.panels['local'].isVisible())
        self.assertEqual(0, self.window.workspace_scroll.horizontalScrollBar().maximum())

    def test_forward_menu_contains_local_and_flow_still_has_two_steps(self):
        panel = self.window.panels['claude']
        card = MessageCard({'id': 'fixture-message', 'role': 'assistant', 'content': 'Fixture response'}, panel)
        labels = [action.text() for action in card.forward_button.menu().actions()]
        self.assertEqual(['G8毛', 'Codex', 'Local LLM'], labels)
        menu = QMenu(self.window)
        self.window.populate_flow_menu(menu)
        self.assertEqual(4, len(menu.actions()))
        self.assertIn('Claude', menu.actions()[0].text())
        self.assertIn('G8毛', menu.actions()[1].text())
        self.assertFalse(any('Local LLM' in action.text() for action in menu.actions()))

    def test_settings_save_local_harness_endpoint_model_and_env_name(self):
        def accept(dialog):
            tabs = dialog.findChild(QTabWidget)
            self.assertIn('Local LLM', [tabs.tabText(i) for i in range(tabs.count())])
            harness = dialog.findChild(QComboBox, 'local_harness')
            harness.setCurrentIndex(harness.findData('claude'))
            for name, value in (('local_base_url', 'http://localhost:1234'),
                                ('local_model', 'fixture-local'), ('local_api_key_env', 'LOCAL_MODEL_KEY')):
                dialog.findChild(QLineEdit, name).setText(value)
            self.assertEqual('', dialog.findChild(QLineEdit, 'executable_local').text())
            return QDialog.Accepted
        with patch.object(QDialog, 'exec', accept):
            self.window.settings()
        saved = self.core.get_setting('agent.local')
        self.assertEqual('claude', saved['harness'])
        self.assertEqual('http://localhost:1234', saved['base_url'])
        self.assertEqual('fixture-local', saved['model'])
        self.assertEqual('fixture-local', saved['default_model'])
        self.assertEqual('LOCAL_MODEL_KEY', saved['api_key_env'])
        self.assertTrue(self.window.panels['local'].connect_button.isEnabled())
        self.assertIn('設定已備妥', self.window.panels['local'].notice.text())
        self.assertEqual([], self.adapters['local'].calls)

    def test_local_history_filter_uses_local_id_and_branch_label_updates(self):
        self.window.show_history('local')
        self.assertEqual('local', self.window.history_agent.currentData())
        self.assertEqual('Local LLM', self.window.history_agent.currentText())
        self.core.git_snapshot = lambda: {'branch': 'fixture-branch', 'is_git': True, 'dirty': False}
        self.window._git_clock = 100
        self.window.poll_events()
        self.assertIn('fixture-branch', self.window.panels['local'].branch_label.text())


def capture_native_evidence(target):
    """Opt-in visible Windows Qt screenshot; no inference or adapter operation."""
    app = QApplication.instance() or QApplication([])
    if app.platformName() != 'windows':
        raise RuntimeError('Native screenshot requires the Windows Qt platform, not offscreen')
    app.setStyle('Fusion')
    with tempfile.TemporaryDirectory() as temporary:
        core, adapters, window = offline_window(Path(temporary))
        try:
            window.resize(1900, 950)
            window.move(0, 0)
            window.show()
            window.raise_()
            QTest.qWait(600)
            app.processEvents()
            window.update_workspace_layout()
            app.processEvents()
            if window.size().width() != 1900 or window.size().height() != 950:
                raise AssertionError('Windows did not preserve the requested 1900x950 client size')
            for panel in window.panels.values():
                if not (panel.isVisible() and panel.title.isVisible() and panel.input.isVisible()):
                    raise AssertionError('All four native panel headings and inputs must be visible')
            if any(adapter.calls for adapter in adapters.values()):
                raise AssertionError('Native screenshot must not call any adapter')
            target = Path(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            screenshot = window.screen().grabWindow(int(window.winId()))
            if screenshot.isNull() or not screenshot.save(str(target)):
                raise RuntimeError('Windows native window capture failed')
            print(f'PASS native Windows screenshot: {screenshot.width()}x{screenshot.height()}, '
                  f'platform={app.platformName()}, font={app.font().family()}, four panels visible, no adapter calls')
        finally:
            window.close()
            core.close()


if __name__ == '__main__':
    unittest.main()
