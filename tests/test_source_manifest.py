from pathlib import Path
import sys,tempfile,unittest,stat
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mcp_server'))
from hammer_mcp.source_manifest import source_manifest,manifest_changes,copy_source_manifest,SourceCopyCancelled


class SourceManifestTests(unittest.TestCase):
    def test_copy_can_cancel_before_any_file_is_written(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'source';source.mkdir();(source/'logic.js').write_text('original')
            with self.assertRaises(SourceCopyCancelled):
                copy_source_manifest(source_manifest(source),root/'private',lambda:True)
            self.assertEqual(list((root/'private').iterdir()),[])
            self.assertEqual((source/'logic.js').read_text(),'original')

    def test_private_copy_preserves_content_when_original_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'source';source.mkdir()
            (source/'logic.js').write_text('original')
            baseline=source_manifest(source);destination=root/'private'
            copied=copy_source_manifest(baseline,destination)
            try:
                self.assertEqual(copied['files']['logic.js']['sha256'],baseline['files']['logic.js']['sha256'])
                (source/'logic.js').write_text('changed')
                self.assertEqual((destination/'logic.js').read_text(),'original')
            finally:(destination/'logic.js').chmod(stat.S_IWRITE|stat.S_IREAD)

    def test_copy_rejects_stale_input_nested_destination_and_traversal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'source';source.mkdir();file=source/'logic.js';file.write_text('before')
            baseline=source_manifest(source)
            with self.assertRaises(ValueError):copy_source_manifest(baseline,source/'nested')
            file.write_text('after')
            with self.assertRaisesRegex(ValueError,'changed before'):copy_source_manifest(baseline,root/'stale')
            baseline=source_manifest(source);baseline['files']['../escape.js']=baseline['files'].pop('logic.js')
            with self.assertRaisesRegex(ValueError,'relative path'):copy_source_manifest(baseline,root/'escape')
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
