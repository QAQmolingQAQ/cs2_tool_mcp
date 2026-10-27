from pathlib import Path
import struct,sys,unittest
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mcp_server'))
from hammer_mcp.history_snapshot import stack,batch_undo_plan


class HistorySnapshotTests(unittest.TestCase):
    def test_batch_plan_includes_exact_recorded_selection_steps(self):
        steps=[{'name':name,'id_candidate':index} for index,name in enumerate(
            ('Modify Selection','Change: Name','Modify Selection','Change: Name'))]
        before={'entities':[{'id':'a','properties':{'targetname':''}},{'id':'b','properties':{'targetname':''}}]}
        after={'entities':[{'id':'a','properties':{'targetname':'a'}},{'id':'b','properties':{'targetname':'b'}}]}
        rows=[]
        for index in range(2):
            start=index*2
            rows.append({'index':index,'status':'verified_modified',
                         'history_before_selection':{'undo':steps[:start]},
                         'history_after_selection':{'undo':steps[:start+1]},
                         'history_before_write':{'undo':steps[:start+1]},
                         'history_after_write':{'undo':steps[:start+2]}})
        batch={'status':'verified','results':rows,'before':before,'after':after}
        actions=batch_undo_plan(batch)
        self.assertEqual([x['kind'] for x in actions],['property','selection','property','selection'])
        self.assertEqual(actions[-1]['after_properties'],before)
        rows[1]['history_before_selection']={'undo':[]}
        with self.assertRaisesRegex(ValueError,'intervening'):batch_undo_plan(batch)

    def reader(self,count):
        r=Mock();r.type_of.return_value=('hammer.dll','.?AVCMapDocHistory@@',0x1765e00)
        r.ptr.side_effect=[0x10008,0x30000]
        r.read.side_effect=[struct.pack('<QIIQ',0,count,0,0x20000),
                            struct.pack('<IIQQQII',1,0,0x40000,0,0x50000,7,0)]
        r.text.return_value='Modify Selection'
        return r

    def test_valid_step_identity_and_name(self):
        rows=stack(self.reader(1),0x50000,0x10000)
        self.assertEqual(rows[0]['name'],'Modify Selection')
        self.assertEqual(rows[0]['id_candidate'],7)

    def test_wrong_owner_and_oversized_stack_rejected(self):
        r=self.reader(1);r.ptr.side_effect=[0x10010]
        with self.assertRaisesRegex(ValueError,'document owner'):stack(r,0x50000,0x10000)
        with self.assertRaisesRegex(ValueError,'count/pointer'):stack(self.reader(1025),0x50000,0x10000)
        r=self.reader(1);r.read.side_effect=[struct.pack('<QIIQ',0,1,0,0x20000),
                                           struct.pack('<IIQQQII',1,0,0x40000,0,0x50008,7,0)]
        with self.assertRaisesRegex(ValueError,'step owner'):stack(r,0x50000,0x10000)
