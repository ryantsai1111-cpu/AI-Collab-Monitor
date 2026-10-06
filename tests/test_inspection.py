import tempfile,unittest
import hashlib
import subprocess
from unittest.mock import patch
from pathlib import Path
from acw.inspection import GIT,LegacyReader,diff_sides,parse_test_result,git_read,git_snapshot,git_diff
from acw.adapters.dot import DotAdapter
class InspectionTests(unittest.TestCase):
 def test_legacy_incremental_unicode_and_truncation(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'logs').mkdir();p=root/'logs'/'claude.log'
   raw='中文🙂\n'.encode();p.write_bytes(raw[:4]);reader=LegacyReader(root,chunk_size=4)
   text=''.join(x['content'] for x in reader.poll())
   with p.open('ab') as f:f.write(raw[4:])
   for _ in range(5):text+=''.join(x['content'] for x in reader.poll())
   self.assertEqual(text,'中文🙂\n');self.assertEqual(reader.poll(),[])
   p.write_text('new',encoding='utf-8');self.assertEqual(reader.poll()[0]['content'],'new')
 def test_diff_and_tests(self):
  l,r=diff_sides('@@ 1 @@\n-old\n+new');self.assertIn('old',l);self.assertNotIn('old',r)
  parsed=parse_test_result('pytest','8 passed, 1 failed, 2 skipped',1,2.1)
  self.assertEqual((parsed['passed'],parsed['failed'],parsed['skipped']),(8,1,2))
 def test_git_write_prohibited(self):
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(ValueError):git_read(d,'commit')
 def test_dot_honest_boundary(self):
  events=[];a=DotAdapter(lambda t,**p:events.append((t,p)))
  self.assertFalse(a.connect());self.assertNotEqual(a.state,'Connected')
  self.assertEqual(a.list_models(),[]);self.assertFalse(a.capabilities.supports_streaming)
  a.set_project('C:/no-filesystem',{'name':'Isolated test'})
  self.assertEqual(a.cwd,'');self.assertEqual(a.metadata['name'],'Isolated test')
  with self.assertRaises(RuntimeError):a.send_message('test')

