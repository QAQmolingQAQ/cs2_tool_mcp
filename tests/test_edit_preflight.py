import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'mcp_server'))
from hammer_mcp import edit_preflight as ep


class PreflightTests(unittest.TestCase):
    def test_persistent_baseline_and_disk_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'a.vmap'; source.write_text('original')
            config = root / 'project.json'; config.write_text('{}')
            project = dict(source=str(source), config_path=str(config),
                           config_sha256=ep.sha256(config), state_root=str(root),
                           profile='test', addon='test')
            with patch.object(ep, 'load_project', return_value=project), patch.object(
                    ep, 'inspect_live', side_effect=OSError('offline')):
                first = ep.cs2_edit_preflight()
                self.assertTrue(first['ok'])
                second = ep.cs2_edit_preflight(baseline_id=first['id'])
                self.assertEqual(second['conflict_check'], 'matched')
                self.assertFalse(second['safe_to_write'])
                source.write_text('edited')
                third = ep.cs2_edit_preflight(baseline_id=first['id'],
                                             expected_source_hash=first['evidence']['source']['sha256'])
                self.assertIn('source_changed', third['conflicts'])
                self.assertIn('expected_source_hash_mismatch', third['conflicts'])
                self.assertFalse(third['safe_to_write'])
                saved = json.loads((root/'edit_preflights'/(first['id']+'.json')).read_text())
                self.assertEqual(saved, first)
                self.assertEqual(source.read_text(), 'edited')

    def test_runtime_domains_and_input_validation(self):
        old = {'runtime': {'pid': 1}, 'layout': {'generation': 1}}
        new = {'runtime': {'pid': 2}, 'layout': {'generation': 2}}
        self.assertEqual(ep.compare(old, new), ['layout_changed', 'runtime_changed'])
        self.assertFalse(ep.cs2_edit_preflight(baseline_id='../escape')['ok'])
        self.assertFalse(ep.cs2_edit_preflight(expected_source_hash='x')['ok'])

    def test_config_race_blocks_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'map';path.write_text('x')
            with self.assertRaisesRegex(ValueError, 'config changed'):
                ep.collect(dict(source=str(path),config_path=str(path),config_sha256='wrong',
                                profile='test',addon='test'))
