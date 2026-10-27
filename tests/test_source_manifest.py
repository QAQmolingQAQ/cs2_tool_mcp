from pathlib import Path
import sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mcp_server'))
from hammer_mcp.source_manifest import source_manifest,manifest_changes


class SourceManifestTests(unittest.TestCase):
    def test_add_remove_modify_and_owned_snapshot_exclusion(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);script=root/'script.js';script.write_text('before')
            material=root/'material.vmat';material.write_text('material')
            snapshot=root/'owned.vmap';before=source_manifest(root,[snapshot])
            snapshot.write_text('owned build input');self.assertEqual(manifest_changes(before,source_manifest(root,[snapshot])),
                {'added':[],'removed':[],'changed':[]})
            script.write_text('after');material.unlink();(root/'particle.vpcf').write_text('new')
            changes=manifest_changes(before,source_manifest(root,[snapshot]))
            self.assertEqual(changes,{'added':['particle.vpcf'],'removed':['material.vmat'],'changed':['script.js']})

    def test_manifest_rejects_wrong_root_comparison(self):
        with self.assertRaises(ValueError):manifest_changes({'root':'a','files':{}},{'root':'b','files':{}})
