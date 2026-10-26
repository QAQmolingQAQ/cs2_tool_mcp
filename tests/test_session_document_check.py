import json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mcp_server'))
from hammer_mcp.session_check import cs2_session_selfcheck

class DocumentSelfcheckTests(unittest.TestCase):
    def run_check(self,documents,count,error=None):
        with tempfile.TemporaryDirectory() as temp:
            config=Path(temp)/'project.json';config.write_text(json.dumps({'game_root':temp,'active_profile':'test','profiles':{'test':{'map':'maps/configured.vmap','addon':'test'}}}))
            live={'writes_enabled':False,'allowed_methods':[],'bridge':{'addon':'test'},'live':{'modules':{'hammer.dll':{}}}}
            with patch('hammer_mcp.session_check.WATCHED',set()),patch('hammer_mcp.session_check.steam_version',return_value={}),patch('hammer_mcp.session_check.inspect_live',return_value=live),patch('hammer_mcp.session_check.get_session',return_value=SimpleNamespace(pipe=object())),patch('hammer_mcp.hammer_layout.observe_live_layout',side_effect=error,return_value={'sessions':documents,'session_count_candidate':count}):
                return cs2_session_selfcheck(str(config))
    def test_current_document_differs_from_config_without_enabling_writes(self):
        r=self.run_check([{'document_path':'C:/actual.vmap'}],1)
        self.assertEqual(r['current_map'],'C:/actual.vmap')
        self.assertEqual(r['configured_project']['map'],'maps/configured.vmap')
        self.assertFalse(r['writes_enabled']);self.assertEqual(r['hammer_dirty_state'],'unknown')
    def test_multiple_and_pathless_documents_do_not_guess_active(self):
        for docs in ([{'document_path':'A'},{'document_path':'B'}],[{'document_path':None}]):
            r=self.run_check(docs,len(docs));self.assertIsNone(r['current_map'])
            self.assertIn('unknown',r['current_map_status'])
    def test_layout_failure_does_not_misreport_disconnected(self):
        r=self.run_check([],0,ValueError('identity mismatch'))
        self.assertTrue(r['connected']);self.assertIsNone(r['current_map'])
        self.assertEqual(r['current_map_status'],'read_only_layout_unavailable')

if __name__=='__main__':unittest.main()
