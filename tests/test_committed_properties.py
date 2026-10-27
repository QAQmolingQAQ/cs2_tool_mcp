from pathlib import Path
import struct,sys,unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mcp_server'))
from hammer_mcp.committed_properties import attributes
from hammer_mcp import committed_properties as cp
from uuid import UUID


class CommittedPropertyTests(unittest.TestCase):
    def test_full_handle_generation_mismatch_rejects_reused_table_slot(self):
        guid='657b42df-8155-4005-9f33-8ff4072e6c70'
        identity={'identities':[{'entity_guid':guid,'entity_address':'0x10000'}],
                  'before':{'runtime':{'live':{'modules':{'hammer.dll':{'base':'0x100000'}}}}}}
        reader=Mock();reader.type_of.side_effect=[('hammer.dll','.?AVCMapEntity@@',0x175ad00),
            ('hammer.dll','.?AVCDataModel@@',0x16c45d8),
            ('hammer.dll','.?AVCEditGameClassProps@@',0x17602b8)]
        reader.read.side_effect=[UUID(guid).bytes_le,struct.pack('<I',26),
            struct.pack('<IIQ Q',54,0,139,0x40000),struct.pack('<I',26+(1<<22))]
        reader.ptr.return_value=0x20000
        with patch.object(cp,'read_identities',return_value=identity),patch.object(cp,'Reader',return_value=reader),patch.object(
                cp,'get_session'),patch.object(cp,'attributes',return_value={
                    'entity_properties':{'type':1,'value_pointer':0x30000}}):
            with self.assertRaisesRegex(ValueError,'generation mismatch'):
                cp.read_committed_properties('private-config','test',guid)

    def header(self,following=0,owner=0x10000):
        return struct.pack('<QQQIIQ',following,0x30000,owner,0,5,0x40000)

    def test_owner_mismatch_and_cycles_are_errors(self):
        reader=Mock();reader.ptr.return_value=0x20000
        reader.read.return_value=self.header(owner=0x10001)
        with self.assertRaisesRegex(ValueError,'owner mismatch'):attributes(reader,0x10000)
        reader.read.return_value=self.header(following=0x20000);reader.text.return_value='targetname'
        with self.assertRaisesRegex(ValueError,'cycle'):attributes(reader,0x10000)

    def test_duplicate_and_empty_keys_are_not_silently_overwritten(self):
        reader=Mock();reader.ptr.return_value=0x20000;reader.text.return_value='targetname'
        reader.read.side_effect=[self.header(following=0x20030),self.header()]
        with self.assertRaisesRegex(ValueError,'duplicate'):attributes(reader,0x10000)
        reader.read.side_effect=None;reader.read.return_value=self.header();reader.text.return_value=''
        with self.assertRaisesRegex(ValueError,'empty'):attributes(reader,0x10000)

    def test_typed_reference_and_empty_chain(self):
        reader=Mock();reader.ptr.return_value=0x20000;reader.text.return_value='targetname'
        reader.read.return_value=self.header()
        self.assertEqual(attributes(reader,0x10000),{'targetname':{'type':5,'value_pointer':0x30000}})
        reader.ptr.return_value=0
        self.assertEqual(attributes(reader,0x10000),{})
