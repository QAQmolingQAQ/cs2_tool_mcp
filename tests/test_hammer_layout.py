import sys,struct,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mcp_server'))
from hammer_mcp.hammer_layout import sample_layout,APP_RVA,APP_VTABLE_RVA,MANAGER_POINTER_RVA
from hammer_mcp.hammer_layout import direct_dirty_documents

class LayoutTests(unittest.TestCase):
    def fixture(self):
        base=0x10000000; app=bytearray(0x68)
        struct.pack_into('<Q',app,0,base+APP_VTABLE_RVA)
        spans={base+APP_RVA:app,base+MANAGER_POINTER_RVA:struct.pack('<Q',0x20000000),0x20000000:bytes(16)}
        def read(a,n):return bytes(spans[a][:n])
        return base,app,spans,read
    def test_empty_is_unknown_not_clean(self):
        b,app,m,r=self.fixture();d=sample_layout(r,b)
        self.assertEqual(d['session_count_candidate'],0)
        self.assertEqual(d['dirty_state'],'unknown');self.assertFalse(d['safe_to_write'])
    def test_nonempty_groups_are_raw_candidates(self):
        b,app,m,r=self.fixture()
        struct.pack_into('<i',app,0x58,1);struct.pack_into('<Q',app,0x60,0x30000000)
        m[0x30000000]=struct.pack('<Q',0x40000000)
        session=bytearray(0x140);struct.pack_into('<Q',session,0x138,0x50000000);m[0x40000000]=session
        for index,(address,vt,name) in enumerate(((0x40000000,0x1DF74E8,'.?AVCHammerEditorSession@@'),
                (0x50000000,0x1DFA7C0,'.?AVCMapDocSession@@'),(0x50000010,0x1766188,'.?AVCMapDoc@@'))):
            vtable=b+vt;col=b+0x300000+index*0x100;td=0x200000+index*0x100
            if address==0x40000000:struct.pack_into('<Q',session,0,vtable)
            else:m[address]=struct.pack('<Q',vtable)
            m[vtable-8]=struct.pack('<Q',col)
            m[col]=struct.pack('<6I',1,0,0,td,0,col-b)
            m[b+td+16]=name.encode().ljust(64,b'\0')
        m[0x50000010+0x6a0]=struct.pack('<Q',0x80000000)
        m[0x80000000]=b'C:/test.vmap\0'.ljust(64,b'\0')
        m[0x20000000]=struct.pack('<i4xQ',1,0x60000000)
        bucket=bytearray(0x38);struct.pack_into('<i',bucket,8,1);struct.pack_into('<Q',bucket,16,0x70000000);struct.pack_into('<Q',bucket,40,5);m[0x60000000]=bucket
        entry=bytearray(0x20);struct.pack_into('<Q',entry,0,0x50000010);struct.pack_into('<Q',entry,16,6);m[0x70000000]=entry
        result=sample_layout(r,b)
        self.assertEqual(result['dirty_groups'][0]['documents'][0]['generation_candidate'],6)
        self.assertEqual(result['dirty_state'],'unknown')
        self.assertEqual(len(result['direct_document_unsaved_changes']),1)
        self.assertEqual(result['sessions'][0]['document_path'],'C:/test.vmap')
        original=m[b+0x200000+2*0x100+16]
        m[b+0x200000+2*0x100+16]=b'.?AVWrong@@\0'.ljust(64,b'\0')
        with self.assertRaisesRegex(ValueError,'RTTI mismatch'):sample_layout(r,b)
        m[b+0x200000+2*0x100+16]=original
        m[0x80000000]=b'\xff\0'.ljust(64,b'\0')
        with self.assertRaises(UnicodeDecodeError):sample_layout(r,b)
    def test_bound_vtable_and_concurrent_change_rejection(self):
        b,app,m,r=self.fixture();struct.pack_into('<i',app,0x58,33)
        with self.assertRaises(ValueError):sample_layout(r,b)
        struct.pack_into('<i',app,0x58,0);app[0]=0
        with self.assertRaises(ValueError):sample_layout(r,b)
        b,app,m,r=self.fixture();calls=0
        def changed(a,n):
            nonlocal calls
            calls+=1
            if calls==4:return bytes(n)
            return r(a,n)
        with self.assertRaisesRegex(ValueError,'changed'):sample_layout(changed,b)
    def test_direct_dirty_does_not_certify_unrelated_or_equal_generations(self):
        sessions=[{'document_candidate':'known'}]
        group={'saved_generation_candidate':5,'documents':[
            {'document':'known','generation_candidate':5},
            {'document':'other','generation_candidate':99}]}
        self.assertEqual(direct_dirty_documents([group],sessions),[])
        group['documents'][0]['generation_candidate']=6
        self.assertEqual(direct_dirty_documents([group],sessions)[0]['document'],'known')

if __name__=='__main__':unittest.main()
