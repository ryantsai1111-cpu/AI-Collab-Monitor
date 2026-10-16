"""Isolated playbook settings, validation and Markdown projection contracts."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import os

from acw.core import WorkspaceCore
from acw import playbooks


class PlaybookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.core = WorkspaceCore(Path(self.temp.name) / 'data', {})
        self.addCleanup(self.core.close)

    def test_defaults_are_detached_and_new_instances_use_provider_defaults(self):
        for agent in self.core.agent_ids:
            self.assertEqual(playbooks.DEFAULTS[agent], playbooks.load(self.core, agent))
        instance = self.core.create_agent_instance('codex', 'Second implementer')['id']
        self.assertEqual(playbooks.DEFAULTS['codex'], playbooks.load(self.core, instance))
        loaded = playbooks.load(self.core, instance)
        loaded['limits']['run_budget'] = 1
        self.assertNotEqual(loaded, playbooks.load(self.core, instance))

    def test_save_roundtrip_projection_merge_and_reset(self):
        data = playbooks.load(self.core, 'codex')
        data.update(role='驗證實作者', instructions='Only this test instruction')
        data['permissions']['push'] = False
        playbooks.save(self.core, 'codex', data)
        self.assertEqual(data, playbooks.load(self.core, 'codex'))
        projected = Path(self.core.data_dir) / 'playbooks/codex.md'
        self.assertIn(data['role'], projected.read_text(encoding='utf-8'))
        self.assertFalse(list(projected.parent.glob('*.tmp')))
        self.core.set_setting('playbook.local', {'role': 'Custom', 'limits': {'max_turns': 7}})
        self.assertEqual(7, playbooks.load(self.core, 'local')['limits']['max_turns'])
        self.assertEqual(600, playbooks.load(self.core, 'local')['limits']['run_budget'])
        self.assertEqual(playbooks.DEFAULTS['codex'], playbooks.reset(self.core, 'codex'))
        self.assertEqual(playbooks.DEFAULTS['codex'], playbooks.load(self.core, 'codex'))

    def test_invalid_fields_are_rejected_before_persistence(self):
        invalid = [{'role': 'x' * 41}, {'instructions': 'x' * 20001}, {'duties': []},
                   {'limits': {'run_budget': True}}, {'limits': {'max_turns': 0}},
                   {'limits': {'timeout_seconds': -1}}, {'permissions': {'push': 1}},
                   {'report': None}, {'unexpected': 'field'}]
        for value in invalid:
            with self.subTest(value=str(value)[:80]), self.assertRaises(ValueError):
                playbooks.save(self.core, 'local', value)
        self.assertIsNone(self.core.get_setting('playbook.local'))

    def test_invalid_saved_data_falls_back_once_and_compose_remains_usable(self):
        self.core.set_setting('playbook.claude', {'role': 'x' * 99})
        with self.assertLogs('acw.playbooks', level='WARNING') as warnings:
            first = playbooks.load(self.core, 'claude')
            self.assertEqual(playbooks.DEFAULTS['claude'], first)
            self.assertTrue(playbooks.compose_prompt(self.core, 'claude', 'Body').endswith('Body'))
            playbooks.load(self.core, 'claude')
        self.assertEqual(1, len(warnings.output))
        first['limits']['max_turns'] = 1
        self.assertEqual(playbooks.DEFAULTS['claude'], playbooks.load(self.core, 'claude'))

    def test_save_updates_settings_before_markdown_and_failed_setting_write_preserves_projection(self):
        real_replace = os.replace
        def replace(source, destination):
            self.assertEqual('Persisted first', self.core.get_setting('playbook.codex')['role'])
            real_replace(source, destination)
        with patch('acw.playbooks.os.replace', side_effect=replace):
            playbooks.save(self.core, 'codex', {'role': 'Persisted first'})
        path = self.core.data_dir / 'playbooks/codex.md'
        original = path.read_bytes()
        with patch.object(self.core, 'set_setting', side_effect=RuntimeError('Fixture write failure')), \
                self.assertRaises(RuntimeError):
            playbooks.save(self.core, 'codex', {'role': 'Must not reach Markdown'})
        self.assertEqual(original, path.read_bytes())

    def test_compose_empty_and_nonempty_instructions(self):
        playbooks.save(self.core, 'codex', {'instructions': 'Instruction'})
        self.assertEqual('Instruction\n\n---\n\nBody', playbooks.compose_prompt(self.core, 'codex', 'Body'))
        playbooks.save(self.core, 'codex', {'instructions': ''})
        self.assertEqual('Body', playbooks.compose_prompt(self.core, 'codex', 'Body'))