@unittest.skipUnless(Path(GIT).is_file(), 'Native Git executable is unavailable')
class NativeGitInspectionTests(unittest.TestCase):
    """Real Git operations only in new disposable fixture repositories.

    Fixture setup writes commits/branches in its temporary repo. All inspected
    application operations are read-only and never target an existing repo.
    """
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='acw-git-inspection-')
        self.addCleanup(self.directory.cleanup)
        self.repo = Path(self.directory.name)
        self.fixture_git('init', '--initial-branch=main')

    def fixture_git(self, *args):
        result = subprocess.run(
            [GIT, '--no-pager', '-c', 'core.hooksPath=NUL', '-c', 'core.fsmonitor=false',
             '-c', 'commit.gpgsign=false', '-c', 'user.name=ACW Isolated Test',
             '-c', 'user.email=acw-isolated@example.invalid', '-C', str(self.repo), *args],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=20, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def write(self, name, text):
        target = self.repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')

    def commit_initial(self):
        self.write('sample.txt', 'original line\n')
        self.fixture_git('add', '--', 'sample.txt')
        self.fixture_git('commit', '-m', 'isolated initial fixture')

    def test_no_upstream_has_unknown_divergence_counts(self):
        self.commit_initial()
        state = git_snapshot(self.repo)
        self.assertEqual(state['branch'], 'main')
        self.assertFalse(state['has_upstream'])
        self.assertIsNone(state['upstream'])
        self.assertIsNone(state['ahead'])
        self.assertIsNone(state['behind'])
        self.assertEqual(state['divergence'], 'no_upstream')
        self.assertTrue(state['is_git'])
        self.assertEqual(state['status_result']['exit_code'], 0)

    def test_existing_upstream_reports_actual_ahead_behind(self):
        self.commit_initial()
        self.fixture_git('branch', 'upstream')
        self.fixture_git('branch', '--set-upstream-to=upstream', 'main')
        state = git_snapshot(self.repo)
        self.assertEqual((state['ahead'], state['behind']), (0, 0))
        self.assertEqual(state['upstream'], 'upstream')
        self.assertTrue(state['has_upstream'])
        self.write('sample.txt', 'second commit\n')
        self.fixture_git('add', '--', 'sample.txt')
        self.fixture_git('commit', '-m', 'isolated second fixture')
        state = git_snapshot(self.repo)
        self.assertEqual((state['ahead'], state['behind']), (1, 0))
        self.assertEqual(state['divergence'], 'known')

    def test_unborn_untracked_repo_explicitly_has_no_patch(self):
        self.write('new.txt', 'untracked fixture\n')
        state = git_snapshot(self.repo)
        self.assertTrue(state['unborn'])
        self.assertTrue(state['dirty'])
        result = git_diff(self.repo)
        self.assertEqual(result['exit_code'], 0)
        self.assertTrue(result['unborn'])
        self.assertEqual(result['untracked_count'], 1)
        self.assertEqual(result['stdout'], '')
        self.assertIn('no commits', result['notice'])
        self.assertIn('untracked files', result['notice'])
        self.assertNotIn('No tracked changes', result['notice'])
        self.assertEqual(len(result['listing_results']), 2)

    def test_unborn_staged_and_unstaged_patches_preserved_separately(self):
        self.write('new file.txt', 'staged line\n')
        self.fixture_git('add', '--', 'new file.txt')
        self.write('new file.txt', 'worktree line\n')
        result = git_diff(self.repo)
        self.assertEqual(result['exit_code'], 0, result['stderr'])
        self.assertEqual(result['changed_files'], ['new file.txt'])
        self.assertEqual([x['scope'] for x in result['components']],
                         ['staged additions', 'unstaged tracked edits'])
        self.assertIn('+staged line', result['components'][0]['stdout'])
        self.assertIn('-staged line', result['components'][1]['stdout'])
        self.assertIn('+worktree line', result['components'][1]['stdout'])
        self.assertIn('new file mode', result['stdout'])
        for component in result['components']:
            self.assertEqual(component['exit_code'], 0)
            self.assertIn('stderr', component)
            self.assertEqual(component['cwd'], str(self.repo))

    def test_unified_and_side_by_side_show_native_modification_and_deletion(self):
        self.commit_initial()
        self.write('sample.txt', 'updated line\n')
        result = git_diff(self.repo)
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual(result['changed_files'], ['sample.txt'])
        self.assertIn('-original line', result['stdout'])
        self.assertIn('+updated line', result['stdout'])
        left, right = diff_sides(result['stdout'])
        self.assertIn('original line', left)
        self.assertNotIn('updated line', left)
        self.assertIn('updated line', right)
        self.assertNotIn('original line', right)
        (self.repo / 'sample.txt').unlink()
        deletion = git_diff(self.repo)
        self.assertIn('deleted file mode', deletion['stdout'])
        self.assertEqual(deletion['changed_files'], ['sample.txt'])

    def test_known_credential_filenames_excluded_before_diff(self):
        self.commit_initial()
        self.write('auth.json', '{"fixture": "synthetic excluded content"}\n')
        self.fixture_git('add', '--', 'auth.json')
        self.write('sample.txt', 'public fixture\n')
        result = git_diff(self.repo)
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual(result['changed_files'], ['sample.txt'])
        self.assertEqual(result['excluded_path_count'], 1)
        self.assertNotIn('synthetic excluded content', result['stdout'])
        self.assertNotIn('auth.json', result['stdout'])
        self.assertIn('excluded', result['notice'])

    def test_status_diff_branch_log_do_not_modify_fixture_repository(self):
        self.commit_initial()
        self.write('sample.txt', 'visible worktree change\n')
        def fingerprints():
            return {str(p.relative_to(self.repo)):hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in self.repo.rglob('*') if p.is_file()}
        before = fingerprints()
        self.assertTrue(git_snapshot(self.repo)['dirty'])
        self.assertIn('+visible worktree change', git_diff(self.repo)['stdout'])
        self.assertEqual(git_read(self.repo, 'branch', '--show-current')['stdout'].strip(), 'main')
        history = git_read(self.repo, 'log', '-8', '--format=%h %s')
        self.assertEqual(history['exit_code'], 0)
        self.assertIn('isolated initial fixture', history['stdout'])
        self.assertEqual(fingerprints(), before)
        self.assertFalse((self.repo / '.git' / 'index.lock').exists())

    def test_git_error_keeps_stderr_exit_and_command(self):
        malformed = git_read(self.repo, 'status', '--this-option-does-not-exist')
        self.assertNotEqual(malformed['exit_code'], 0)
        self.assertIn('unknown option', malformed['stderr'])
        self.assertIn('--this-option-does-not-exist', malformed['command'])
        empty = self.repo / 'not-a-repository'
        empty.mkdir()
        # Outside this test repository, not a nested directory Git can discover.
        with tempfile.TemporaryDirectory(prefix='acw-nonrepo-') as unrelated:
            state = git_snapshot(unrelated)
            result = git_diff(unrelated)
            self.assertFalse(state['is_git'])
            self.assertEqual(state['divergence'], 'unknown')
            self.assertNotEqual(result['exit_code'], 0)
            self.assertIn('not a git repository', result['stderr'])
            self.assertIn('status', result['command'])
            self.assertEqual(result['stdout'], '')
            self.assertIn('failed', result['notice'])

    def test_unborn_log_failure_is_not_a_successful_empty_history(self):
        history = git_read(self.repo, 'log', '-8', '--format=%h %s')
        self.assertNotEqual(history['exit_code'], 0)
        self.assertIn('does not have any commits', history['stderr'])
        self.assertEqual(history['stdout'], '')

    def test_mutation_and_external_execution_options_are_rejected(self):
        forbidden = [('commit',), ('push',), ('merge', 'main'), ('branch', '-D', 'main'),
                     ('branch', 'new-name'), ('diff', '--output=result.patch'),
                     ('log', '--output', 'result.log'), ('diff', '--ext-diff'),
                     ('diff', '--textconv'), ('diff', '--no-index', 'one', 'two'),
                     ('status', '--config-env=x=y')]
        for args in forbidden:
            with self.subTest(args=args), self.assertRaises(ValueError):
                git_read(self.repo, *args)
        self.assertFalse((self.repo / 'result.patch').exists())
        self.assertFalse((self.repo / 'result.log').exists())

    def test_process_flags_disable_pager_locks_hooks_and_diff_helpers(self):
        self.commit_initial()
        real_run = subprocess.run
        calls = []
        def capture(*args, **kwargs):
            calls.append((args[0], kwargs))
            return real_run(*args, **kwargs)
        with patch('acw.inspection.subprocess.run', side_effect=capture):
            git_read(self.repo, 'diff', 'HEAD', '--', 'sample.txt')
            git_read(self.repo, 'log', '-1', '--format=%h')
        for argv, options in calls:
            self.assertIn('--no-pager', argv)
            self.assertIn('--no-optional-locks', argv)
            self.assertIn('--literal-pathspecs', argv)
            self.assertIn('core.hooksPath=NUL', argv)
            self.assertIn('core.fsmonitor=false', argv)
            self.assertIn('--no-ext-diff', argv)
            self.assertIn('--no-textconv', argv)
            self.assertFalse(options.get('shell', False))

    def test_literal_wildcard_path_does_not_expand_to_credential_path(self):
        self.commit_initial()
        self.write('[a]uth.json', 'literal public filename\n')
        self.write('auth.json', 'synthetic excluded content\n')
        self.fixture_git('add', '--', '[a]uth.json', 'auth.json')
        result = git_diff(self.repo)
        self.assertIn('[a]uth.json', result['changed_files'])
        self.assertIn('literal public filename', result['stdout'])
        self.assertNotIn('synthetic excluded content', result['stdout'])


if __name__=='__main__':unittest.main()
