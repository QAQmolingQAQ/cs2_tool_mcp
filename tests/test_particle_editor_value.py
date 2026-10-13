import struct
import unittest
from unittest.mock import patch

from hammer_mcp import particle_editor_value as pev


class ParticleValueTests(unittest.TestCase):
    def test_pet_hash_matches_native_samples(self):
        self.assertEqual(pev._hash_name('_class'), 0x2B234708)
        self.assertEqual(pev._hash_name('m_InputValue'), 0xE1E525B2)
        self.assertEqual(pev._hash_name('m_nOutputField'), 0xCFEC116E)

    def test_path_rejects_unbounded_or_invalid_selectors(self):
        self.assertEqual(pev._path('m_vecTexturesInput[0].m_hTexture'),
                         ['m_vecTexturesInput', 0, 'm_hTexture'])
        for value in ('foo[-1]', 'foo[1000]', 'foo..bar', 'foo/' + 'a' * 160):
            with self.assertRaises(ValueError):
                pev._path(value)

    def test_inline_object_array_and_nested_value(self):
        memory = bytearray(0x400)
        def put(address, data):
            memory[address:address + len(data)] = data
        # Root KV3 object -> one hash slot -> nested KV3 array -> two doubles.
        put(0x20, struct.pack('<QQ', 9 << 2, 0x80))
        put(0x84, struct.pack('<I', 1))
        put(0x90, struct.pack('<I', 1))
        put(0x98, struct.pack('<I', pev._hash_name('m_vecCP2Pos')))
        put(0xA0, struct.pack('<Q', 0xC0))
        put(0xC0, struct.pack('<QQ', 8 << 2, 0xE0))
        put(0xE4, struct.pack('<I', 2))
        put(0xE8, struct.pack('<I', 2))
        put(0xF0, struct.pack('<QQ', 0x120, 0x140))
        put(0x120, struct.pack('<Qd', 5 << 2, 1000.0))
        put(0x140, struct.pack('<Qd', 5 << 2, -2.5))
        with patch.object(pev, '_read_bytes', side_effect=lambda a, n: bytes(memory[a:a+n])):
            address = pev._follow(0x20, pev._path('m_vecCP2Pos[1]'))
            self.assertEqual(pev._decode(address)['value'], -2.5)
            self.assertEqual([item['value'] for item in pev._decode(0xC0)['value']],
                             [1000.0, -2.5])


if __name__ == '__main__':
    unittest.main()
