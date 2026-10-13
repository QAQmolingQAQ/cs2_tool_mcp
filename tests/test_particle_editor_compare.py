import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hammer_mcp import particle_editor_compare as cmp


class ParticleCompareTests(unittest.TestCase):
    def test_typed_resource_and_numeric_tolerance(self):
        self.assertTrue(cmp._equal('materials/example.vtex', {'type': 'resource', 'value': 'materials/example.vtex'}))
        self.assertTrue(cmp._equal([1000.00000001, 0.0], [1000.0, 0.0]))
        self.assertFalse(cmp._equal(True, 1))

    def test_saved_source_match_and_missing_default(self):
        source = '''<!-- kv3 encoding:text:version{e21c7f3c-8a7e-45e8-8e4d-4fb1e7a5fa2d} format:vpcf66:version{1} -->
{ m_Initializers = [ { _class = "C_INIT_InitFloat" m_InputValue = { m_flLiteralValue = 1.0 } } ] }
'''
        live = {'ok': True, 'class_name': 'C_INIT_InitFloat', 'session': '0x123',
                'kv3_type': 'double', 'value': 1.0}
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'sample.vpcf'
            file.write_text(source, encoding='utf-8')
            with patch.object(cmp, 'cs2_particle_editor_value', return_value=live), \
                 patch.object(cmp, 'cs2_editor_document', return_value={'ok': True, 'session': '0x123'}), \
                 patch.object(cmp, '_read_int', return_value=0x456), \
                 patch.object(cmp, '_read_string', return_value=str(file)):
                found = cmp.cs2_particle_editor_compare(str(file), 2, 0, 'm_InputValue.m_flLiteralValue')
                self.assertTrue(found['ok'] and found['comparable'] and found['equal'])
                self.assertTrue(found['source_file_verified_as_active'])
                missing = cmp.cs2_particle_editor_compare(str(file), 2, 0, 'm_nOutputField')
                self.assertTrue(missing['ok'])
                self.assertFalse(missing['comparable'])
                with patch.object(cmp, '_read_string', return_value=str(file.with_name('other.vpcf'))):
                    mismatch = cmp.cs2_particle_editor_compare(str(file), 2, 0, 'm_InputValue.m_flLiteralValue')
                    self.assertFalse(mismatch['ok'])
                    self.assertIn('does not match', mismatch['error'])


if __name__ == '__main__':
    unittest.main()
