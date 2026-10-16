"""Offline source packaging and test-runner boundaries; no installed app changes."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts import package_source, run_tests


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, relative, value='fixture'):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding='utf-8')
        return path

    def source_fixture(self):
        for name in package_source.FIXED:
            self.write(name)
        for name in package_source.TREES:
            (self.root / name).mkdir(parents=True, exist_ok=True)
        self.write('tests/fixtures/g8-dot-contract-sample.json', '{}')
        self.write('tools/chatgpt-dot-cli-pinned/LICENSE')
        self.write('acw/ui.py', '# source')
        self.write('acw/assets/arrow.png', 'asset')

    def test_package_excludes_machine_data_and_runtime_but_keeps_assets(self):
        self.source_fixture()
        excluded = (
            'config/local-llm.json', '.env', 'tests/fixtures/g8-dot-observed.json',
            'test-data/workspace.sqlite3', 'evidence/result.json',
            'vendor/runtime.py', 'acw/__pycache__/ui.py',
            'scripts/.env.local', 'docs/evidence/private.md',
            'tools/claude-session-sdk/node_modules/pkg/package.json',
            'tools/claude-session-sdk/auth.json',
        )
        for name in excluded:
            self.write(name, 'private fixture')
        output = self.root / 'source.zip'
        package_source.package(self.root, output)
        with zipfile.ZipFile(output) as archive:
            names = archive.namelist()
            self.assertFalse(set(excluded).intersection(names))
            self.assertIn('acw/ui.py', names)
            self.assertIn('acw/assets/arrow.png', names)
            self.assertIn('tools/chatgpt-dot-cli-pinned/LICENSE', names)
            manifest = json.loads(archive.read('SOURCE-MANIFEST.json'))
            self.assertEqual({row['path'] for row in manifest['files']}, set(names) - {'SOURCE-MANIFEST.json'})
            for row in manifest['files']:
                import hashlib
                self.assertEqual(hashlib.sha256(archive.read(row['path'])).hexdigest(), row['sha256'])

    def test_package_never_overwrites_existing_output(self):
        self.source_fixture()
        output = self.write('source.zip', 'existing file')
        with self.assertRaises(FileExistsError):
            package_source.package(self.root, output)
        self.assertEqual(output.read_text(), 'existing file')

    def test_missing_required_source_does_not_create_archive(self):
        with self.assertRaises(ValueError):
            package_source.package(self.root, self.root / 'source.zip')
        self.assertFalse((self.root / 'source.zip').exists())

    def test_runner_disables_inherited_live_flags_without_mutating_parent(self):
        with patch.dict(os.environ, {'ACW_CODEX_LIVE': '1', 'ACW_CODEX_TOOLS': '1'}):
            env = run_tests.child_environment()
            self.assertNotIn('ACW_CODEX_LIVE', env)
            self.assertNotIn('ACW_CODEX_TOOLS', env)
            self.assertEqual(env['QT_QPA_PLATFORM'], 'offscreen')
            self.assertEqual(os.environ['ACW_CODEX_LIVE'], '1')

    def test_runner_separates_modules_and_keeps_failure_report(self):
        self.write('tests/test_one.py')
        self.write('tests/test_two.py')
        self.write('tests/legacy_ui/test_old.py')
        results = [subprocess.CompletedProcess([], 0), subprocess.CompletedProcess([], 1)]
        with patch.object(run_tests, 'ROOT', self.root), patch.object(run_tests.subprocess, 'run', side_effect=results) as process, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run_tests.main([]), 1)
        self.assertEqual(process.call_count, 2)
        self.assertEqual([call.args[0][-2] for call in process.call_args_list], ['test_one', 'test_two'])
        report = json.loads(next((self.root / 'evidence').rglob('result.json')).read_text())
        self.assertEqual(report['status'], 'FAIL')
        self.assertEqual([row['status'] for row in report['modules']], ['PASS', 'FAIL'])

    def test_runner_surfaces_skips_without_hiding_failures(self):
        self.write('tests/test_one.py')
        self.write('tests/test_two.py')
        def run(command, **kwargs):
            failed = command[-2] == 'test_two'
            kwargs['stdout'].write('FAILED (failures=1, skipped=2)\n' if failed else 'OK (skipped=1)\n')
            return subprocess.CompletedProcess(command, int(failed))
        output = io.StringIO()
        with patch.object(run_tests, 'ROOT', self.root), \
                patch.object(run_tests.subprocess, 'run', side_effect=run), contextlib.redirect_stdout(output):
            self.assertEqual(1, run_tests.main([]))
        report = json.loads(next((self.root / 'evidence').rglob('result.json')).read_text())
        self.assertEqual('FAIL', report['status'])
        self.assertEqual([True, True], [row['skipped'] for row in report['modules']])
        self.assertEqual([1, 2], [row['skipped_count'] for row in report['modules']])
        self.assertIn('PASS (skipped) test_one', output.getvalue())
        self.assertIn('FAIL test_two', output.getvalue())

    def test_runner_timeout_is_reported_as_failure(self):
        self.write('tests/test_one.py')
        with patch.object(run_tests, 'ROOT', self.root), patch.object(run_tests.subprocess, 'run', side_effect=subprocess.TimeoutExpired('fixture', 1)), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run_tests.main(['--timeout', '1']), 1)
        report = json.loads(next((self.root / 'evidence').rglob('result.json')).read_text())
        self.assertEqual(report['modules'][0]['status'], 'TIMEOUT')

    def test_runner_rejects_unknown_module_before_process_or_report(self):
        self.write('tests/test_one.py')
        with patch.object(run_tests, 'ROOT', self.root), patch.object(run_tests.subprocess, 'run') as process, contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            run_tests.main(['../not_a_test'])
        process.assert_not_called()
        self.assertFalse((self.root / 'evidence').exists())


if __name__ == '__main__':
    unittest.main()
