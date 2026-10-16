"""Standalone stdlib client exit codes and atomic request shape, using a fake dispatcher."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import dispatch_request as client
from acw.requests import REFUSAL_CODES


class DispatchClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root / 'requests'
        self.directory.mkdir()
        self.heartbeat = self.directory / '.dispatcher.json'
        self.heartbeat.write_text(json.dumps({'pid': os.getpid()}), encoding='utf-8')
        self.args = ['--agent', 'codex', '--worktree', str(self.root), '--label', 'fixture',
                     '--spec', 'spec.md', '--data-dir', str(self.root), '--monitor-root', str(self.root)]

    def test_complete_error_and_refusal_exit_codes_and_request_fields(self):
        self.assertEqual(REFUSAL_CODES, client.REFUSAL_CODES)
        for status, reason, expected in [('complete', '', 0), ('error', 'fixture', 1), ('rejected', 'no-spec: missing', 3)]:
            def respond(_):
                request = json.loads((self.directory / 'fixture.json').read_text(encoding='utf-8'))
                self.assertEqual('codex', request['agent'])
                self.assertEqual('spec.md', request['spec'])
                self.assertIn('不要 push main', request['prompt'])
                result = dict(label='fixture', status=status, reason=reason, exit_code=int(status != 'complete'))
                (self.directory / 'fixture.result.json').write_text(json.dumps(result), encoding='utf-8')
            output = io.StringIO()
            with self.subTest(status=status), patch.object(client, 'pid_alive', return_value=True), \
                    patch.object(client.time, 'sleep', side_effect=respond), contextlib.redirect_stdout(output):
                self.assertEqual(expected, client.main(self.args))
            self.assertIn('codex_exit=', output.getvalue())
            self.assertFalse((self.directory / 'fixture.json').exists())
            self.assertFalse(list(self.directory.glob('*.tmp')))
        timeline = (self.root / 'logs/timeline.log').read_text(encoding='utf-8')
        self.assertEqual(3, timeline.count('| CODEX | RUN_STARTED | mode=workspace'))
        self.assertEqual(3, timeline.count('| CODEX | RUN_ENDED |'))

    def test_missing_stale_or_dead_dispatcher_exits_four_without_request(self):
        output = io.StringIO()
        with patch.object(client, 'pid_alive', return_value=False), contextlib.redirect_stdout(output):
            self.assertEqual(4, client.main(self.args))
        self.assertIn('workspace: dispatcher not responding', output.getvalue())
        os.utime(self.heartbeat, (1, 1))
        with patch.object(client, 'pid_alive', return_value=True), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(4, client.main(self.args))
        self.assertFalse((self.directory / 'fixture.json').exists())

    def test_lost_heartbeat_withdraws_request_without_direct_fallback(self):
        def lose(_):
            os.utime(self.heartbeat, (1, 1))
        with patch.object(client, 'pid_alive', return_value=True), patch.object(client.time, 'sleep', side_effect=lose), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(1, client.main(self.args))
        self.assertFalse((self.directory / 'fixture.json').exists())
        self.assertIn('dispatcher-lost', (self.root / 'logs/timeline.log').read_text(encoding='utf-8'))

    def test_local_default_prompt_and_interruption_cleanup(self):
        args = self.args.copy()
        args[1] = 'local'
        args[args.index('--spec')] = '--briefs'
        args[args.index('spec.md')] = 'docs/briefs/t'
        def interrupt(_):
            request = json.loads((self.directory / 'fixture.json').read_text(encoding='utf-8'))
            self.assertEqual(client.LOCAL_PROMPT.format(worktree=self.root, briefs='docs/briefs/t'), request['prompt'])
            raise KeyboardInterrupt
        with patch.object(client, 'pid_alive', return_value=True), patch.object(client.time, 'sleep', side_effect=interrupt):
            self.assertEqual(1, client.main(args))
        self.assertFalse((self.directory / 'fixture.json').exists())
