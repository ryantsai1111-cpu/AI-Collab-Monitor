"""Mocked official child processes; no credentials, HOME writes or network."""
import json
import io
import os
from pathlib import Path
import tempfile
import tomllib
import unittest
from urllib.error import HTTPError, URLError
from unittest.mock import MagicMock, patch

from acw.adapters.claude import ClaudeAdapter
from acw.adapters.codex import CodexAdapter
from acw.adapters.hermes import HermesAdapter
from acw.adapters.local import LocalCodexAdapter, LocalClaudeAdapter, make_local_adapter, _official_executable


class LocalAdapterTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.emit = lambda kind, **data: self.events.append((kind, data))
        self.process = MagicMock()
        self.process.poll.return_value = None
        self.process.stdin.closed = False
        self.process.stdin.close.side_effect = lambda: setattr(self.process.stdin, 'closed', True)
        self.http_response = MagicMock()
        self.http_response.status = 200
        self.http_response.read.return_value = b'{"data":[{"id":"fixture-local"}]}'
        self.http_client = MagicMock()
        self.http_client.open.return_value.__enter__.return_value = self.http_response
        self.guards = [patch('subprocess.Popen', return_value=self.process),
                       patch('threading.Thread'), patch('subprocess.run', return_value=MagicMock(stdout='fixture-version')),
                       patch('socket.socket.connect', side_effect=AssertionError('Network forbidden')),
                       patch('urllib.request.urlopen', side_effect=AssertionError('HTTP forbidden')),
                       patch('acw.adapters.local.build_opener', return_value=self.http_client)]
        self.popen, self.thread, self.run, _, _, self.opener = [guard.start() for guard in self.guards]
        self.addCleanup(lambda: [guard.stop() for guard in reversed(self.guards)])

    def adapter(self, cls, **settings):
        return cls(self.emit, executable='official.exe', base_url='http://localhost:1234/v1',
                   model='fixture-local', **settings)

    def connect(self, adapter, directory=None):
        with tempfile.TemporaryDirectory() as temporary:
            adapter.set_project(directory or temporary)
            with patch.object(adapter, '_request', return_value={'models': []}), \
                 patch('builtins.open', side_effect=AssertionError('Unexpected file open')), \
                 patch.object(Path, 'open', side_effect=AssertionError('Unexpected Path.open')), \
                 patch.object(Path, 'write_text', side_effect=AssertionError('Unexpected HOME write')):
                adapter.connect()

    def test_codex_popen_base_argv_and_toml_provider_overrides(self):
        adapter = self.adapter(LocalCodexAdapter)
        self.connect(adapter)
        argv = self.popen.call_args.args[0]
        self.assertEqual(['official.exe', 'app-server', '--listen', 'stdio://'], argv[:4])
        self.assertTrue(all(flag == '-c' for flag in argv[4::2]))
        config = tomllib.loads('\n'.join(argv[5::2]))
        self.assertEqual('acw_local', config['model_provider'])
        self.assertEqual('fixture-local', config['model'])
        provider = config['model_providers']['acw_local']
        self.assertEqual('Local LLM', provider['name'])
        self.assertEqual('http://localhost:1234/v1', provider['base_url'])
        self.assertEqual('responses', provider['wire_api'])
        self.assertFalse(provider['requires_openai_auth'])
        self.assertEqual('Connected', adapter.state)

    def test_claude_child_environment_and_model_do_not_mutate_parent(self):
        with patch.dict(os.environ, {'LOCAL_FIXTURE_KEY': 'not-a-real-key',
                                    'ANTHROPIC_BASE_URL': 'https://official-fixture.invalid',
                                    'ANTHROPIC_API_KEY': 'parent-fixture-key', 'CLAUDE_CODE_USE_BEDROCK': '1'}):
            before = dict(os.environ)
            adapter = self.adapter(LocalClaudeAdapter, api_key_env='LOCAL_FIXTURE_KEY')
            self.connect(adapter)
            env = self.popen.call_args.kwargs['env']
            self.assertEqual('http://localhost:1234/v1', env['ANTHROPIC_BASE_URL'])
            self.assertEqual('not-a-real-key', env['ANTHROPIC_AUTH_TOKEN'])
            self.assertNotIn('ANTHROPIC_API_KEY', env)
            self.assertNotIn('CLAUDE_CODE_USE_BEDROCK', env)
            self.assertIn('--model=fixture-local', self.popen.call_args.args[0])
            self.assertEqual(before, dict(os.environ))

    def test_claude_without_api_key_never_falls_back_to_parent_login(self):
        # An empty token makes Claude Code send its stored Anthropic login to the endpoint.
        with patch.dict(os.environ, {'CLAUDE_CODE_OAUTH_TOKEN': 'parent-fixture-login',
                                    'ANTHROPIC_AUTH_TOKEN': 'parent-fixture-token',
                                    'CLAUDE_CODE_SDK_HAS_HOST_AUTH_REFRESH': '1',
                                    'CLAUDE_CONFIG_DIR': 'fixture-config-dir'}):
            adapter = self.adapter(LocalClaudeAdapter)
            self.connect(adapter)
            env = self.popen.call_args.kwargs['env']
            self.assertEqual('local', env['ANTHROPIC_AUTH_TOKEN'])
            self.assertEqual('http://localhost:1234/v1', env['ANTHROPIC_BASE_URL'])
            self.assertEqual('fixture-config-dir', env['CLAUDE_CONFIG_DIR'])
            leaked = [name for name in env if name.upper().startswith(('ANTHROPIC_', 'CLAUDE'))
                      and name not in ('ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_BASE_URL', 'CLAUDE_CONFIG_DIR',
                                       'CLAUDE_CODE_MAX_OUTPUT_TOKENS', 'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC')]
            self.assertEqual([], leaked)
            # Claude Code otherwise asks for 128k output tokens, which a small local context rejects.
            self.assertEqual('8192', env['CLAUDE_CODE_MAX_OUTPUT_TOKENS'])
            self.assertEqual('1', env['CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC'])
            capped = self.adapter(LocalClaudeAdapter, max_output_tokens=4000, context_tokens=65536)
            self.assertEqual('4000', capped._process_env()['CLAUDE_CODE_MAX_OUTPUT_TOKENS'])
            self.assertEqual('65536', capped._process_env()['CLAUDE_CODE_MAX_CONTEXT_TOKENS'])
            self.assertNotIn('CLAUDE_CODE_MAX_CONTEXT_TOKENS', env)
            self.assertNotIn('parent-fixture', json.dumps(env))

    def test_missing_endpoint_or_model_is_offline_without_any_process(self):
        for cls in (LocalCodexAdapter, LocalClaudeAdapter):
            for settings in ({}, {'model': 'fixture'}, {'base_url': 'http://localhost:1234'}):
                with self.subTest(cls=cls, settings=settings):
                    adapter = cls(self.emit, executable='official.exe', **settings)
                    adapter.connect()
                    self.assertEqual('Offline', adapter.state)
                    self.assertEqual('請先在設定填入本地端點與模型名稱', adapter.last_error)
        self.popen.assert_not_called()
        self.run.assert_not_called()

    def test_explicit_endpoint_probe_uses_metadata_get_without_launching(self):
        adapter = self.adapter(LocalClaudeAdapter)
        result = adapter.check_endpoint()
        request = self.http_client.open.call_args.args[0]
        self.assertEqual('GET', request.get_method())
        self.assertEqual('http://localhost:1234/v1/models', request.full_url)
        self.assertEqual(['fixture-local'], result['models'])
        self.assertIn('尚未驗證', result['detail'])
        self.assertEqual(result, adapter.diagnostics()['endpoint_check'])
        self.assertEqual('Disconnected', adapter.state)
        self.popen.assert_not_called()
        self.run.assert_not_called()

    def test_endpoint_http_and_network_failures_stop_before_harness_launch(self):
        for error, message in ((HTTPError('http://fixture', 502, '', {}, None), 'HTTP 502'),
                               (HTTPError('http://fixture', 401, '', {}, None), 'API key'),
                               (URLError('private server detail'), '網路連線')):
            with self.subTest(message=message):
                self.http_client.open.side_effect = error
                adapter = self.adapter(LocalClaudeAdapter)
                with self.assertRaisesRegex(ConnectionError, message):
                    adapter.connect()
                self.assertEqual('Offline', adapter.state)
                self.assertNotIn('private server detail', str(self.events))
        self.popen.assert_not_called()
        self.run.assert_not_called()

    def test_models_optional_but_invalid_catalog_or_model_mismatch_is_clear(self):
        adapter = self.adapter(LocalClaudeAdapter)
        for status in (404, 405):
            self.http_client.open.side_effect = HTTPError('http://fixture', status, '', {}, None)
            self.assertEqual(status, adapter.check_endpoint()['http_status'])
        self.http_client.open.side_effect = None
        for body, message in ((b'<html>wrong port</html>', 'JSON'),
                              (b'{}', '格式不符'),
                              (b'x' * 65537, '大小限制'),
                              (b'{"data":[{"id":"actual-model"}]}', 'actual-model')):
            self.http_response.read.return_value = body
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                adapter.check_endpoint()

    def test_strata_host_rejection_has_specific_hint_without_echoing_response(self):
        body = json.dumps({'error': {'type': 'forbidden',
                          'message': 'Host rejected (DNS rebinding protection) private-response-canary'}}).encode()
        self.http_client.open.side_effect = HTTPError('http://fixture', 403, '', {}, io.BytesIO(body))
        adapter = self.adapter(LocalClaudeAdapter)
        with self.assertRaisesRegex(ConnectionError, 'STRATA_ALLOWED_HOSTS') as caught:
            adapter.connect()
        self.assertNotIn('private-response-canary', str(caught.exception))
        self.assertNotIn('private-response-canary', json.dumps(self.events))
        self.assertEqual('Offline', adapter.state)
        self.popen.assert_not_called()

    def test_other_forbidden_responses_keep_auth_hint(self):
        for body in (b'not-json', b'[]', b'{"error":"forbidden"}', b'{"error":{"type":"authentication"}}'):
            with self.subTest(body=body):
                self.http_client.open.side_effect = HTTPError('http://fixture', 403, '', {}, io.BytesIO(body))
                with self.assertRaisesRegex(ConnectionError, 'API key'):
                    self.adapter(LocalClaudeAdapter).check_endpoint()

    def test_probe_does_not_follow_redirects_or_echo_credentials(self):
        with patch.dict(os.environ, {'LOCAL_FIXTURE_KEY': 'private-probe-canary'}):
            adapter = self.adapter(LocalClaudeAdapter, api_key_env='LOCAL_FIXTURE_KEY')
            adapter.check_endpoint()
            handler = self.opener.call_args.args[0]
            request = self.http_client.open.call_args.args[0]
            self.assertEqual('Bearer private-probe-canary', request.get_header('Authorization'))
            self.assertIsNone(handler.redirect_request(request, None, 302, '', {}, 'http://elsewhere'))
            self.assertNotIn('private-probe-canary', json.dumps(adapter.diagnostics()))
            self.http_client.open.side_effect = HTTPError('http://fixture', 302, 'private-probe-canary', {}, None)
            with self.assertRaisesRegex(ConnectionError, '重新導向') as caught:
                adapter.check_endpoint()
            self.assertNotIn('private-probe-canary', str(caught.exception))

    def test_missing_native_session_error_keeps_history_and_requests_explicit_new_chat(self):
        adapter = self.adapter(LocalClaudeAdapter)
        adapter._error('No conversation found with session ID: fixture-id')
        self.assertIn('Workspace 歷史仍保留', adapter.last_error)
        self.assertIn('按「新增」', adapter.last_error)
        self.assertEqual('', adapter.session_id)
        self.popen.assert_not_called()

    def test_invalid_schemes_and_malformed_urls_never_launch(self):
        for cls in (LocalCodexAdapter, LocalClaudeAdapter):
            for url in ('file:///x', 'ftp://x', 'http://', 'https://localhost:bad',
                        'http://user:password@localhost', 'http://localhost?api_key=x'):
                with self.subTest(cls=cls, url=url):
                    adapter = cls(self.emit, executable='official.exe', base_url=url, model='fixture')
                    with self.assertRaisesRegex(ValueError, 'http://.*https://'):
                        adapter.connect()
                    self.assertEqual('Offline', adapter.state)
        self.popen.assert_not_called()
        self.run.assert_not_called()

    def test_missing_key_environment_never_launches(self):
        with patch.dict(os.environ, {}, clear=True):
            for cls in (LocalCodexAdapter, LocalClaudeAdapter):
                adapter = self.adapter(cls, api_key_env='LOCAL_MISSING_KEY')
                with self.assertRaisesRegex(ValueError, '找不到 API key 環境變數'):
                    adapter.connect()
                self.assertEqual('Offline', adapter.state)
        self.popen.assert_not_called()

    def test_key_not_in_argv_diagnostics_events_or_errors(self):
        for cls in (LocalCodexAdapter, LocalClaudeAdapter):
            with self.subTest(cls=cls), patch.dict(os.environ, {'LOCAL_FIXTURE_KEY': 'private-canary-value'}):
                adapter = self.adapter(cls, api_key_env='LOCAL_FIXTURE_KEY')
                self.connect(adapter)
                argv = self.popen.call_args.args[0]
                self.assertNotIn('private-canary-value', json.dumps(argv))
                if cls == LocalCodexAdapter:
                    self.assertIn('model_providers.acw_local.env_key="LOCAL_FIXTURE_KEY"', argv)
                    adapter._stderr_tail = ['private-canary-value']
                else:
                    adapter._last_stderr = 'private-canary-value'
                adapter._error('Backend echoed private-canary-value')
                self.assertNotIn('private-canary-value', json.dumps(adapter.diagnostics()))
                self.assertNotIn('private-canary-value', json.dumps(self.events))

    def test_construction_does_not_read_credentials_or_launch(self):
        with patch.object(os.environ, 'get', side_effect=AssertionError('Credential read at startup')):
            for cls in (LocalCodexAdapter, LocalClaudeAdapter):
                adapter = self.adapter(cls, api_key_env='LOCAL_FIXTURE_KEY')
                adapter.diagnostics()
        self.popen.assert_not_called()
        self.run.assert_not_called()

    def test_no_home_files_are_written_on_either_connect(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {'HOME': temporary, 'USERPROFILE': temporary}):
            before = list(Path(temporary).rglob('*'))
            for cls in (LocalCodexAdapter, LocalClaudeAdapter):
                self.connect(self.adapter(cls), directory=temporary)
            self.assertEqual(before, list(Path(temporary).rglob('*')))

    def test_configured_codex_model_can_be_sent_without_official_catalog(self):
        adapter = self.adapter(LocalCodexAdapter)
        self.connect(adapter)
        adapter.session_id = 'fixture-thread'
        adapter._session_ready = True
        adapter._permission_state = {'sandbox': {'type': 'workspaceWrite'}}
        with patch.object(adapter, '_request', return_value={'turn': {'id': 'fixture-turn'}}) as request:
            self.assertEqual('fixture-turn', adapter.send_message('hello', model='fixture-local'))
        self.assertEqual('fixture-local', request.call_args.args[1]['model'])
        self.assertEqual(['fixture-local'], adapter.list_models())
        self.assertFalse(adapter.attachment_capability('fixture-local')['supported'])

    def test_claude_handshake_catalog_does_not_replace_local_model(self):
        adapter = self.adapter(LocalClaudeAdapter)
        adapter._discover({'models': [{'id': 'official-model'}]})
        self.assertEqual(['fixture-local'], [item['id'] for item in adapter.list_models()])
        self.assertFalse(adapter.capabilities.supports_effort)

    def test_backend_exception_echo_is_redacted_before_propagation(self):
        for cls in (LocalCodexAdapter, LocalClaudeAdapter):
            with self.subTest(cls=cls), tempfile.TemporaryDirectory() as temporary, \
                 patch.dict(os.environ, {'LOCAL_FIXTURE_KEY': 'private-exception-canary'}):
                adapter = self.adapter(cls, api_key_env='LOCAL_FIXTURE_KEY')
                adapter.set_project(temporary)
                with patch.object(adapter, '_request', side_effect=RuntimeError('private-exception-canary')):
                    with self.assertRaises(RuntimeError) as caught:
                        adapter.connect()
                self.assertNotIn('private-exception-canary', str(caught.exception))
                self.assertNotIn('private-exception-canary', json.dumps(self.events))

    @unittest.skipUnless(os.name == 'nt', 'Windows npm native executable resolution')
    def test_windows_npm_wrapper_resolves_installed_official_binary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            native = root / 'node_modules/@openai/codex/node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe'
            native.parent.mkdir(parents=True)
            native.write_bytes(b'fixture, never executed')
            with patch('acw.adapters.local.shutil.which', return_value=str(root / 'codex.cmd')), \
                 patch('acw.adapters.local.platform.machine', return_value='AMD64'):
                self.assertEqual(str(native), _official_executable('codex'))

    def test_factory_selects_hermes_and_ignores_legacy_harness_executables(self):
        adapter = make_local_adapter(self.emit, codex_executable='codex.exe', claude_executable='claude.exe')
        self.assertIsInstance(adapter, HermesAdapter)
        self.assertEqual('', adapter.executable)
        adapter = make_local_adapter(self.emit, harness='claude', claude_executable='claude.exe')
        self.assertIsInstance(adapter, HermesAdapter)
        self.assertEqual('', adapter.executable)
        adapter = make_local_adapter(self.emit, harness='hermes', executable='custom-hermes.exe')
        self.assertIsInstance(adapter, HermesAdapter)
        self.assertEqual('custom-hermes.exe', adapter.executable)
        self.popen.assert_not_called()
        self.run.assert_not_called()

    def test_official_adapters_preserve_argv_and_omit_env_keyword(self):
        codex = CodexAdapter(self.emit, executable='official.exe')
        with patch.object(codex, '_request', return_value={'data': []}):
            codex.connect()
        self.assertEqual(['official.exe', 'app-server', '--listen', 'stdio://'], self.popen.call_args.args[0])
        self.assertNotIn('env', self.popen.call_args.kwargs)
        claude = ClaudeAdapter(self.emit, executable='official.exe')
        with tempfile.TemporaryDirectory() as temporary:
            claude.set_project(temporary)
            expected = ['official.exe', '--print', '--input-format', 'stream-json', '--output-format',
                        'stream-json', '--include-partial-messages', '--verbose', '--permission-prompt-tool', 'stdio']
            with patch.object(claude, '_request', return_value={}):
                claude.connect()
        self.assertEqual(expected, self.popen.call_args.args[0])
        self.assertNotIn('env', self.popen.call_args.kwargs)
        self.assertNotIn('env', self.run.call_args.kwargs)


if __name__ == '__main__':
    unittest.main()
