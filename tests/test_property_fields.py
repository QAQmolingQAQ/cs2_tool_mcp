"""Property names must come from verified row descriptors, never blank text guesses."""
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mcp_server'))
from hammer_mcp.property_fields import BindingReader, verify_layout, HASHES


class MemoryPipe:
    def __init__(self):self.memory={}
    def put(self,address,raw):
        for index,value in enumerate(raw):self.memory[address+index]=value
    def ptr(self,address,value):self.put(address,struct.pack('<Q',value))
    def text(self,address,text):self.put(address,text.encode()+bytes(256))
    def call(self,method,params):
        if method!='read_memory':raise AssertionError('native operation forbidden')
        try:raw=bytes(self.memory[params['address']+i] for i in range(params['size']))
        except KeyError:return {'error':'unreadable fixture memory'}
        return {'result':{'hex':'0x'+raw.hex()}}


class PropertyFieldTests(unittest.TestCase):
    def fixture(self):
        pipe=MemoryPipe();base=0x10000000;qt=0x20000000
        modules={'propertyeditor.dll':{'base':hex(base),'image_size':0x200000},
                 'qt5widgets.dll':{'base':hex(qt),'image_size':0x200000}}
        editor=0x50000000;private=editor+0x1000;row=editor+0x2000;item=editor+0x3000
        def obj(address,module,vt,col,td,name):
            pipe.ptr(address,module+vt);pipe.ptr(module+vt-8,module+col)
            pipe.put(module+col,struct.pack('<6I',1,0,0,td,0,col));pipe.text(module+td+16,name)
        obj(editor,qt,0x8000,0x9000,0xa000,'.?AVQLineEdit@@')
        obj(row,base,0x10f900,0x5000,0x7000,'.?AVCQPropRow@@')
        obj(item,base,0x109488,0x6000,0x8000,'.?AVCPropItem_Attr@@')
        pipe.ptr(editor+8,private);pipe.ptr(private+16,row);pipe.ptr(row+0x68,item)
        pipe.ptr(item+0x18,row);pipe.ptr(item+0x28,item+0x1000);pipe.ptr(item+0x30,item+0x2000)
        pipe.text(item+0x1000,'targetname');pipe.text(item+0x2000,'Name')
        return pipe,BindingReader(pipe,modules),editor,private,row,item

    def test_key_and_label_are_read_from_typed_item(self):
        pipe,reader,editor,_,row,item=self.fixture();result=reader.binding(editor)
        self.assertEqual(result['property'],'targetname');self.assertEqual(result['display_name'],'Name')
        self.assertEqual(result['row_address'],hex(row));self.assertEqual(result['item_address'],hex(item))
        self.assertEqual(len(result['editor_types']),2)

    def test_stale_row_backreference_rejected(self):
        pipe,reader,editor,_,row,item=self.fixture();pipe.ptr(item+0x18,row+8)
        with self.assertRaisesRegex(ValueError,'backreference'):reader.binding(editor)

    def test_parent_cycle_and_unbound_filter_are_distinct(self):
        pipe,reader,editor,private,_,_=self.fixture();pipe.ptr(private+16,editor)
        with self.assertRaisesRegex(ValueError,'cyclic'):reader.binding(editor)
        pipe.ptr(private+16,0);self.assertIsNone(reader.binding(editor))

    def test_mismatched_rtti_locator_rejected(self):
        pipe,reader,editor,_,_,_=self.fixture();pipe.put(0x20009000,struct.pack('<6I',1,0,0,0xa000,0,0x9999))
        with self.assertRaisesRegex(ValueError,'RTTI'):reader.binding(editor)

    def test_unterminated_and_invalid_utf8_keys_rejected(self):
        for raw in (b'x'*128,b'\xff'+b'\0'*127):
            pipe,reader,editor,_,_,item=self.fixture();pipe.put(item+0x1000,raw)
            with self.assertRaises(ValueError):reader.binding(editor)

    def test_every_layout_hash_and_loaded_identity_is_required(self):
        modules={name:{'sha256':digest,'loaded_matches_disk_headers':True} for name,digest in HASHES.items()}
        verify_layout(modules)
        for name in modules:
            changed={k:dict(v) for k,v in modules.items()};changed[name]['sha256']='changed'
            with self.assertRaisesRegex(ValueError,'unsupported'):verify_layout(changed)
        modules['propertyeditor.dll']['loaded_matches_disk_headers']=False
        with self.assertRaises(ValueError):verify_layout(modules)
