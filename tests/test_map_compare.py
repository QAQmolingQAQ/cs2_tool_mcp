from pathlib import Path
import sys
import unittest
import tempfile
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mcp_server'))
from hammer_mcp.map_compare import compare_map_text, cs2_map_snapshot_compare

HEADER='<!-- dmx encoding keyvalues2 4 format vmap 40 -->\n'
TEXT='''"CMapEntity" { "id" "elementid" "entity" "nodeID" "int" "1"
 "origin" "vector3" "1 2 3" "mesh" "element" "mesh"
 "children" "element_array" [ "element" "child" ] }
 "Mesh" { "id" "elementid" "mesh" "vertices" "vector3_array" [ "0 0 0" "1 0 0" ] }
 "CMapEntity" { "id" "elementid" "child" "nodeID" "int" "2" "idvalue" "string" "game-id" }
'''

class CompareTests(unittest.TestCase):
    def test_storage_guids_can_change_but_references_are_resolved(self):
        renamed=TEXT.replace('"entity"','"newentity"').replace('"mesh"','"newmesh"').replace('"child"','"newchild"')
        r=compare_map_text(HEADER+TEXT,HEADER+renamed)
        # Renaming the attribute itself is not storage-GUID normalization.
        self.assertFalse(r['node_content_equal'])
        renamed=TEXT.replace('"entity"','"newentity"').replace('"elementid" "mesh"','"elementid" "newmesh"').replace('"element" "mesh"','"element" "newmesh"')
        self.assertTrue(compare_map_text(HEADER+TEXT,HEADER+renamed)['node_content_equal'])
    def test_geometry_transform_and_reference_changes_are_not_hidden(self):
        for old,new in [('1 2 3','1 2 4'),('1 0 0','2 0 0'),('game-id','other')]:
            self.assertFalse(compare_map_text(HEADER+TEXT,HEADER+TEXT.replace(old,new))['node_content_equal'])
        with self.assertRaisesRegex(ValueError,'unresolved'):
            compare_map_text(HEADER+TEXT,HEADER+TEXT.replace('"element" "mesh"','"element" "missing"'))
    def test_duplicate_node_and_cycle_fail_closed(self):
        with self.assertRaisesRegex(ValueError,'duplicate nodeID'):
            compare_map_text(HEADER+TEXT,HEADER+TEXT.replace('"int" "2"','"int" "1"'))
        cyclic=TEXT.replace('"vertices" "vector3_array" [ "0 0 0" "1 0 0" ]','"cycle" "element" "mesh"')
        with self.assertRaisesRegex(ValueError,'cyclic'):
            compare_map_text(HEADER+TEXT,HEADER+cyclic)
    def test_child_order_and_types_remain_significant(self):
        text=TEXT.replace('[ "element" "child" ]','[ "element" "child" "element" "entity" ]')
        reordered=text.replace('[ "element" "child" "element" "entity" ]','[ "element" "entity" "element" "child" ]')
        self.assertFalse(compare_map_text(HEADER+text,HEADER+reordered)['node_content_equal'])
        self.assertFalse(compare_map_text(HEADER+TEXT,HEADER+TEXT.replace('"origin" "vector3"','"origin" "string"'))['node_content_equal'])
    def test_cached_scope_and_file_readback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);before=root/'before.kv2';after=root/'after.kv2'
            before.write_text(HEADER+TEXT);after.write_text(HEADER+TEXT)
            with patch('hammer_mcp.map_compare.load_project',return_value={'state_root':str(root)}):
                result=cs2_map_snapshot_compare(str(before),str(after))
                self.assertTrue(result['ok']);self.assertTrue(result['node_content_equal'])
                self.assertFalse(result['full_rollback_verified']);self.assertFalse(result['safe_to_write'])
                self.assertFalse(cs2_map_snapshot_compare(str(root.parent/'outside.kv2'),str(after))['ok'])
                self.assertEqual(before.read_text(),HEADER+TEXT)
