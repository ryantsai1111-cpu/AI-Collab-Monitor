"""Offline regressions for blank settings and desktop update reconnection."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from acw.adapters.codex import CodexAdapter
from acw.core import WorkspaceCore


@unittest.skipUnless(os.name == 'nt', 'Windows desktop executable discovery')
class CodexDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.local = Path(self.temporary.name)
        self.root = self.local / 'OpenAI/Codex/bin'
        self.environment = patch.dict(os.environ, LOCALAPPDATA=str(self.local))
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.adapter = CodexAdapter(lambda *args, **kwargs: None)

    def binary(self, build, modified):
        path = self.root / build / 'codex.exe'
        path.parent.mkdir(parents=True)
        path.write_bytes(b'fixture, never executed')
        os.utime(path, (modified, modified))
        return str(path)

    def connect(self):
        process = MagicMock()
        process.poll.return_value = None
        with patch('acw.adapters.codex.subprocess.Popen', return_value=process) as popen, \
             patch('acw.adapters.codex.threading.Thread'), \
             patch.object(self.adapter, '_request', return_value={'data': []}):
            self.adapter.connect()
        self.assertEqual('Connected', self.adapter.state)
        return popen.call_args.args[0]

    def test_blank_setting_selects_newest_native_binary_before_path_wrapper(self):
        self.binary('old', 100)
        newest = self.binary('new', 200)
        with patch('acw.adapters.codex.shutil.which', return_value='codex.CMD') as which:
            self.assertEqual([newest, 'app-server', '--listen', 'stdio://'], self.connect())
        which.assert_not_called()

    def test_reconnect_refreshes_path_after_update(self):
        old = self.binary('old', 100)
        self.assertEqual(old, self.connect()[0])
        newest = self.binary('new', 200)
        self.adapter._process.poll.return_value = 0
        self.adapter.state = 'Disconnected'
        self.assertEqual(newest, self.connect()[0])

    def test_saved_removed_desktop_build_selects_current_build(self):
        self.adapter.executable = str(self.root / 'removed/codex.exe')
        newest = self.binary('new', 200)
        self.assertEqual(newest, self.connect()[0])

    def test_custom_override_is_preserved_even_if_desktop_exists(self):
        self.binary('new', 200)
        self.adapter.executable = str(self.local / 'custom/codex.exe')
        self.assertEqual(self.adapter.executable, self.connect()[0])

    def test_similar_directory_name_is_not_treated_as_managed(self):
        self.binary('new', 200)
        custom = str(self.local / 'Other/OpenAI/Codex/bin/custom/codex.exe')
        self.adapter.executable = custom
        self.assertEqual(custom, self.connect()[0])

    def test_connected_process_is_not_replaced_during_update(self):
        old = self.binary('old', 100)
        self.connect()
        self.binary('new', 200)
        with patch('acw.adapters.codex.subprocess.Popen') as popen:
            self.adapter.connect()
        popen.assert_not_called()
        self.assertEqual(old, self.adapter.executable)

    def test_path_fallback_is_refreshed_when_desktop_is_installed(self):
        with patch('acw.adapters.codex.shutil.which', return_value='codex.CMD'):
            self.assertEqual('codex.CMD', self.connect()[0])
        newest = self.binary('new', 200)
        self.adapter._process.poll.return_value = 0
        self.adapter.state = 'Disconnected'
        self.assertEqual(newest, self.connect()[0])

    def test_core_clears_custom_override_when_setting_becomes_blank(self):
        with tempfile.TemporaryDirectory() as data:
            core = WorkspaceCore(data, {'codex': self.adapter})
            try:
                self.adapter.executable = 'custom.exe'
                core.set_setting('agent.codex', {'executable': ''})
                with patch.object(self.adapter, 'connect') as connect:
                    core.connect('codex')
                connect.assert_called_once_with()
                self.assertEqual('', self.adapter.executable)
            finally:
                core.close()

    def test_startup_blank_settings_keep_detected_defaults_without_connection(self):
        import run
        newest = self.binary('new', 200)
        core = MagicMock()
        core.get_setting.side_effect = lambda key, *args: {'executable': ''} if key.startswith('agent.') else None
        core.adapters = {}
        with patch('sys.argv', ['run.py', '--data-dir', str(self.local / 'data')]), \
             patch.object(run, 'ROOT', self.local), \
             patch('PySide6.QtWidgets.QApplication'), \
             patch('PySide6.QtCore.QLockFile'), \
             patch('acw.core.WorkspaceCore', return_value=core), \
             patch('acw.ui.MainWindow'), \
             patch('acw.adapters.claude.ClaudeAdapter'), \
             patch('acw.adapters.dot.DotAdapter'), \
             patch('acw.adapters.hermes.HermesAdapter'), \
             patch('acw.adapters.codex.CodexAdapter') as adapter, \
             patch('subprocess.Popen') as popen:
            run.main()
        self.assertEqual(newest, adapter.call_args.kwargs['executable'])
        adapter.return_value.connect.assert_not_called()
        popen.assert_not_called()


if __name__ == '__main__':
    unittest.main()
