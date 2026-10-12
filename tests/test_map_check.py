import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp_server"))
from hammer_mcp import maps
from hammer_mcp import offsets
from hammer_mcp import scene


class MapCheckTests(unittest.TestCase):
    def test_reports_missing_geometry_empty_mesh_and_duplicate_name(self):
        base = 0x100000
        entities = (0x200000, 0x210000)
        mesh = 0x300000
        scene = [(entities[0], base + offsets.RVA_CMAPENTITY_VTABLE),
                 (entities[1], base + offsets.RVA_CMAPENTITY_VTABLE),
                 (mesh, base + offsets.RVA_CMAPMESH_VTABLE)]

        def read_int(address, kind):
            if address == 0x1000 + offsets.CMAPDOC_WORLD_OFFSET:
                return 0x1800
            if address == 0x400000 + offsets.POLY_OFF_VPOOL_CNT:
                return 8
            if address == 0x400000 + offsets.POLY_OFF_FPOOL_CNT:
                return 0
            raise AssertionError(hex(address))

        with patch.object(maps, "_map_doc", return_value=0x1000), \
             patch.object(maps, "_read_int", side_effect=read_int), \
             patch.object(maps, "_dm_table", return_value=([], 0)), \
             patch.object(maps, "_hammer_base", return_value=base), \
             patch.object(maps, "_walk_elements", return_value=scene), \
             patch.object(maps, "_entity_get_attrs", side_effect=[
                 {"classname": "func_button", "name": "door"},
                 {"classname": "info_target", "name": "door"}]), \
             patch.object(maps, "_read_vec3", return_value=(0.0, 0.0, 0.0)), \
             patch.object(maps, "_entity_meshes", return_value=[]), \
             patch.object(maps, "_poly_ready", return_value=0x400000):
            result = maps.cs2_map_check("0")

        self.assertTrue(result["ok"])
        self.assertEqual(result["counts"], {"elements": 3, "entities": 2, "meshes": 1})
        self.assertEqual({x["code"] for x in result["issues"]},
                         {"missing_brush_mesh", "empty_mesh", "duplicate_targetname"})
        self.assertEqual(result["issue_count"], 3)

    def test_read_failure_is_not_reported_as_clean_map(self):
        with patch.object(maps, "_map_doc", side_effect=RuntimeError("disconnected")):
            result = maps.cs2_map_check()
        self.assertFalse(result["ok"])
        self.assertIn("disconnected", result["error"])

    def test_strict_scene_walk_propagates_unreadable_node(self):
        with patch.object(scene, "_read_bytes", side_effect=OSError("bad node")):
            with self.assertRaisesRegex(OSError, "bad node"):
                list(scene._walk_elements(0x1000, [], 0, strict=True))


if __name__ == "__main__":
    unittest.main()
