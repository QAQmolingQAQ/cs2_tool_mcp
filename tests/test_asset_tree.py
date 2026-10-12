import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp_server"))
from hammer_mcp.asset_tree import cs2_asset_tree


class AssetTreeTests(unittest.TestCase):
    def test_particle_functions_children_and_resource_refs(self):
        source = '''<!-- kv3 encoding:text:version{x} format:vpcf66:version{x} -->
        { _class = "CParticleSystemDefinition"
          m_Operators = [ { _class = "C_OP_Remap" m_flScale = 2.5 } ]
          m_Children = [ { m_ChildRef = resource:"particles/a.vpcf" } ] }
        '''
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "sample.vpcf"
            file.write_text(source, encoding="utf-8")
            result = cs2_asset_tree(str(file), depth=2)
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["nodes"][0]["children"],
                             {"m_Operators": 1, "m_Children": 1})
            operator = cs2_asset_tree(str(file), "m_Operators[0]", depth=0)
            self.assertEqual(operator["nodes"][0]["fields"]["m_flScale"], 2.5)
            child = cs2_asset_tree(str(file), "m_Children[0]", depth=0)
            self.assertEqual(child["nodes"][0]["fields"]["m_ChildRef"],
                             {"type": "resource", "value": "particles/a.vpcf"})

    def test_modeldoc_nested_nodes_and_bad_input(self):
        source = '''<!-- kv3 encoding:text:version{x} format:modeldoc36:version{x} -->
        { rootNode = { _class = "RootNode" children = [
          { _class = "RenderMeshFile" name = "test" position = [ 1.0, 2.0, 3.0 ] }
        ] } }'''
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "sample.vmdl"
            file.write_text(source, encoding="utf-8")
            result = cs2_asset_tree(str(file), "rootNode.children[0]", depth=0)
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["nodes"][0]["fields"]["position"], [1.0, 2.0, 3.0])
            self.assertFalse(cs2_asset_tree(str(file), "rootNode.children[2]")["ok"])
            file.write_text(source[:-3], encoding="utf-8")
            self.assertFalse(cs2_asset_tree(str(file))["ok"])


if __name__ == "__main__":
    unittest.main()
