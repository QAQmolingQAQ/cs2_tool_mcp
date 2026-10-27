from pathlib import Path
import json,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mcp_server'))
from hammer_mcp import edit_preview as ep


class LiveEditPreviewTests(unittest.TestCase):
    def test_live_value_conflict_and_noop_do_not_use_disk_converter(self):
        with tempfile.TemporaryDirectory() as temporary:
            guid='657b42df-8155-4005-9f33-8ff4072e6c70'
            project={'state_root':temporary,'source':str(Path(temporary)/'map.vmap'),
                     'profile':'test','config_sha256':'c'*64}
            observation={'ok':True,'id':'a'*32,'conflicts':[],'blockers':['dirty'],
                         'evidence':{'config':{'sha256':'c'*64},'source':{'path':project['source']},'profile':'test'}}
            live={'entities':[{'id':guid,'properties':{'targetname':'unsaved'}}]}
            with patch.object(ep,'load_project',return_value=project),patch.object(ep,'cs2_edit_preflight',return_value=observation),patch.object(
                    ep,'read_committed_batch',return_value=live),patch.object(ep.subprocess,'run') as converter:
                operation={'entity_id':guid,'property':'targetname','expected':'diskvalue','value':'new'}
                result=ep.cs2_edit_live_preview(json.dumps([operation]),'d'*64)
                self.assertEqual(result['results'][0]['status'],'conflict')
                self.assertEqual(result['results'][0]['before'],'unsaved');self.assertFalse(result['plan_valid'])
                operation.update(expected='unsaved',value='unsaved')
                result=ep.cs2_edit_live_preview(json.dumps([operation]),'d'*64)
                self.assertEqual(result['results'][0]['status'],'no_change');self.assertTrue(result['plan_valid'])
                converter.assert_not_called();self.assertFalse(result['safe_to_write'])

    def test_recheck_rereads_live_values_even_when_context_matches(self):
        with tempfile.TemporaryDirectory() as temporary:
            guid='657b42df-8155-4005-9f33-8ff4072e6c70'
            project={'state_root':temporary,'source':str(Path(temporary)/'map.vmap'),
                     'profile':'test','config_sha256':'c'*64}
            observation={'ok':True,'id':'a'*32,'conflicts':[],'blockers':['dirty'],
                         'evidence':{'config':{'sha256':'c'*64},'source':{'path':project['source']},'profile':'test'}}
            operation={'entity_id':guid,'property':'targetname','expected':'before','value':'after'}
            with patch.object(ep,'load_project',return_value=project),patch.object(ep,'cs2_edit_preflight',return_value=observation),patch.object(
                    ep,'read_committed_batch',side_effect=[{'entities':[{'id':guid,'properties':{'targetname':'before'}}]},
                        {'entities':[{'id':guid,'properties':{'targetname':'changed'}}]}]):
                plan=ep.cs2_edit_live_preview(json.dumps([operation]),'d'*64)
                result=ep.cs2_edit_plan_recheck(plan['id'],plan['plan_sha256'])
                self.assertFalse(result['plan_current']);self.assertIn('live_properties_changed',result['conflicts'])
                self.assertEqual(result['executed_count'],0)
