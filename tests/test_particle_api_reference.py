import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from export_particle_api_reference import build_reference


class ParticleApiReferenceTests(unittest.TestCase):
    def test_export_matches_versioned_catalog(self):
        source = json.loads((ROOT / 'mcp_server/hammer_mcp/data/particle_functions.json').read_text(encoding='utf-8'))
        actual = build_reference(source)
        saved = json.loads((ROOT / 'PARTICLE_API_REFERENCE.json').read_text(encoding='utf-8'))
        self.assertEqual(actual, saved)
        self.assertEqual(saved['function_count'], 376)
        self.assertEqual([x['function_count'] for x in saved['categories']],
                         [49, 4, 98, 161, 16, 13, 35])
        all_fields = [field for row in saved['functions'] for field in row['parameters']]
        self.assertEqual(len(all_fields), 9467)
        self.assertTrue(all(field['type'] for field in all_fields))
        self.assertEqual(sum(field['editor_hidden_by_schema'] for field in all_fields), 376)


if __name__ == '__main__':
    unittest.main()
