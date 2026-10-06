"""Session-only local providers using the existing official CLI harnesses."""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import re
import shutil
from urllib.parse import urlsplit

from .claude import ClaudeAdapter
from .codex import CodexAdapter


CONFIGURATION_REQUIRED = '請先在設定填入本地端點與模型名稱'


class _LocalSettings:
    """Validate only on explicit connection; never read credentials at startup."""
    agent = 'local'

    def __init__(self, emit, executable='', **settings):
        super().__init__(emit, executable, **settings)
        self._credential_values = []
        self._configured_models()
        self.capabilities.detail = CONFIGURATION_REQUIRED if not self.configured else self._provider_detail()

    @property
    def configured(self):
        return bool(str(self.settings.get('base_url') or '').strip() and self.model_name)

    @property
    def model_name(self):
        return str(self.settings.get('model') or '').strip()

    def _provider_detail(self):
        protocol = 'Responses API' if self.local_harness == 'codex' else 'Anthropic Messages API'
        return f'Local LLM · {protocol} · 模型清單來自設定；變更設定後請重新連線'

    def _configured_models(self):
        model = self.model_name
        self.capabilities.models = ([model] if self.local_harness == 'codex' else [{'id': model, 'name': model}]) if model else []
        self.capabilities.supports_model_selection = bool(model)
        self.capabilities.efforts = []
        self.capabilities.supports_effort = False

    def _redact_local(self, value):
        if isinstance(value, str):
            for credential in self._credential_values:
                value = value.replace(credential, '[REDACTED]')
            return value
        if isinstance(value, dict):
            return {self._redact_local(k): self._redact_local(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._redact_local(item) for item in value]
        return value

    def _emit(self, kind, **payload):
        return super()._emit(kind, **self._redact_local(payload))

    def _event(self, kind, **payload):
        return super()._event(kind, **self._redact_local(payload))

    def _error(self, error):
        return super()._error(self._redact_local(str(error)))

    def _request(self, *args, **kwargs):
        try:
            return super()._request(*args, **kwargs)
        except Exception as exc:
            safe = self._redact_local(str(exc))
            if safe != str(exc):
                raise RuntimeError(safe) from None
            raise

    def _validate(self):
        base_url = str(self.settings.get('base_url') or '').strip()
        try:
            parsed = urlsplit(base_url)
            valid = (parsed.scheme in ('http', 'https') and bool(parsed.hostname)
                     and parsed.username is None and parsed.password is None
                     and not parsed.query and not parsed.fragment and parsed.port != 0
                     and not any(c.isspace() or ord(c) < 32 for c in base_url))
        except ValueError:
            valid = False
        if not valid:
            raise ValueError('本地端點必須是有效的 http:// 或 https:// URL；認證請使用 API key 環境變數')
        env_name = str(self.settings.get('api_key_env') or '').strip()
        if env_name and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', env_name):
            raise ValueError('API key 環境變數名稱格式不正確')
        # Read only the explicitly named variable, and only after Connect.
        credential = os.environ.get(env_name) if env_name else None
        if env_name and not credential:
            raise ValueError('找不到 API key 環境變數，或其值為空')
        self._credential_values = [credential] if credential else []
        return base_url.rstrip('/'), env_name, credential

    def connect(self):
        if self.state in ('Connected', 'Busy'):
            return self.capabilities
        if not self.configured:
            self.last_error = CONFIGURATION_REQUIRED
            self.capabilities.detail = CONFIGURATION_REQUIRED
            self.set_state('Offline')
            return self.capabilities
        try:
            self._validate()
        except ValueError as exc:
            self._error(exc)
            self.set_state('Offline')
            raise
        if self.local_harness == 'claude':
            self._model = self.model_name
        try:
            result = super().connect()
        except Exception as exc:
            safe = self._redact_local(str(exc))
            if safe != str(exc):
                raise RuntimeError(safe) from None
            raise
        self.capabilities.detail = self._provider_detail()
        return result

    def diagnostics(self):
        result = self._redact_local(super().diagnostics())
        result.update(harness=self.local_harness, models_source='Local model setting')
        return result


class LocalCodexAdapter(_LocalSettings, CodexAdapter):
    agent = 'local'
    local_harness = 'codex'

    def _extra_args(self):
        base_url, env_name, _ = self._validate()
        provider = 'acw_local'
        values = {
            'model_provider': provider,
            f'model_providers.{provider}.name': 'Local LLM',
            f'model_providers.{provider}.base_url': base_url,
            f'model_providers.{provider}.wire_api': 'responses',
            f'model_providers.{provider}.requires_openai_auth': False,
            'model': self.model_name,
        }
        if env_name:
            values[f'model_providers.{provider}.env_key'] = env_name
        # JSON strings/booleans are valid TOML literals; values never become shell text.
        return [part for key, value in values.items()
                for part in ('-c', key + '=' + json.dumps(value, ensure_ascii=False))]

    def _process_env(self):
        _, env_name, credential = self._validate()
        child_env = os.environ.copy()
        if env_name:
            child_env[env_name] = credential
        return child_env

    def _discover_models(self):
        # Official model/list is not authoritative for custom providers.
        self._configured_models()
        self._model_records = [{'id': self.model_name, 'model': self.model_name,
                                'isDefault': True, 'inputModalities': ['text']}]
        self.capabilities.supports_files = False


class LocalClaudeAdapter(_LocalSettings, ClaudeAdapter):
    agent = 'local'
    local_harness = 'claude'

    def _process_env(self):
        base_url, _, credential = self._validate()
        child_env = os.environ.copy()
        # Explicitly route this child through Messages, independent of official panes.
        for key in ('ANTHROPIC_API_KEY', 'CLAUDE_CODE_USE_BEDROCK',
                    'CLAUDE_CODE_USE_VERTEX', 'CLAUDE_CODE_USE_FOUNDRY'):
            child_env.pop(key, None)
        child_env['ANTHROPIC_BASE_URL'] = base_url
        child_env['ANTHROPIC_AUTH_TOKEN'] = credential or ''
        return child_env

    def _discover(self, handshake):
        super()._discover(handshake)
        self._configured_models()
        self._model_info = []
        self.capabilities.detail = self._provider_detail()
        self._event('capabilities', capabilities=self.capabilities.to_dict())


def _official_executable(harness):
    executable = shutil.which(harness) or ''
    if os.name == 'nt' and harness == 'codex' and Path(executable).suffix.lower() in ('.cmd', '.bat', '.ps1'):
        # npm's Windows entry is a shell wrapper; use its installed native binary.
        arch = 'arm64' if platform.machine().lower() in ('arm64', 'aarch64') else 'x64'
        target = 'aarch64' if arch == 'arm64' else 'x86_64'
        package = Path(executable).parent / 'node_modules' / '@openai'
        relative = Path('vendor') / (target + '-pc-windows-msvc') / 'bin' / 'codex.exe'
        for root in (package / ('codex-win32-' + arch),
                     package / 'codex' / 'node_modules' / '@openai' / ('codex-win32-' + arch),
                     package / 'codex'):
            if (root / relative).is_file():
                return str(root / relative)
        return ''
    return executable


def make_local_adapter(emit, **settings):
    settings = dict(settings)
    harness = settings.get('harness', 'codex')
    if harness not in ('codex', 'claude'):
        raise ValueError('本地模型 Harness 必須是 Codex 或 Claude Code')
    executable = settings.pop('executable', '') or settings.get(harness + '_executable') or _official_executable(harness)
    cls = LocalCodexAdapter if harness == 'codex' else LocalClaudeAdapter
    return cls(emit, executable=executable, **settings)
