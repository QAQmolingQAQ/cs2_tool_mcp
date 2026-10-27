from pathlib import Path
import sys
import unittest
import json,tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'mcp_server'))
from hammer_mcp.edit_preview import plan_properties, cs2_edit_preview
from hammer_mcp import edit_preview as ep


class PreviewTests(unittest.TestCase):
    def test_durable_plan_recheck_reports_context_changes_without_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);identifier='a'*32
            folder=root/'edit_plans'/identifier;folder.mkdir(parents=True)
            plan={'version':1,'id':identifier,'results':[{'index':0,'status':'planned','executed':False}],
                  'plan_valid':True,'source_sha256':'b'*64,'preflight_after':'c'*32}
            plan['plan_sha256']=ep._plan_hash(plan)
            path=folder/'report.json';path.write_text(json.dumps(plan))
            with patch.object(ep,'load_project',return_value={'state_root':str(root)}),patch.object(
                    ep,'cs2_edit_preflight',return_value={'ok':True,'conflicts':[],
                        'blockers':['dirty_semantics_unverified'],'id':'d'*32}) as preflight:
                result=ep.cs2_edit_plan_recheck(identifier,plan['plan_sha256'])
                self.assertTrue(result['plan_current']);self.assertFalse(result['safe_to_write'])
                self.assertEqual(result['results'][0]['recheck_status'],'unchanged')
                preflight.assert_called_with('','','c'*32,'b'*64)
                preflight.return_value['conflicts']=['layout_changed','source_changed']
                stale=ep.cs2_edit_plan_recheck(identifier,plan['plan_sha256'])
                self.assertFalse(stale['plan_current']);self.assertEqual(stale['executed_count'],0)
                self.assertEqual(stale['results'][0]['recheck_status'],'stale_or_invalid')
                self.assertEqual(len(list((root/'edit_plan_rechecks').glob('*.json'))),2)
                plan['results'][0]['status']='no_change';path.write_text(json.dumps(plan))
                preflight.reset_mock()
                self.assertFalse(ep.cs2_edit_plan_recheck(identifier,plan['plan_sha256'])['ok'])
                preflight.assert_not_called()

    def test_plan_recheck_bounds_before_disk_access(self):
        with patch.object(ep,'load_project') as project:
            for identifier,digest in (('../bad','a'*64),('a'*32,'bad')):
                self.assertFalse(ep.cs2_edit_plan_recheck(identifier,digest)['ok'])
            project.assert_not_called()

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
            plan_properties([{'id':'x','properties':{}},{'id':'x','properties':{}}],[{}])
        self.assertFalse(cs2_edit_preview('[]','0'*64)['ok'])
        self.assertFalse(cs2_edit_preview('[{}]','bad')['ok'])
        self.assertEqual(plan_properties([],[{'entity_id':'x','property':'p','expected':None,'value':'x'}])[0]['status'],'invalid')

    def test_native_property_case_matches_without_ambiguous_keys(self):
        operation={'entity_id':'x','property':'startdisabled','expected':'0','value':'1'}
        self.assertEqual(plan_properties([{'id':'x','properties':{'StartDisabled':'0'}}],[operation])[0]['status'],'planned')
        with self.assertRaisesRegex(ValueError,'ambiguous property key'):
            plan_properties([{'id':'x','properties':{'StartDisabled':'0','startdisabled':'1'}}],[operation])
