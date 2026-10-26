from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'mcp_server'))
from hammer_mcp.edit_preview import plan_properties, cs2_edit_preview


class PreviewTests(unittest.TestCase):
    def test_plan_conflict_noop_and_invalid_are_per_operation(self):
        entities=[{'id':'one','properties':{'targetname':'a','speed':'10'}}]
        ops=[{'entity_id':'one','property':'TargetName','expected':'a','value':'b'},
             {'entity_id':'one','property':'speed','expected':'9','value':'11'},
             {'entity_id':'missing','property':'speed','expected':'0','value':'1'},
             {'entity_id':'one','property':'targetname','expected':'a','value':'c'},
             {'entity_id':'one','property':'classname','expected':'x','value':'y'}]
        rows=plan_properties(entities,ops)
        self.assertEqual([r['status'] for r in rows],['planned','conflict','invalid','invalid','invalid'])
        self.assertEqual(rows[0]['before'],'a')
        self.assertTrue(all(not r['executed'] for r in rows))
        self.assertEqual(entities[0]['properties']['targetname'],'a')
        self.assertEqual(plan_properties(entities,[dict(ops[0],value='a')])[0]['status'],'no_change')

    def test_bounds_and_ambiguous_ids(self):
        for ops in ([],{},[{}]*257):
            with self.assertRaises(ValueError):plan_properties([],ops)
        with self.assertRaisesRegex(ValueError,'ambiguous'):
            plan_properties([{'id':'x'},{'id':'x'}],[{}])
        self.assertFalse(cs2_edit_preview('[]','0'*64)['ok'])
        self.assertFalse(cs2_edit_preview('[{}]','bad')['ok'])
        self.assertEqual(plan_properties([],[{'entity_id':'x','property':'p','expected':None,'value':'x'}])[0]['status'],'invalid')
