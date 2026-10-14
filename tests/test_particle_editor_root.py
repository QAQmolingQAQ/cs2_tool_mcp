import unittest
from unittest.mock import patch
from hammer_mcp import particle_editor_root as per


class ParticleRootTests(unittest.TestCase):
    def context(self):
        doc = {'ok': True, 'session': '0x2000', 'root': '0x3000'}
        module = {'cls': 'CPetApp', 'base': 0x10000}
        return doc, module

    def test_document_change_discards_partial_result(self):
        doc, module = self.context()
        with patch.object(per, 'cs2_editor_document', side_effect=[doc, {**doc, 'session': '0x4000'}]), \
             patch.object(per, '_tool_module', return_value=module), \
             patch.object(per, '_read_int', side_effect=[0x100, 0x6AC7FFFE, 0xA76000]), \
             patch.object(per, '_editor_session_class', return_value='CPetRootNode'), \
             patch.object(per, '_value', return_value=(9, 0, b'')), \
             patch.object(per, '_follow', side_effect=[0x5000, 0x6000]), \
             patch.object(per, '_decode', side_effect=[{'value': 'CParticleSystemDefinition'},
                                                       {'kv3_type': 'double', 'value': 106.0}]):
            result = per.cs2_particle_editor_root_value('m_flConstantRadius')
        self.assertFalse(result['ok'])
        self.assertNotIn('value', result)
        self.assertIn('changed during read', result['error'])

    def test_unsupported_build_rejected_before_root_read(self):
        doc, module = self.context()
        with patch.object(per, 'cs2_editor_document', return_value=doc), \
             patch.object(per, '_tool_module', return_value=module), \
             patch.object(per, '_read_int', side_effect=[0x100, 0, 0]), \
             patch.object(per, '_value') as read:
            result = per.cs2_particle_editor_root_value('m_nMaxParticles')
        self.assertFalse(result['ok'])
        read.assert_not_called()
        self.assertIn('unsupported', result['error'])

    def test_wrong_root_rtti_rejected(self):
        doc, module = self.context()
        with patch.object(per, 'cs2_editor_document', return_value=doc), \
             patch.object(per, '_tool_module', return_value=module), \
             patch.object(per, '_read_int', side_effect=[0x100, 0x6AC7FFFE, 0xA76000]), \
             patch.object(per, '_editor_session_class', return_value='CPetFunctionNode'), \
             patch.object(per, '_value') as read:
            result = per.cs2_particle_editor_root_value('m_nMaxParticles')
        self.assertFalse(result['ok'])
        read.assert_not_called()
        self.assertIn('RTTI', result['error'])


if __name__ == '__main__':
    unittest.main()
