"""History uncertainty must stop content mutations and document fallbacks."""
from contextlib import ExitStack
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mcp_server'))
from hammer_mcp import entities, entity_io, history, scene


class EditHistoryFailureTests(unittest.TestCase):
    def test_all_history_calls_propagate_dispatch_error(self):
        calls=[lambda:history._hist_push_step(1,'step'),
               lambda:history._hist_record_object(1,2,True),
               lambda:history._hist_record_object(1,2,False),
               lambda:history._hist_record_node(1,2),
               lambda:history._hist_notify(1)]
        for index,call in enumerate(calls):
            with self.subTest(call=call), patch.object(history,'_call_fn',return_value=('', 'running_timeout_unknown')), patch.object(history,'_read_int',return_value=2) as read:
                with self.assertRaisesRegex(RuntimeError,'do not retry'):call()
                self.assertEqual(read.call_count,1 if index==0 else 0)

    def test_native_return_without_verified_new_step_is_not_success(self):
        for after in (4,3,6):
            with self.subTest(after=after), patch.object(history,'_call_fn',return_value=('0x0','')), patch.object(history,'_read_int',side_effect=[4,after]):
                with self.assertRaisesRegex(RuntimeError,'not verified'):history._hist_push_step(1,'step')
        with patch.object(history,'_call_fn',return_value=('0x0','')), patch.object(history,'_read_int',side_effect=[4,5]):
            self.assertEqual(history._hist_push_step(1,'step'),5)

    def test_invalid_initial_history_count_stops_native_call(self):
        with patch.object(history,'_call_fn') as native, patch.object(history,'_read_int',return_value=1000001):
            with self.assertRaisesRegex(RuntimeError,'not executed'):history._hist_push_step(1,'step')
            native.assert_not_called()

    def prepare(self, stack, module, failure):
        for name,value in {'_parse_addr':0x10000,'_read_int':1,'_entity_class_props':0x20000,
                           '_dm_find_attr':0x30000,'_dm_attr_value':'before','_undo_manager_addr':0x40000,
                           '_doc_of_element':0x50000,'_find_map_histories':(0x60000,0x70000),
                           '_hist_push_step':1,'_hist_record_node':None,'_hist_notify':None,
                           '_hist_state':'prepared','_plausible_ptr':True,'_native_conns':[{}]}.items():
            if hasattr(module,name):stack.enter_context(patch.object(module,name,return_value=value))
        stack.enter_context(patch.object(module,failure,side_effect=RuntimeError('preparation unknown')))

    def test_each_property_history_stage_failure_stops_setter(self):
        for stage in ('_doc_of_element','_find_map_histories','_hist_push_step','_hist_record_node','_hist_notify'):
            with self.subTest(stage=stage), ExitStack() as stack:
                self.prepare(stack,entities,stage)
                pipe=stack.enter_context(patch.object(entities,'_get_pipe'))
                scope=stack.enter_context(patch.object(entities,'_undo_scope_begin'))
                result=entities.cs2_entity_set_attr('0x10000','targetname','after')
                self.assertTrue(result.startswith('ERROR'),result)
                pipe.assert_not_called();scope.assert_not_called()

    def test_io_history_failure_stops_allocation_add_and_remove(self):
        for stage in ('_doc_of_element','_hist_push_step','_hist_record_node','_hist_notify'):
            with self.subTest(stage=stage), ExitStack() as stack:
                self.prepare(stack,entity_io,stage)
                scratch=stack.enter_context(patch.object(entity_io,'_conn_scratch'))
                native=stack.enter_context(patch.object(entity_io,'_call_fn'))
                add=entity_io.cs2_entity_add_io('0x10000','OnUser1','x','Trigger')
                remove=entity_io.cs2_entity_remove_io('0x10000',0)
                self.assertTrue(add.startswith('ERROR'),add)
                self.assertTrue(remove.startswith('ERROR'),remove)
                scratch.assert_not_called();native.assert_not_called()

    def test_ownership_unknown_cycle_error_and_ambiguity_never_fallback(self):
        for parents,docs,worlds in [
            ([('0x0','')],[],[]),
            ([('0x10000','')],[],[]),
            ([('', 'query failed')],[],[]),
            ([('0x20000',''),('0x0','')],[{'address':'0x30000'},{'address':'0x40000'}],[0x20000,0x20000])]:
            with self.subTest(parents=parents,docs=docs), patch.object(scene,'_call_fn',side_effect=parents), patch.object(scene,'_get_pipe',return_value=Mock(call=Mock(return_value={'result':{'docs':docs}}))), patch.object(scene,'_read_int',side_effect=worlds), patch.object(scene,'_map_doc') as fallback:
                with self.assertRaises(RuntimeError):scene._doc_of_element(0x10000)
                fallback.assert_not_called()

    def test_ownership_resolves_matching_document_not_first(self):
        docs=[{'address':'0x30000'},{'address':'0x40000'}]
        with patch.object(scene,'_call_fn',side_effect=[('0x20000',''),('0x0','')]), patch.object(scene,'_get_pipe',return_value=Mock(call=Mock(return_value={'result':{'docs':docs}}))), patch.object(scene,'_read_int',side_effect=[0x99999,0x20000]):
            self.assertEqual(scene._doc_of_element(0x10000),0x40000)
