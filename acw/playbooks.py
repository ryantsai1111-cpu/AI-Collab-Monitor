"""Per-instance role instructions and a plain Markdown projection for external callers."""
from __future__ import annotations

from copy import deepcopy
import json
import logging
import os
from pathlib import Path
import tempfile
from weakref import WeakKeyDictionary

from .security import reject_link_ancestors


def _default(role, duties, instructions, report, *, local=False):
    return dict(role=role, duties=duties, instructions=instructions,
                limits=dict(run_budget=600 if local else 3000, max_turns=60 if local else 150,
                            timeout_seconds=7200),
                permissions=dict(commit=True, push=True, outside_card=False), report=report)


DEFAULTS = {
    'claude': _default('架構與審查', '規劃任務、定義驗收條件，審查實作與風險。',
                       '只讀規劃與審查，不修改檔案。\n回覆第一行使用本步驟要求的 VERDICT 判定。',
                       '回報判定、依據、具體問題與未盡事項。'),
    'dot': _default('複核與轉交', '複核計畫與實作，整理自足的交接單。',
                    '依本步驟要求複核與轉交，不擅自擴大任務。\n保留 VERDICT 與交接信封格式。',
                    '列出發現、必要修正與給下一位 Agent 的完整交接內容。'),
    'codex': _default('實作者', '依規格實作、驗證並提供可審查的成果。',
                      '只修改規格允許的範圍；不 push main。\n執行適當測試，回報附實際執行輸出。',
                      '變更檔案與原因、驗證輸出、分支與 commit、PR 連結、未盡事項。'),
    'local': _default('實作者', '依 PROGRESS.md 指定的任務卡逐步實作與更新進度。',
                      '先讀 PROGRESS.md，只執行它指定的任務卡。\n長輸出導到 tmp，再讀必要的尾段。\n'
                      '遇到卡片未涵蓋的決策，記錄 [DECISION NEEDED] 並停止回報。\n不 push main，不擴大範圍。',
                      '回報完成的任務卡、變更檔案、測試輸出、commit 與未盡事項。', local=True),
}


def _normalize(provider, data):
    if not isinstance(data, dict):
        raise ValueError('Playbook must be an object')
    result = deepcopy(DEFAULTS[provider])
    if set(data) - set(result):
        raise ValueError('Unknown playbook field')
    for field, value in data.items():
        if field in ('limits', 'permissions'):
            if not isinstance(value, dict) or set(value) - set(result[field]):
                raise ValueError('Invalid playbook ' + field)
            result[field].update(value)
        else:
            result[field] = value
    for field in ('role', 'duties', 'instructions', 'report'):
        value = result[field]
        if not isinstance(value, str) or len(value) > (40 if field == 'role' else 20000):
            raise ValueError('Invalid playbook ' + field)
    if '\n' in result['role'] or '\r' in result['role']:
        raise ValueError('Playbook role must be a single line')
    if any(type(value) is not int or not 1 <= value <= 2147483647 for value in result['limits'].values()):
        raise ValueError('Playbook limits must be positive integers within the editor range')
    if any(type(value) is not bool for value in result['permissions'].values()):
        raise ValueError('Playbook permissions must be booleans')
    return result


_INVALID_WARNED = WeakKeyDictionary()


_LOADED = WeakKeyDictionary()


def load(core, agent):
    provider = core.provider(agent)
    raw = core.get_setting('playbook.' + agent, {})
    try:
        # The Monitor asks once per agent per second; validate only when the stored value changed.
        stamp = (provider, json.dumps(raw, sort_keys=True, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        stamp = None
    cached = _LOADED.get(core, {}).get(agent) if stamp else None
    if cached and cached[0] == stamp:
        if core in _INVALID_WARNED:
            _INVALID_WARNED[core].discard(agent)
        return deepcopy(cached[1])
    try:
        result = _normalize(provider, raw)
    except (ValueError, TypeError):
        warned = _INVALID_WARNED.setdefault(core, set())
        if agent not in warned:
            warned.add(agent)
            logging.getLogger('acw.playbooks').warning('Invalid playbook for %s; using provider defaults', agent)
        return deepcopy(DEFAULTS[provider])
    if core in _INVALID_WARNED:
        _INVALID_WARNED[core].discard(agent)
    if stamp:
        _LOADED.setdefault(core, {})[agent] = (stamp, deepcopy(result))
    return result


def render(data):
    limits = '\n'.join(f'- {key}: {value}' for key, value in data['limits'].items())
    permissions = '\n'.join(f'- {key}: {str(value).lower()}' for key, value in data['permissions'].items())
    return (f"# 角色腳本\n\n## 角色\n{data['role']}\n\n## 職責\n{data['duties']}\n\n"
            f"## 指示\n{data['instructions']}\n\n## 限制\n{limits}\n\n## 權限\n{permissions}\n\n"
            f"## 回報格式\n{data['report']}\n")


def save(core, agent, data):
    result = _normalize(core.provider(agent), data)
    directory = Path(core.data_dir) / 'playbooks'
    destination = directory / (agent + '.md')
    reject_link_ancestors(destination)
    directory.mkdir(parents=True, exist_ok=True)
    temporary = None
    core.set_setting('playbook.' + agent, result)
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                         dir=directory, suffix='.tmp', delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(render(result))
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return deepcopy(result)


def reset(core, agent):
    return save(core, agent, deepcopy(DEFAULTS[core.provider(agent)]))


def compose_prompt(core, agent, body):
    instructions = load(core, agent)['instructions']
    return instructions + '\n\n---\n\n' + body if instructions else body
