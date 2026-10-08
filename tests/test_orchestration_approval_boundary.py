"""A user-started collaboration run must still wait for explicit tool approval."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
import test_approvals as fixtures


class CollaborationApprovalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    setUp = fixtures.WindowTests.setUp

    def tearDown(self):
        self.window.orchestrator = None
        fixtures.WindowTests.tearDown(self)

    def test_active_run_never_uses_mode_or_always_allow_rule(self):
        self.window.orchestrator = SimpleNamespace(active=True)
        self.panel.approval_rules.add('cmd:python')
        for mode in ('ask', 'edits', 'all'):
            with self.subTest(mode=mode):
                self.core.set_setting('agent.claude', {'approval_mode': mode})
                with patch('acw.ui.approvals.decide', return_value=True) as decide, patch.object(self.window, 'run') as dispatch:
                    result = self.window.auto_approve('claude', {'details': fixtures.bash('python -V')}, 'approval-test')
                self.assertFalse(result)
                decide.assert_not_called()
                dispatch.assert_not_called()
                self.assertEqual(mode, self.window.approval_mode('claude'))

    def test_non_running_workspace_retains_existing_approval_behavior(self):
        for run in (None, SimpleNamespace(active=False)):
            with self.subTest(run=run):
                self.window.orchestrator = run
                with patch('acw.ui.approvals.decide', return_value=True), patch.object(self.window, 'run') as dispatch:
                    self.assertTrue(self.window.auto_approve('claude', {'details': fixtures.bash('python -V')}, 'approval-test'))
                dispatch.assert_called_once()


if __name__ == '__main__':
    unittest.main()
