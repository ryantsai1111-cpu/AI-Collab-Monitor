"""Offline persistence safety checks using only synthetic temporary fixtures."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from acw.store import Store


class StoreSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='acw-store-safety-')
        self.root = Path(self.temp.name).resolve()
        self.addCleanup(self.temp.cleanup)

    def new_store(self, name='data'):
        store = Store(self.root / name)
        self.addCleanup(store.close)
        return store

    def symlink(self, link, target, *, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except OSError as exc:
            if os.name == 'nt' and getattr(exc, 'winerror', None) == 1314:
                self.skipTest('Windows symlink creation requires Developer Mode or the create-symbolic-link privilege (WinError 1314)')
            raise

    def outside_file(self, name='outside.jsonl'):
        path = self.root / name
        path.write_bytes(b'{"outside":"synthetic sentinel"}\n')
        return path, path.read_bytes()

    def test_normal_append_redaction_offsets_and_permissions(self):
        store = self.new_store()
        record = {'content': '中文 🧪', 'password': 'SYNTHETIC_SECRET'}
        first = store.append_raw('dot', record)
        path = store.raw_dir / 'dot.jsonl'
        mode = stat.S_IMODE(path.stat().st_mode)
        directory_mode = stat.S_IMODE(store.raw_dir.stat().st_mode)
        first_size = path.stat().st_size
        with patch('os.chmod', side_effect=AssertionError('Permissions must not be changed')):
            second = store.append_raw('dot', {'content': 'second fixture'})
        self.assertEqual('raw/dot.jsonl:0', first)
        self.assertEqual(f'raw/dot.jsonl:{first_size}', second)
        self.assertEqual({'content': '中文 🧪', 'password': '[REDACTED]'}, store.read_raw(first))
        self.assertEqual({'content': 'second fixture'}, store.read_raw(second))
        self.assertEqual('SYNTHETIC_SECRET', record['password'])
        self.assertNotIn(b'SYNTHETIC_SECRET', path.read_bytes())
        self.assertEqual(mode, stat.S_IMODE(path.stat().st_mode))
        self.assertEqual(directory_mode, stat.S_IMODE(store.raw_dir.stat().st_mode))
        self.assertTrue(store.append_raw('../outside', {'safe': True}).startswith('raw/workspace.jsonl:'))

    def test_rotation_archives_and_restart_preserve_references(self):
        store = self.new_store()
        store.max_raw_bytes = 90
        refs = [store.append_raw('codex', {'index': index, 'content': 'ordinary ' + '中' * 25})
                for index in range(6)]
        self.assertEqual(6, len({ref.rsplit(':', 1)[0] for ref in refs}))
        self.assertTrue(list(store.raw_dir.glob('*.jsonl.gz')))
        for index, ref in enumerate(refs):
            self.assertEqual(index, store.read_raw(ref)['index'])
        store.close()
        reopened = self.new_store()
        for index, ref in enumerate(refs):
            self.assertEqual(index, reopened.read_raw(ref)['index'])

    def test_retention_expires_only_owned_segments(self):
        store = self.new_store()
        store.max_raw_bytes = 40
        first = store.append_raw('local', {'index': 0, 'content': 'first synthetic record'})
        store.append_raw('local', {'index': 1, 'content': 'second synthetic record'})
        archived = (store.data_dir / first.rsplit(':', 1)[0]).with_suffix('.jsonl.gz')
        unrelated = store.raw_dir / 'user-notes.jsonl'
        unrelated.write_text('ordinary user-owned fixture', encoding='utf-8')
        old = time.time() - 40 * 86400
        os.utime(archived, (old, old))
        os.utime(unrelated, (old, old))
        self.assertEqual(1, store.archive_logs())
        self.assertFalse(archived.exists())
        self.assertEqual('ordinary user-owned fixture', unrelated.read_text(encoding='utf-8'))
        with self.assertRaisesRegex(FileNotFoundError, 'retention'):
            store.read_raw(first)

    def test_archive_timestamp_dispatch_matches_platform_capabilities(self):
        real_utime = os.utime
        for capability in ('descriptor', 'no-follow', 'pathname'):
            with self.subTest(capability=capability):
                store = self.new_store(capability)
                source = store.raw_dir / 'dot-100.jsonl'
                source.write_bytes(b'{"content":"portable archive"}\n')
                stamp = time.time() - 2 * 86400
                real_utime(source, (stamp, stamp))
                stamp = source.stat().st_mtime

                def supported_utime(path, times, **options):
                    if capability == 'descriptor':
                        self.assertIsInstance(path, int)
                        self.assertEqual({}, options)
                    else:
                        if isinstance(path, int) or (options and capability == 'pathname'):
                            raise NotImplementedError('utime: unsupported on this Windows Python')
                        self.assertEqual({'follow_symlinks': False} if capability == 'no-follow' else {}, options)
                    # Exercise dispatch on every test host, including Windows
                    # hosts that cannot perform the simulated descriptor call.
                    real_utime(source.with_suffix('.jsonl.gz'), times)

                with patch('acw.store.os.utime', side_effect=supported_utime) as utime, \
                        patch('acw.store.os.supports_fd', {utime} if capability == 'descriptor' else set()), \
                        patch('acw.store.os.supports_follow_symlinks', {utime} if capability == 'no-follow' else set()):
                    self.assertEqual(1, store.archive_logs())
                    utime.assert_called_once()
                archived = source.with_suffix('.jsonl.gz')
                self.assertFalse(source.exists())
                self.assertAlmostEqual(stamp, archived.stat().st_mtime, places=3)
                store.close()
                reopened = self.new_store(capability)
                self.assertEqual({'content': 'portable archive'}, reopened.read_raw('raw/dot-100.jsonl:0'))
                reopened.retention_days = 1
                self.assertEqual(1, reopened.archive_logs())
                with self.assertRaisesRegex(FileNotFoundError, 'retention'):
                    reopened.read_raw('raw/dot-100.jsonl:0')

    def test_rotation_without_descriptor_or_no_follow_utime_preserves_references(self):
        store = self.new_store()
        store.max_raw_bytes = 40
        real_utime = os.utime

        def windows_utime(path, times, **options):
            if isinstance(path, int) or 'follow_symlinks' in options:
                raise NotImplementedError('utime: unsupported on this Windows Python')
            return real_utime(path, times)

        with patch('acw.store.os.utime', side_effect=windows_utime), \
                patch('acw.store.os.supports_fd', set()), \
                patch('acw.store.os.supports_follow_symlinks', set()):
            refs = [store.append_raw('dot', {'index': index, 'content': 'synthetic rotation'}) for index in range(4)]
        self.assertEqual(3, len(list(store.raw_dir.glob('*.jsonl.gz'))))
        for index, reference in enumerate(refs):
            self.assertEqual(index, store.read_raw(reference)['index'])

    def test_timestamp_failure_preserves_source_and_is_not_silenced(self):
        store = self.new_store()
        source = store.raw_dir / 'dot-100.jsonl'
        original = b'{"content":"ordinary source"}\n'
        source.write_bytes(original)
        with patch('acw.store.os.utime', side_effect=PermissionError('timestamp denied')), \
                patch('acw.store.os.supports_fd', set()), \
                patch('acw.store.os.supports_follow_symlinks', set()):
            with self.assertRaisesRegex(PermissionError, 'timestamp denied'):
                store.archive_logs()
        self.assertEqual(original, source.read_bytes())
        self.assertEqual({'content': 'ordinary source'}, store.read_raw('raw/dot-100.jsonl:0'))

    def test_pathname_timestamp_rejects_missing_or_replaced_target(self):
        store = self.new_store()
        opened_path = store.raw_dir / 'dot-100.jsonl.gz'
        other = store.raw_dir / 'dot-101.jsonl.gz'
        other.write_bytes(b'other managed file')
        with store._open_raw(opened_path, write=True) as handle:
            for target in (other, store.raw_dir / 'dot-102.jsonl.gz'):
                with self.subTest(target=target), \
                        patch('acw.store.os.utime') as utime, \
                        patch('acw.store.os.supports_fd', set()), \
                        patch('acw.store.os.supports_follow_symlinks', set()):
                    with self.assertRaisesRegex(PermissionError, 'changed before timestamp'):
                        store._set_raw_mtime(target, handle, time.time())
                    utime.assert_not_called()

    def test_pathname_timestamp_rejects_link_and_hardlink_redirects(self):
        store = self.new_store()
        outside, before = self.outside_file()
        stamp = outside.stat().st_mtime_ns
        link = store.raw_dir / 'dot-100.jsonl.gz'
        self.symlink(link, outside)
        hardlink = store.raw_dir / 'dot-101.jsonl.gz'
        os.link(outside, hardlink)
        with store._open_raw(store.raw_dir / 'dot-102.jsonl.gz', write=True) as handle:
            for target in (link, hardlink):
                with self.subTest(target=target), \
                        patch('acw.store.os.utime') as utime, \
                        patch('acw.store.os.supports_fd', set()), \
                        patch('acw.store.os.supports_follow_symlinks', set()):
                    with self.assertRaises(PermissionError):
                        store._set_raw_mtime(target, handle, time.time() - 100)
                    utime.assert_not_called()
        self.assertEqual(before, outside.read_bytes())
        self.assertEqual(stamp, outside.stat().st_mtime_ns)

    def test_pathname_timestamp_revalidates_reparse_attribute(self):
        store = self.new_store()
        target = store.raw_dir / 'dot-100.jsonl.gz'
        original_lstat = Path.lstat

        class ReparseMetadata:
            st_file_attributes = 0x400

            def __init__(self, metadata):
                self.metadata = metadata

            def __getattr__(self, name):
                return getattr(self.metadata, name)

        def lstat(path, *args, **kwargs):
            metadata = original_lstat(path, *args, **kwargs)
            return ReparseMetadata(metadata) if path == target else metadata

        with store._open_raw(target, write=True) as handle, \
                patch.object(Path, 'lstat', lstat), \
                patch('acw.store.os.utime') as utime, \
                patch('acw.store.os.supports_fd', set()), \
                patch('acw.store.os.supports_follow_symlinks', set()):
            with self.assertRaisesRegex(PermissionError, 'reparse'):
                store._set_raw_mtime(target, handle, time.time())
            utime.assert_not_called()

    def test_append_rejects_existing_file_symlink_without_outside_write(self):
        store = self.new_store()
        outside, before = self.outside_file()
        self.symlink(store.raw_dir / 'dot.jsonl', outside)
        with self.assertRaises(PermissionError):
            store.append_raw('dot', {'content': 'must remain inside'})
        self.assertEqual(before, outside.read_bytes())

    def test_append_rejects_dangling_file_symlink_without_creating_target(self):
        store = self.new_store()
        outside = self.root / 'must-not-be-created.jsonl'
        self.symlink(store.raw_dir / 'dot.jsonl', outside)
        with self.assertRaises(PermissionError):
            store.append_raw('dot', {'content': 'must remain inside'})
        self.assertFalse(outside.exists())

    def test_append_revalidates_cached_segment(self):
        store = self.new_store()
        first = store.append_raw('dot', {'content': 'ordinary first record'})
        path = store.data_dir / first.rsplit(':', 1)[0]
        path.unlink()
        outside, before = self.outside_file()
        self.symlink(path, outside)
        with self.assertRaises(PermissionError):
            store.append_raw('dot', {'content': 'must remain inside'})
        with self.assertRaises(PermissionError):
            store.read_raw(first)
        self.assertEqual(before, outside.read_bytes())

    def test_append_rejects_linked_rotation_candidate(self):
        store = self.new_store()
        (store.raw_dir / 'dot.jsonl').write_text('{"safe":true}\n', encoding='utf-8')
        outside, before = self.outside_file()
        self.symlink(store.raw_dir / 'dot-100-deadbeef.jsonl', outside)
        with self.assertRaises(PermissionError):
            store.append_raw('dot', {'content': 'must remain inside'})
        self.assertEqual(before, outside.read_bytes())

    def test_startup_rejects_raw_and_artifact_directory_symlinks(self):
        for child in ('raw', 'artifacts'):
            with self.subTest(child=child):
                data = self.root / ('data-' + child)
                data.mkdir()
                outside = self.root / ('outside-' + child)
                outside.mkdir()
                self.symlink(data / child, outside, directory=True)
                with self.assertRaises(PermissionError):
                    Store(data)
                self.assertEqual([], list(outside.iterdir()))
                self.assertFalse((data / 'workspace.sqlite3').exists())

    def test_startup_rejects_linked_data_directory_and_ancestor(self):
        outside = self.root / 'outside-directory'
        outside.mkdir()
        linked = self.root / 'linked-directory'
        self.symlink(linked, outside, directory=True)
        for data in (linked, linked / 'new-data'):
            with self.subTest(data=data):
                with self.assertRaises(PermissionError):
                    Store(data)
        self.assertEqual([], list(outside.iterdir()))

    def test_raw_directory_is_revalidated_after_startup(self):
        store = self.new_store()
        first = store.append_raw('dot', {'content': 'ordinary record'})
        store.raw_dir.rename(store.data_dir / 'original-raw')
        outside = self.root / 'outside-directory'
        outside.mkdir()
        sentinel = outside / 'dot.jsonl'
        sentinel.write_bytes(b'{"outside":"synthetic sentinel"}\n')
        before = sentinel.read_bytes()
        self.symlink(store.raw_dir, outside, directory=True)
        for action in (lambda: store.append_raw('dot', {'content': 'must remain inside'}),
                       store.archive_logs, lambda: store.read_raw(first)):
            with self.subTest(action=action):
                with self.assertRaises(PermissionError):
                    action()
        self.assertEqual(before, sentinel.read_bytes())
        self.assertEqual(['dot.jsonl'], sorted(path.name for path in outside.iterdir()))

    def test_archive_rejects_linked_destination_before_truncation(self):
        store = self.new_store()
        source = store.raw_dir / 'dot-100.jsonl'
        original = b'{"content":"ordinary source"}\n'
        source.write_bytes(original)
        outside, before = self.outside_file('outside.jsonl.gz')
        self.symlink(source.with_suffix('.jsonl.gz'), outside)
        with self.assertRaises(PermissionError):
            store.archive_logs()
        self.assertEqual(before, outside.read_bytes())
        self.assertEqual(original, source.read_bytes())

    def test_archive_rejects_linked_source_before_retention(self):
        store = self.new_store()
        outside, before = self.outside_file()
        old = time.time() - 40 * 86400
        os.utime(outside, (old, old))
        link = store.raw_dir / 'dot-100.jsonl'
        self.symlink(link, outside)
        with self.assertRaises(PermissionError):
            store.archive_logs()
        self.assertTrue(link.is_symlink())
        self.assertEqual(before, outside.read_bytes())

    def test_archived_read_rejects_linked_file(self):
        store = self.new_store()
        outside, before = self.outside_file('outside.jsonl.gz')
        self.symlink(store.raw_dir / 'dot.jsonl.gz', outside)
        with self.assertRaises(PermissionError):
            store.read_raw('raw/dot.jsonl:0')
        self.assertEqual(before, outside.read_bytes())

    def test_startup_rejects_database_and_each_sqlite_sidecar_symlink(self):
        for index, suffix in enumerate(('', '-wal', '-shm', '-journal')):
            with self.subTest(suffix=suffix):
                outside = self.root / f'outside-{index}.sqlite3'
                with closing(sqlite3.connect(outside)) as db, db:
                    db.execute('CREATE TABLE sentinel (value TEXT)')
                    db.execute("INSERT INTO sentinel VALUES ('synthetic outside database')")
                before = outside.read_bytes()
                data = self.root / f'data-{index}'
                data.mkdir()
                self.symlink(data / ('workspace.sqlite3' + suffix), outside)
                with patch('acw.store.sqlite3.connect') as connect:
                    with self.assertRaises(PermissionError):
                        Store(data)
                    connect.assert_not_called()
                self.assertEqual(before, outside.read_bytes())
                with closing(sqlite3.connect(outside)) as db:
                    self.assertEqual([('sentinel',)], db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())

    def test_startup_rejects_non_regular_database_sidecar(self):
        data = self.root / 'data'
        data.mkdir()
        (data / 'workspace.sqlite3-wal').mkdir()
        with patch('acw.store.sqlite3.connect') as connect:
            with self.assertRaises(PermissionError):
                Store(data)
            connect.assert_not_called()

    def test_managed_files_reject_reparse_attribute_without_is_junction(self):
        store = self.new_store()
        chosen = store.raw_dir / 'dot.jsonl'
        chosen.write_text('{"safe":true}\n', encoding='utf-8')
        original_lstat = Path.lstat

        class ReparseMetadata:
            st_file_attributes = 0x400

            def __init__(self, metadata):
                self.metadata = metadata

            def __getattr__(self, name):
                return getattr(self.metadata, name)

        def lstat(path, *args, **kwargs):
            metadata = original_lstat(path, *args, **kwargs)
            return ReparseMetadata(metadata) if path == chosen else metadata

        with patch.object(Path, 'lstat', lstat):
            with self.assertRaises(PermissionError):
                store.append_raw('dot', {'content': 'must remain inside'})
        self.assertEqual('{"safe":true}\n', chosen.read_text(encoding='utf-8'))

    def test_append_rejects_non_regular_segment(self):
        store = self.new_store()
        (store.raw_dir / 'dot.jsonl').mkdir()
        with self.assertRaises(PermissionError):
            store.append_raw('dot', {'content': 'ordinary record'})

    def test_raw_and_archive_targets_reject_shared_hardlinks(self):
        for archive in (False, True):
            with self.subTest(archive=archive):
                store = self.new_store('archive-data' if archive else 'append-data')
                outside, before = self.outside_file('outside-archive' if archive else 'outside-append')
                if archive:
                    source = store.raw_dir / 'dot-100.jsonl'
                    source.write_text('{"safe":true}\n', encoding='utf-8')
                    os.link(outside, source.with_suffix('.jsonl.gz'))
                    action = store.archive_logs
                else:
                    os.link(outside, store.raw_dir / 'dot.jsonl')
                    action = lambda: store.append_raw('dot', {'content': 'must remain inside'})
                with self.assertRaises(PermissionError):
                    action()
                self.assertEqual(before, outside.read_bytes())

    def test_leaf_symlink_swap_during_open_never_writes_outside(self):
        store = self.new_store()
        chosen = store.raw_dir / 'dot.jsonl'
        outside, before = self.outside_file()
        original_open = os.open

        def swap_then_open(path, flags, *args, **kwargs):
            if Path(path) == chosen:
                self.symlink(chosen, outside)
            return original_open(path, flags, *args, **kwargs)

        with patch('acw.store.os.open', side_effect=swap_then_open):
            with self.assertRaises(PermissionError):
                store.append_raw('dot', {'content': 'must remain inside'})
        self.assertEqual(before, outside.read_bytes())

    def test_concurrent_append_keeps_complete_unique_records_and_offsets(self):
        store = self.new_store()
        store.max_raw_bytes = 1000
        start = threading.Barrier(8)

        def append(worker):
            start.wait(timeout=5)
            return [(worker, index, store.append_raw('dot', {'worker': worker, 'index': index, 'content': '中 🧪'}))
                    for index in range(50)]

        with ThreadPoolExecutor(max_workers=8) as pool:
            groups = list(pool.map(append, range(8)))
        records = [record for group in groups for record in group]
        self.assertEqual(400, len({ref for _, _, ref in records}))
        for worker, index, ref in records:
            self.assertEqual({'worker': worker, 'index': index, 'content': '中 🧪'}, store.read_raw(ref))

    def test_close_waits_for_locked_append_and_is_idempotent(self):
        store = self.new_store()
        opened = threading.Event()
        release = threading.Event()
        close_started = threading.Event()
        original_open = store._open_raw

        def paused_open(*args, **kwargs):
            opened.set()
            if not release.wait(timeout=5):
                raise RuntimeError('Test did not release append')
            return original_open(*args, **kwargs)

        def close():
            close_started.set()
            store.close()

        with patch.object(store, '_open_raw', side_effect=paused_open), ThreadPoolExecutor(max_workers=2) as pool:
            append_future = pool.submit(store.append_raw, 'dot', {'content': 'in-flight synthetic record'})
            try:
                self.assertTrue(opened.wait(timeout=5))
                close_future = pool.submit(close)
                self.assertTrue(close_started.wait(timeout=5))
                self.assertFalse(close_future.done())
            finally:
                release.set()
            reference = append_future.result(timeout=5)
            close_future.result(timeout=5)
        self.assertEqual('raw/dot.jsonl:0', reference)
        self.assertEqual({'content': 'in-flight synthetic record'}, json.loads((store.raw_dir / 'dot.jsonl').read_text(encoding='utf-8')))
        store.close()
        before = (store.raw_dir / 'dot.jsonl').read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'closed'):
            store.append_raw('dot', {'content': 'must not append after close'})
        self.assertEqual(before, (store.raw_dir / 'dot.jsonl').read_bytes())

    def test_closed_store_rejects_reads_writes_and_maintenance_before_mutation(self):
        store = self.new_store()
        store.close()
        actions = (lambda: store.append_raw('dot', {'safe': True}),
                   lambda: store.read_raw('raw/dot.jsonl:0'),
                   store.archive_logs,
                   lambda: store.query('SELECT * FROM settings'),
                   lambda: store.set_setting('ordinary', 'fixture'),
                   lambda: store.insert('settings', {'key': 'ordinary', 'value': 'fixture'}),
                   lambda: store.update('settings', {'key': 'ordinary'}, {'value': 'fixture'}))
        for action in actions:
            with self.subTest(action=action):
                with self.assertRaisesRegex(RuntimeError, 'closed'):
                    action()
        self.assertEqual([], list(store.raw_dir.iterdir()))


if __name__ == '__main__':
    unittest.main()
