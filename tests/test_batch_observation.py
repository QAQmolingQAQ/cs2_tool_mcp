from pathlib import Path
import sys,unittest,json,tempfile
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mcp_server'))
from hammer_mcp import batch_observation as bo


class BatchObservationTests(unittest.TestCase):
    def test_changed_project_scope_does_not_inspect_live_entity_addresses(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);identifier='a'*32
            directory=root/'batch_probe_runs';directory.mkdir()
            context={'profile':'old','source':{'path':str(root/'old.vmap')},'config':{'sha256':'b'*64}}
            record={'id':identifier,'status':'verified','before':{'entities':[{'id':'one'}]},
                    'results':[{'index':0,'status':'verified_modified','history_before_selection':{'context':context}}]}
            (directory/(identifier+'.json')).write_text(json.dumps(record))
            project={'state_root':temporary,'profile':'new','source':str(root/'new.vmap'),'config_sha256':'c'*64}
            with patch.object(bo,'load_project',return_value=project),patch.object(bo,'read_committed_batch') as memory:
                result=bo.observe_batch('config',identifier)
                self.assertFalse(result['project_scope_matches']);self.assertFalse(result['current_memory_available'])
                memory.assert_not_called()

    def test_process_identity_distinguishes_live_exited_and_reused_pid(self):
        record={'producer':{'pid':123,'created':'456'}}
        for current,expected in (('456','running'),(None,'exited'),('789','pid_reused')):
            with patch.object(bo,'process_identity',return_value=current):
                self.assertEqual(bo.writer_state(record),expected)
        self.assertEqual(bo.writer_state({}),'not_recorded')
        with patch.object(bo,'process_identity',side_effect=OSError('access denied')):
            with self.assertRaises(OSError):bo.writer_state(record)

    def test_unknown_dispatch_is_never_reclassified_as_safe_to_retry(self):
        record={'status':'preparing','results':[{'index':0,'status':'verified_modified'},
            {'index':1,'status':'property_dispatching_unknown_do_not_replay'}]}
        for writer in ('running','exited','pid_reused','not_recorded','unknown'):
            result=bo.classify(record,writer)
            self.assertEqual(result['verified_modified_count'],1)
            self.assertEqual(result['unknown_dispatch_indexes'],[1])
            self.assertFalse(result['replay_allowed']);self.assertFalse(result['recovery_authorized'])
            self.assertFalse(result['attribution_verified'])
            self.assertEqual(result['observation_state'],'in_progress' if writer=='running' else 'stopped_or_unobserved_unknown')

    def test_terminal_error_retains_unknown_item_and_invalid_rows_rejected(self):
        result=bo.classify({'status':'stopped_error_do_not_replay','results':[
            {'index':0,'status':'selection_dispatching'}]},'exited')
        self.assertEqual(result['unknown_dispatch_indexes'],[0]);self.assertEqual(result['observation_state'],'recorded_terminal')
        with self.assertRaises(ValueError):bo.classify({'status':'verified','results':[
            {'index':4,'status':'verified_modified'}]},'exited')
