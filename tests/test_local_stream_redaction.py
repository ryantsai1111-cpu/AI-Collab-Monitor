"""Offline arbitrary local-key redaction through native handlers and Core.

Only invented canaries are placed in a specifically named test environment
variable. No connection, CLI subprocess, native session, or network is used.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from acw.adapters.claude import ClaudeAdapter
from acw.adapters.codex import CodexAdapter
from acw.adapters.local import LocalClaudeAdapter, LocalCodexAdapter
from acw.core import WorkspaceCore


CANARY = 'K9NEVER_PERSIST_CANARY_VALUE'
CANARY_SUFFIX = 'PERSIST_CANARY_VALUE'
SAFE_PREFIX = 'Public answer: '
CLASSES = (LocalCodexAdapter, LocalClaudeAdapter)


class LocalStreamRedactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='acw-local-stream-redaction-')
        self.root = Path(self.temp.name)
        self.repo = self.root / 'isolated-repo'
        self.repo.mkdir()
        self.cores, self.transports = [], []
        self.guards = [patch('subprocess.Popen', side_effect=AssertionError('CLI forbidden')),
                       patch('subprocess.run', side_effect=AssertionError('Process forbidden')),
                       patch('socket.socket.connect', side_effect=AssertionError('Network forbidden')),
                       patch('urllib.request.urlopen', side_effect=AssertionError('HTTP forbidden'))]
        self.forbidden = [guard.start() for guard in self.guards]

    def tearDown(self):
        try:
            for core in self.cores:
                if not core._closed:
                    core.close()
            for transport in self.transports + self.forbidden:
                transport.assert_not_called()
            self.temp.cleanup()
        finally:
            for guard in reversed(self.guards):
                guard.stop()

    def adapter(self, cls, credentials=(CANARY,)):
        adapter = cls(lambda kind, **payload: None, base_url='http://127.0.0.1:1/v1',
                      model='offline-fixture', api_key_env='ACW_LOCAL_STREAM_TEST_KEY')
        with patch.dict(os.environ, {'ACW_LOCAL_STREAM_TEST_KEY': credentials[0]}):
            adapter._validate()  # Explicit test-only loading; no connect/startup.
        if len(credentials) > 1:
            adapter._credential_values = list(credentials)
        for method in ('_write', '_request'):
            transport = Mock(side_effect=AssertionError('Transport forbidden'))
            setattr(adapter, method, transport)
            self.transports.append(transport)
        return adapter

    def make_core(self, cls, name, credentials=(CANARY,)):
        adapter = self.adapter(cls, credentials)
        core = WorkspaceCore(self.root / name, {'local': adapter})
        self.cores.append(core)
        core.git_snapshot = lambda project_id=None: {'branch': 'offline', 'diff': '', 'status': '', 'log': ''}
        project = core.create_project('Local stream fixture', self.repo)
        core.select_project(project['id'], sync=False)
        core.create_task('Replay local handler without transport')
        adapter.session_id = 'offline-local-session'
        core.ingest_event('local', 'session', session_id=adapter.session_id)
        return core, adapter

    @staticmethod
    def start(adapter):
        if isinstance(adapter, LocalCodexAdapter):
            adapter._handle_message({'method': 'turn/started', 'params': {
                'threadId': adapter.session_id, 'turn': {'id': 'fixture-turn'}}})
            adapter._handle_message({'method': 'item/started', 'params': {
                'threadId': adapter.session_id, 'item': {'type': 'agentMessage', 'id': 'visible-message'}}})
        else:
            adapter.set_state('Busy')
            adapter._handle({'type': 'stream_event', 'event': {
                'type': 'message_start', 'message': {'id': 'visible-message'}}})

    @staticmethod
    def delta(adapter, text):
        if isinstance(adapter, LocalCodexAdapter):
            adapter._handle_message({'method': 'item/agentMessage/delta', 'params': {
                'threadId': adapter.session_id, 'itemId': 'visible-message', 'delta': text}})
        else:
            adapter._handle({'type': 'stream_event', 'event': {
                'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': text}}})

    @staticmethod
    def finish(adapter, text):
        if isinstance(adapter, LocalCodexAdapter):
            adapter._handle_message({'method': 'item/completed', 'params': {
                'threadId': adapter.session_id, 'item': {
                    'type': 'agentMessage', 'id': 'visible-message', 'text': text}}})
        else:
            adapter._handle({'type': 'stream_event', 'event': {'type': 'message_stop'}})

    def assert_safe(self, core, forbidden=(CANARY, CANARY_SUFFIX)):
        queued = core.drain_events(limit=100000)
        surfaces = [json.dumps(queued, ensure_ascii=False)]
        for table in sorted(core.store.TABLES):
            surfaces.append(json.dumps(core.store.query('SELECT * FROM ' + table), ensure_ascii=False))
        for surface in surfaces:
            for canary in forbidden:
                self.assertNotIn(canary, surface)
        for path in core.data_dir.rglob('*'):
            if path.is_file():
                content = path.read_bytes()
                for canary in forbidden:
                    self.assertNotIn(canary.encode(), content, str(path))
        for event in queued:
            if event['type'] == 'message_delta':
                self.assertNotIn('delta', event)
                self.assertEqual(event['content'], event['full_content'])
        return queued

    def test_character_by_character_key_is_masked_in_every_ui_event(self):
        for cls in CLASSES:
            with self.subTest(harness=cls.local_harness):
                core, adapter = self.make_core(cls, cls.local_harness + '-characters')
                self.start(adapter)
                self.delta(adapter, SAFE_PREFIX)
                core.drain_events(limit=100000)
                for char in CANARY:
                    self.delta(adapter, char)
                    queued = self.assert_safe(core)
                    visible = [event for event in queued if event['type'] == 'message_delta']
                    self.assertEqual(visible[-1]['full_content'], SAFE_PREFIX + '[REDACTED]')
                self.assertEqual(core._streams['local']['text'], SAFE_PREFIX + CANARY)
                self.delta(adapter, '\nPublic ending\n')
                self.finish(adapter, SAFE_PREFIX + CANARY + '\nPublic ending\n')
                self.assertEqual(core.messages(agent='local')[-1]['content'],
                                 SAFE_PREFIX + '[REDACTED]\nPublic ending\n')
                self.assert_safe(core)

    def test_every_split_safe_in_streaming_db_and_after_interrupted_restart(self):
        for cls in CLASSES:
            for split in range(1, len(CANARY)):
                with self.subTest(harness=cls.local_harness, split=split):
                    core, adapter = self.make_core(cls, '%s-split-%d' % (cls.local_harness, split))
                    self.start(adapter)
                    self.delta(adapter, SAFE_PREFIX + CANARY[:split])
                    self.assert_safe(core)
                    self.delta(adapter, CANARY[split:] + '\n')
                    self.assertEqual(core.messages(agent='local')[-1]['content'], SAFE_PREFIX + '[REDACTED]\n')
                    self.assert_safe(core)
                    core.close()
                    restored = WorkspaceCore(core.data_dir)
                    self.cores.append(restored)
                    message = restored.messages(agent='local')[-1]
                    self.assertEqual((message['content'], message['status']),
                                     (SAFE_PREFIX + '[REDACTED]\n', 'interrupted'))
                    self.assert_safe(restored)
                    restored.close()

    def test_newline_spanning_credential_prefix_never_enters_wal(self):
        credential = 'K9FIRST_SECRET_LINE\nSECOND_SECRET_LINE'
        for cls in CLASSES:
            with self.subTest(harness=cls.local_harness):
                core, adapter = self.make_core(cls, cls.local_harness + '-newline', (credential,))
                self.start(adapter)
                self.delta(adapter, SAFE_PREFIX)
                core.drain_events(limit=100000)
                for char in credential:
                    self.delta(adapter, char)
                    queued = self.assert_safe(core, ('K9FIRST_SECRET_LINE', 'SECOND_SECRET_LINE', credential))
                    self.assertEqual([e for e in queued if e['type'] == 'message_delta'][-1]['full_content'],
                                     SAFE_PREFIX + '[REDACTED]')
                self.delta(adapter, '\n')
                self.assertEqual(core.messages(agent='local')[-1]['content'], SAFE_PREFIX + '[REDACTED]\n')
                self.assert_safe(core, ('K9FIRST_SECRET_LINE', 'SECOND_SECRET_LINE', credential))
                core.close()
                restored = WorkspaceCore(core.data_dir)
                self.cores.append(restored)
                self.assertEqual(restored.messages(agent='local')[-1]['content'], SAFE_PREFIX + '[REDACTED]\n')
                self.assert_safe(restored, ('K9FIRST_SECRET_LINE', 'SECOND_SECRET_LINE', credential))

    def test_generic_credential_suffix_is_not_exposed_by_local_prefix_redaction(self):
        prefix, suffix = 'sk-proj-ABCDEFGH', 'SYNTHETIC_GENERIC_SUFFIX'
        for cls in CLASSES:
            with self.subTest(harness=cls.local_harness):
                core, adapter = self.make_core(cls, cls.local_harness + '-generic', (prefix,))
                self.start(adapter)
                self.delta(adapter, SAFE_PREFIX + prefix)
                self.assert_safe(core, (prefix, suffix))
                self.delta(adapter, suffix + '\n')
                self.assert_safe(core, (prefix, suffix))
                self.finish(adapter, SAFE_PREFIX + prefix + suffix + '\n')
                self.assertEqual(core.messages(agent='local')[-1]['content'], SAFE_PREFIX + '[REDACTED]\n')
                self.assert_safe(core, (prefix, suffix))

    def test_overlapping_and_repeated_values_are_redacted_without_marker_reprocessing(self):
        cases = [(['K9ABC', 'ABCXYZ'], 'K9ABCXYZ', '[REDACTED]'),
                 (['K9ABC', 'K9ABCDEFGHI'], 'K9ABCDEFGHI', '[REDACTED]'),
                 (['K9K9'], 'K9K9K9', '[REDACTED]'),
                 (['[REDACTED]suffix', '['], '[REDACTED]suffix', '[REDACTED]'),
                 (['K9credential', ''], 'K9credential', '[REDACTED]')]
        for cls in CLASSES:
            for credentials, value, expected in cases:
                with self.subTest(harness=cls.local_harness, credentials=credentials):
                    adapter = self.adapter(cls, credentials)
                    self.assertEqual(adapter.redact_visible_text('Before ' + value + ' after'),
                                     'Before ' + expected + ' after')
                    self.assertEqual(adapter._redact_local('Before ' + value + ' after'),
                                     'Before ' + expected + ' after')

    def test_partial_match_withholds_tail_without_hiding_unrelated_prose(self):
        for cls in CLASSES:
            with self.subTest(harness=cls.local_harness):
                adapter = self.adapter(cls)
                self.assertEqual(adapter.redact_visible_text('Public K9NEVER_'), 'Public [REDACTED]')
                self.assertEqual(adapter.redact_visible_text('Public K9NEVER_x'), 'Public K9NEVER_x')
                self.assertEqual(adapter.redact_visible_text('Public text\n'), 'Public text\n')
                # Terminal text is deliberately conservative if it ends in a
                # possible configured credential prefix.
                self.assertEqual(adapter.redact_visible_text('Public K'), 'Public [REDACTED]')
                with patch.object(os.environ, 'get', side_effect=AssertionError('No credential read')):
                    self.assertEqual(adapter.redact_visible_text(CANARY), '[REDACTED]')

    def test_metadata_raw_end_errors_and_history_keep_local_redaction(self):
        for cls in CLASSES:
            with self.subTest(harness=cls.local_harness):
                adapter = self.adapter(cls)
                events = []
                adapter.emit = lambda kind, **payload: events.append((kind, payload))
                emit = adapter._emit if cls is LocalCodexAdapter else adapter._event
                emit('message_delta', content=CANARY[:10], details={'ordinary_field': CANARY},
                     thinking='PRIVATE_LOCAL_THOUGHT')
                self.assertEqual(events[-1][1]['content'], CANARY[:10])
                self.assertEqual(events[-1][1]['details']['ordinary_field'], '[REDACTED]')
                self.assertNotIn('PRIVATE_LOCAL_THOUGHT', json.dumps(events))
                emit('raw', raw={'text': CANARY})
                emit('message_end', content=CANARY)
                adapter._error('Local backend echoed ' + CANARY)
                self.assertNotIn(CANARY, json.dumps(events))
                self.assertNotIn(CANARY, json.dumps(adapter.diagnostics()))
                parent = CodexAdapter if cls is LocalCodexAdapter else ClaudeAdapter
                history = [{'role': 'assistant', 'content': 'Public ' + CANARY}]
                with patch.object(parent, 'get_history', return_value=history):
                    self.assertEqual(adapter.get_history()[0]['content'], 'Public [REDACTED]')
                with patch.object(parent, 'get_native_history', return_value=history):
                    self.assertEqual(adapter.get_native_history('offline')[0]['content'], 'Public [REDACTED]')
                self.assertEqual(history[0]['content'], 'Public ' + CANARY)

    def test_empty_message_end_still_filters_accumulated_key(self):
        for cls in CLASSES:
            with self.subTest(harness=cls.local_harness):
                core, adapter = self.make_core(cls, cls.local_harness + '-empty-end')
                self.start(adapter)
                self.delta(adapter, SAFE_PREFIX + CANARY[:8])
                self.delta(adapter, CANARY[8:])
                emit = adapter._emit if cls is LocalCodexAdapter else adapter._event
                emit('message_end', content='')
                message = core.messages(agent='local')[-1]
                self.assertEqual((message['content'], message['status']),
                                 (SAFE_PREFIX + '[REDACTED]', 'complete'))
                self.assert_safe(core)

    def test_replaced_local_claude_missing_start_cannot_reuse_old_raw_key(self):
        old_key, new_key = 'K9OLD_CONFIGURED_CANARY', 'K9NEW_CONFIGURED_CANARY'
        core, old_adapter = self.make_core(LocalClaudeAdapter, 'claude-replacement', (old_key,))
        self.start(old_adapter)
        self.delta(old_adapter, 'Safe retained line\n' + old_key)
        self.assertEqual(core._streams['local']['text'], 'Safe retained line\n' + old_key)
        self.assert_safe(core, (old_key, new_key))
        replacement = self.adapter(LocalClaudeAdapter, (new_key,))
        replacement.session_id = old_adapter.session_id
        core.set_adapter('local', replacement)
        self.assertNotIn('local', core._streams)
        old_message = core.messages(agent='local')[-1]
        self.assertEqual((old_message['content'], old_message['status']),
                         ('Safe retained line\n', 'interrupted'))
        # Replay a new-generation native text delta with a missing start event.
        # It must create a fresh Core stream under the new credential redactor.
        self.delta(replacement, SAFE_PREFIX + new_key + '\n')
        self.assertEqual(core._streams['local']['text'], SAFE_PREFIX + new_key + '\n')
        self.assert_safe(core, (old_key, new_key))
        self.finish(replacement, SAFE_PREFIX + new_key + '\n')
        self.assert_safe(core, (old_key, new_key))
        rows = core.messages(agent='local')
        self.assertEqual(len(rows), 2)
        self.assertEqual((rows[0]['content'], rows[0]['status']), ('Safe retained line\n', 'interrupted'))
        self.assertEqual((rows[1]['content'], rows[1]['status']), (SAFE_PREFIX + '[REDACTED]\n', 'complete'))
        core.close()
        restored = WorkspaceCore(core.data_dir)
        self.cores.append(restored)
        self.assert_safe(restored, (old_key, new_key))
        self.assertEqual(len(restored.messages(agent='local')), 2)


if __name__ == '__main__':
    unittest.main()
