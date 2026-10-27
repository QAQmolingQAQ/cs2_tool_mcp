import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('batch_probe',Path(__file__).resolve().parents[1]/
                                           'scripts/hammer_batch_targetname_probe.py')
probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)


class BatchProbeTests(unittest.TestCase):
    def fixture(self):
        root=Path('content/csgo_addons/test').resolve()
        project={'source_root':str(root),'source':str(root/'maps/__mcp_edit_tests'/('a'*32)/'map.vmap'),
                 'release':False,'addon':'test'}
        plan={'plan_valid':True,'source_basis':'live_class_property_storage',
              'operations':[{'entity_id':'one','property':'targetname','expected':'','value':'mcp_probe_one'}]}
        return project,plan

    def test_only_owned_test_document_and_probe_names_allowed(self):
        project,plan=self.fixture();self.assertEqual(len(probe.validate(project,plan)),1)
        for change in ({'release':True},{'addon':'other'},{'source':str(Path(project['source_root'])/'maps/real.vmap')}):
            with self.assertRaises(ValueError):probe.validate({**project,**change},plan)
        for key,value in (('expected','user_original'),('value','ordinary_name'),('property','classname')):
            altered={**plan,'operations':[{**plan['operations'][0],key:value}]}
            with self.assertRaises(ValueError):probe.validate(project,altered)

    def test_rejects_saved_invalid_oversized_and_duplicate_batches(self):
        project,plan=self.fixture()
        for change in ({'plan_valid':False},{'source_basis':'saved_disk_snapshot_not_unsaved_editor'},
                       {'operations':[]},{'operations':plan['operations']*17},
                       {'operations':plan['operations']*2}):
            with self.assertRaises(ValueError):probe.validate(project,{**plan,**change})
