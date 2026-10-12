import importlib.util
import struct
import unittest
from pathlib import Path
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'mcp_server'))
from hammer_mcp import scene as S, maps
from hammer_mcp import offsets as C


class MeshOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.base = 0x180000000
        self.ent = 0x10000
        self.mesh = 0x20000
        self.group = 0x30000
        self.nested = 0x40000
        self.other = 0x50000
        self.mem = {}
        self.table = [0, self.ent, self.mesh, self.group, self.nested, self.other]
        self.add(self.ent, C.RVA_CMAPENTITY_VTABLE, [3, 4])
        self.add(self.group, 0x1111, [2])
        self.add(self.mesh, C.RVA_CMAPMESH_VTABLE, [])
        self.add(self.nested, C.RVA_CMAPENTITY_VTABLE, [5])
        self.add(self.other, C.RVA_CMAPMESH_VTABLE, [])
        self.patches = [patch.object(S, '_hammer_base', return_value=self.base),
                        patch.object(S, '_read_bytes', side_effect=lambda addr, n: self.mem[addr][:n])]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def add(self, addr, rva, children):
        raw = bytearray(C.NODE_OFF_CHILD_HANDLES + 8)
        struct.pack_into('<Q', raw, 0, self.base + rva)
        struct.pack_into('<I', raw, C.NODE_OFF_CHILD_COUNT, len(children))
        struct.pack_into('<Q', raw, C.NODE_OFF_CHILD_HANDLES, addr + 0x1000 if children else 0)
        self.mem[addr] = bytes(raw)
        self.mem[addr + 0x1000] = struct.pack(f'<{len(children)}I', *children)

    def test_groups_and_nested_entity_ownership(self):
        self.assertEqual(S._entity_meshes(self.ent, self.table, len(self.table)), [self.mesh])

    def test_empty_is_distinct_from_unreadable(self):
        self.add(self.ent, C.RVA_CMAPENTITY_VTABLE, [])
        self.assertEqual(S._entity_meshes(self.ent, self.table, len(self.table)), [])
        del self.mem[self.ent]
        with self.assertRaises(KeyError):
            S._entity_meshes(self.ent, self.table, len(self.table))

    def test_invalid_handle_and_cycle_fail(self):
        self.add(self.group, 0x1111, [99])
        with self.assertRaises(RuntimeError):
            S._entity_meshes(self.ent, self.table, len(self.table))
        self.add(self.group, 0x1111, [1])
        with self.assertRaises(RuntimeError):
            S._entity_meshes(self.ent, self.table, len(self.table))

    def query(self, meshes, classname='func_button', origin=(1000, 1000, 1000), box=(0, 0, 0, 32, 32, 32)):
        with patch.object(maps, '_hammer_base', return_value=self.base), \
             patch.object(maps, '_map_doc', return_value=0x60000), \
             patch.object(maps, '_read_int', return_value=0x70000), \
             patch.object(maps, '_dm_table', return_value=(self.table, len(self.table))), \
             patch.object(maps, '_walk_elements', return_value=[(self.ent, self.base + C.RVA_CMAPENTITY_VTABLE)]), \
             patch.object(maps, '_entity_meshes', return_value=meshes), \
             patch.object(maps, '_poly_ready', return_value=0x80000), \
             patch.object(maps, '_mesh_world_box', return_value=(box, 'test')), \
             patch.object(maps, '_read_vec3', return_value=origin), \
             patch.object(maps, '_entity_get_attrs', return_value={'classname': classname}):
            return maps.cs2_area_query(min='0 0 0', max='16 16 16', kinds='brush,trigger,point')

    def test_brush_mesh_hits_when_origin_is_outside(self):
        self.assertIn('func_button', self.query([self.mesh]))

    def test_brush_origin_inside_but_mesh_outside_does_not_hit(self):
        self.assertNotIn('func_button', self.query([self.mesh], origin=(8, 8, 8), box=(100,100,100,132,132,132)))

    def test_point_and_empty_brush_fallback(self):
        self.assertIn('info_player_start', self.query([], classname='info_player_start', origin=(8,8,8)))
        self.assertNotIn('func_button', self.query([]))

    def test_trigger_geometry_and_unknown_bounds(self):
        self.assertIn('trigger_multiple', self.query([self.mesh], classname='trigger_multiple'))
        self.assertTrue(self.query([self.mesh], box=None).startswith('ERROR'))

    def test_geometry_not_class_prefix_defines_brush(self):
        self.assertIn('[brush]', self.query([self.mesh], classname='custom_solid'))


if __name__ == '__main__':
    unittest.main()
