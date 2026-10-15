"""Offline migration and fourth-role persistence acceptance."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from acw.core import WorkspaceCore
from acw.store import Store
from tests.test_core import SyntheticAdapter


class LocalStoreTests(unittest.TestCase):
    def test_old_schema_upgrade_preserves_every_column_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'workspace.sqlite3'
            with closing(sqlite3.connect(path)) as db:
                db.executescript("""
                    CREATE TABLE projects (
                        id TEXT PRIMARY KEY, name TEXT NOT NULL, repo_path TEXT NOT NULL,
                        default_branch TEXT DEFAULT '', active_branch TEXT DEFAULT '',
                        claude_cwd TEXT DEFAULT '', codex_cwd TEXT DEFAULT '', dot_metadata TEXT DEFAULT '',
                        notes TEXT DEFAULT '', created_at TEXT NOT NULL, metadata TEXT DEFAULT '{}');
                    CREATE TABLE tasks (
                        id TEXT PRIMARY KEY, title TEXT NOT NULL, project_id TEXT REFERENCES projects(id),
                        repo TEXT DEFAULT '', branch TEXT DEFAULT '', created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'NEW',
                        claude_session TEXT DEFAULT '', dot_session TEXT DEFAULT '', codex_session TEXT DEFAULT '',
                        created_by TEXT DEFAULT 'user', current_owner TEXT DEFAULT 'user', notes TEXT DEFAULT '',
                        metadata TEXT DEFAULT '{}');
                    INSERT INTO projects VALUES ('p', 'Existing Project', 'C:/repo', 'main', 'feature',
                        'C:/claude', 'C:/codex', 'dot metadata', 'project notes', '2026-10-01', '{"legacy":1}');
                    INSERT INTO tasks VALUES ('t', 'Existing Task', 'p', 'C:/repo', 'feature', '2026-10-01',
                        '2026-10-02', 'READY', 'c-session', 'd-session', 'x-session', 'Ryan', 'Claude',
                        'task notes', '{"legacy":2}');
                """)
                db.row_factory = sqlite3.Row
                before = {table: dict(db.execute(f'SELECT * FROM {table}').fetchone())
                          for table in ('projects', 'tasks')}
                db.commit()
            for _ in range(2):
                store = Store(temporary)
                try:
                    for table, new_column in (('projects', 'local_cwd'), ('tasks', 'local_session')):
                        columns = [row['name'] for row in store.query(f'PRAGMA table_info({table})')]
                        self.assertEqual(1, columns.count(new_column))
                        row = dict(store.db.execute(f'SELECT * FROM {table}').fetchone())
                        self.assertEqual('', row.pop(new_column))
                        self.assertEqual(before[table], row)
                finally:
                    store.close()

    def test_fresh_database_and_local_audit_are_supported(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(temporary)
            try:
                self.assertIn('local_cwd', [r['name'] for r in store.query('PRAGMA table_info(projects)')])
                self.assertIn('local_session', [r['name'] for r in store.query('PRAGMA table_info(tasks)')])
                reference = store.append_raw('local', {'content': 'local audit'})
                self.assertTrue(reference.startswith('raw/local.jsonl:'))
                self.assertEqual('local audit', store.read_raw(reference)['content'])
            finally:
                store.close()


class LocalCoreTests(unittest.TestCase):
    def test_local_session_create_resume_only_updates_local_column(self):
        with tempfile.TemporaryDirectory() as temporary:
            adapters = {agent: SyntheticAdapter(agent) for agent in ('claude', 'dot', 'codex', 'local')}
            core = WorkspaceCore(Path(temporary) / 'data', adapters)
            try:
                core.git_snapshot = lambda *args: {'branch': 'fixture'}
                project = core.create_project('Fixture', temporary)
                self.assertEqual(project['repo_path'], project['local_cwd'])
                core.select_project(project['id'])
                task = core.create_task('Local task')
                for agent in ('claude', 'dot', 'codex'):
                    core.store.update('tasks', {'id': task['id']}, {agent + '_session': agent + '-original'})
                core.connect('local')
                created = core.create_session('local')
                self.assertEqual(created, core.current_task['local_session'])
                core.resume_session('local', 'local-resumed')
                after = core.current_task
                self.assertEqual('local-resumed', after['local_session'])
                self.assertEqual(project['repo_path'], adapters['local'].cwd)
                for agent in ('claude', 'dot', 'codex'):
                    self.assertEqual(agent + '-original', after[agent + '_session'])
                self.assertEqual('local-resumed', core._context('local')['session_id'])
            finally:
                core.close()

    def test_reconnect_replaces_legacy_harness_without_carrying_its_session(self):
        from acw.adapters.local import LocalCodexAdapter
        from test_hermes_core import HermesFixture
        with tempfile.TemporaryDirectory() as temporary:
            core = WorkspaceCore(Path(temporary) / 'data')
            try:
                adapter = LocalCodexAdapter(core.make_emitter('local'), codex_executable='codex.exe',
                                            claude_executable='claude.exe')
                core.set_adapter('local', adapter)
                adapter.session_id = 'missing-native-session'
                adapter._resume = True
                core.set_setting('agent.local', {'harness': 'hermes', 'hermes_executable': 'hermes.exe',
                                                'provider': 'fixture-provider', 'model': 'custom-model'})
                replacement = HermesFixture()
                with patch('acw.adapters.hermes.HermesAdapter', return_value=replacement) as factory:
                    core.connect('local')
                self.assertIs(replacement, core.adapters['local'])
                self.assertEqual('hermes', replacement.local_harness)
                self.assertEqual('', replacement.session_id)
                self.assertEqual('', replacement.native_session_id)
                self.assertEqual('hermes.exe', factory.call_args.kwargs['hermes_executable'])
                self.assertEqual('custom-model', factory.call_args.kwargs['model'])
                self.assertNotIn('codex_executable', factory.call_args.kwargs)
                self.assertNotIn('claude_executable', factory.call_args.kwargs)
                self.assertEqual('fixture-provider', core.get_setting('agent.local')['provider'])
            finally:
                core.close()

    def test_local_session_cannot_resume_through_different_harness(self):
        from acw.adapters.local import LocalCodexAdapter, LocalClaudeAdapter
        with tempfile.TemporaryDirectory() as temporary:
            core = WorkspaceCore(Path(temporary) / 'data')
            try:
                core.git_snapshot = lambda *args: {'branch': 'fixture'}
                project = core.create_project('Fixture', temporary)
                core.select_project(project['id'], sync=False)
                core.create_task('Fixture')
                codex = LocalCodexAdapter(core.make_emitter('local'))
                core.set_adapter('local', codex)
                codex.cwd = temporary
                core._map_session('local', 'codex-fixture-thread')
                self.assertEqual('codex', core.sessions('local')[0]['metadata']['local_harness'])
                claude = LocalClaudeAdapter(core.make_emitter('local'))
                claude.capabilities.supports_sessions = True
                core.set_adapter('local', claude)
                with patch.object(claude, 'resume_session') as resume:
                    with self.assertRaisesRegex(ValueError, '不同 Harness'):
                        core.resume_session('local', 'codex-fixture-thread')
                    resume.assert_not_called()
                self.assertEqual('codex-fixture-thread', core.current_task['local_session'])
            finally:
                core.close()


if __name__ == '__main__':
    unittest.main()
