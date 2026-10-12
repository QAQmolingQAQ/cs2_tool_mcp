import unittest
from unittest.mock import patch
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp_server"))
from hammer_mcp import automation as S
from hammer_mcp.results import EditResult
from hammer_mcp import meshes

class BrushAutomationTests(unittest.TestCase):
    def test_preflight_without_connection(self):
        with patch.object(S, '_map_doc', side_effect=AssertionError('must not connect')):
            self.assertTrue(S.cs2_entity_create_brush(dry_run=True)['ok'])
            for size in ('0', '-1', 'nan', 'inf', '1 2'):
                self.assertFalse(S.cs2_entity_create_brush(size=size, dry_run=True)['ok'])

    def test_success_and_partial_failure(self):
        with patch.object(S, '_map_doc', return_value=1), patch.object(S, 'create_entity', return_value=EditResult(True, 'arbitrary entity report', 0x100)), patch.object(S, 'create_box', return_value=EditResult(True, 'arbitrary mesh report', 0x200)), patch.object(S, '_element_doc_strict', return_value=1), patch.object(S, '_entity_get_attrs', return_value={'classname': 'func_brush'}) as attrs, patch.object(S, '_poly_ready', return_value=123), patch.object(S, 'attach_mesh', return_value=EditResult(True, 'OK', 0x200)) as attach, patch.object(S, '_dm_table', return_value=([], 0)), patch.object(S, '_entity_meshes', return_value=[0x200]):
            self.assertTrue(S.cs2_entity_create_brush()['ok'])
            attrs.assert_called_with(0x100, ['classname'])
            attach.return_value = EditResult(False, 'failed', 0x200)
            result = S.cs2_entity_create_brush()
            self.assertFalse(result['ok'])
            self.assertEqual(result['stage'], 'attach_mesh')
            self.assertEqual(result['mesh'], '0x200')

    def test_failed_mesh_keeps_addresses_and_stops_before_attach(self):
        with patch.object(S, '_map_doc', return_value=7), \
             patch.object(S, 'create_entity', return_value=EditResult(True, 'entity', 0x100)) as create, \
             patch.object(S, 'create_box', return_value=EditResult(False, 'geometry unavailable', 0x200)) as box, \
             patch.object(S, '_element_doc_strict', return_value=7), \
             patch.object(S, '_entity_get_attrs', return_value={'classname': 'func_brush'}), \
             patch.object(S, 'attach_mesh') as attach:
            result = S.cs2_entity_create_brush(doc='specific-map')
            self.assertFalse(result['ok'])
            self.assertEqual(result['stage'], 'create_mesh')
            self.assertEqual((result['entity'], result['mesh']), ('0x100', '0x200'))
            self.assertEqual(create.call_args.kwargs['document'], 7)
            self.assertEqual(box.call_args.kwargs['document'], 7)
            attach.assert_not_called()

    def test_partial_mesh_result_preserves_allocated_address(self):
        with patch.object(meshes, '_hammer_base', return_value=0x180000000), \
             patch.object(meshes, '_read_int', return_value=0x500), \
             patch.object(meshes, '_call_fn', return_value=('0x1', '')), \
             patch.object(meshes, '_resolve_handle', return_value=0x200), \
             patch.object(meshes, '_poly_ready', return_value=0):
            result = meshes.create_box(document=7)
            self.assertFalse(result.ok)
            self.assertEqual(result.element, 0x200)

if __name__ == '__main__':
    unittest.main()
