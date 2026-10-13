import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'mcp_server'))
from hammer_mcp.particle_catalog import cs2_particle_functions, cs2_particle_function_info


class ParticleCatalogTests(unittest.TestCase):
    def test_full_registry_counts_and_pagination(self):
        result = cs2_particle_functions(limit=100)
        self.assertTrue(result['ok'])
        self.assertEqual(result['total'], 376)
        self.assertEqual(len(result['functions']), 100)
        self.assertEqual([cs2_particle_functions(category=str(i))['total'] for i in range(7)],
                         [49, 4, 98, 161, 16, 13, 35])
        self.assertEqual(cs2_particle_functions(category='Emitters')['total'], 4)
        self.assertEqual(cs2_particle_functions(offset=375)['functions'][0]['index'], 34)

    def test_search_and_inherited_property_schema(self):
        found = cs2_particle_functions(query='Emit continuously')
        self.assertEqual(found['total'], 1)
        self.assertEqual(found['functions'][0]['class_name'], 'C_OP_ContinuousEmitter')
        detail = cs2_particle_function_info('C_OP_ContinuousEmitter')
        self.assertTrue(detail['ok'])
        self.assertEqual(detail['inheritance'],
                         ['C_OP_ContinuousEmitter', 'CParticleFunctionEmitter', 'CParticleFunction'])
        self.assertEqual(detail['field_count'], len(detail['fields']))
        self.assertTrue(any(field['declared_in'] == 'CParticleFunction' for field in detail['fields']))
        self.assertTrue(any(field['type'] == 'float32' for field in detail['fields']))

    def test_invalid_queries(self):
        self.assertFalse(cs2_particle_functions(category='bad')['ok'])
        self.assertFalse(cs2_particle_functions(limit=101)['ok'])
        self.assertFalse(cs2_particle_function_info('C_OP_Unknown')['ok'])


if __name__ == '__main__':
    unittest.main()
