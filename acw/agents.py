"""Provider definitions and persisted, independent workspace agent identities."""
from __future__ import annotations

import re
from copy import deepcopy

PROVIDERS = ('claude', 'dot', 'codex', 'local')
NAMES = {'claude': 'Claude', 'dot': 'G8毛', 'codex': 'Codex', 'local': 'Hermes'}
INSTANCE_ID = re.compile(r'agent-[0-9a-f]{32}')


def load_instances(value):
    """Validate persisted identities before using them as routing keys."""
    result = {key: {'id': key, 'provider': key, 'name': NAMES[key]} for key in PROVIDERS}
    if value is None:
        return result
    if not isinstance(value, list):
        raise ValueError('Agent registry must be a list')
    for row in value:
        if (not isinstance(row, dict) or not INSTANCE_ID.fullmatch(str(row.get('id', '')))
                or row.get('provider') not in ('claude', 'codex', 'local')
                or not isinstance(row.get('name'), str) or not row['name'].strip()
                or len(row['name']) > 80 or any(ord(c) < 32 for c in row['name'])):
            raise ValueError('Invalid saved agent instance')
        if row['id'] in result:
            raise ValueError('Duplicate agent instance')
        result[row['id']] = {key: row[key] for key in ('id', 'provider', 'name')}
    return result


def make_adapter(provider, emit, settings):
    """Construct a disconnected adapter; never share runtime objects."""
    from .adapters.claude import ClaudeAdapter
    from .adapters.codex import CodexAdapter
    from .adapters.dot import DotAdapter
    from .adapters.hermes import HermesAdapter
    options = deepcopy(settings)
    executable = options.pop('executable', '')
    factory = {'claude': ClaudeAdapter, 'codex': CodexAdapter,
               'dot': DotAdapter, 'local': HermesAdapter}[provider]
    return factory(emit, executable=executable, **options)
