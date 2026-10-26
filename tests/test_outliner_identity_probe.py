import importlib.util
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('identity_probe',Path(__file__).resolve().parents[1]/
                                           'scripts/hammer_outliner_identity_probe.py')
probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)


class OutlinerIdentityProbeTests(unittest.TestCase):
    def test_vector_bounds_and_valid_offset(self):
        for count,offset in ((-1,24),(4097,24),(1,0),(1,1025)):
            header=struct.pack('<iiiIq',1,count,0,0,offset)
            reader=probe.Reader(None,{})
            with patch.object(probe.BindingReader,'read',return_value=header):
                with self.assertRaises(ValueError):reader.vector(0x10000,4)
        reader=probe.Reader(None,{})
        with patch.object(probe.BindingReader,'read',side_effect=[
                struct.pack('<iiiIq',1,2,0,0,24),struct.pack('<ii',4,9)]):
            self.assertEqual(struct.unpack('<ii',reader.vector(0x10000,4)),(4,9))

    def test_repeated_read_change_and_address_bounds_fail_closed(self):
        reader=probe.Reader(None,{})
        with patch.object(probe.BindingReader,'read',side_effect=[b'aaaa',b'bbbb']) as native:
            for address,size in ((0,4),(0x10000,32769)):
                with self.assertRaises(ValueError):reader.read(address,size)
            native.assert_not_called()
            reader.read(0x10000,4)
            with self.assertRaisesRegex(ValueError,'changed'):reader.read(0x10000,4)

    def test_unverified_model_rejected_before_pointer_traversal(self):
        reader=probe.Reader(None,{})
        with patch.object(reader,'type_of',return_value=('hammer.dll','wrong',0)),patch.object(reader,'ptr') as ptr:
            with self.assertRaisesRegex(ValueError,'proxy model'):
                reader.entity({'row_key':'10000:20000:0:0'})
            ptr.assert_not_called()
