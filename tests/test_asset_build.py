"""Reject stale/empty outputs and bind fresh asset evidence to inputs."""
from pathlib import Path
import struct,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mcp_server'))
from hammer_mcp.asset_build import cs2_asset_compile

class AssetBuildTests(unittest.TestCase):
    def fixture(self,root):
        compiler=root/'game/bin/win64/resourcecompiler.exe'
        compiler.parent.mkdir(parents=True);compiler.write_bytes(b'compiler')
        source=root/'content/csgo_addons/test/models/sample.vmdl'
        source.parent.mkdir(parents=True);source.write_text('source')
        compiled=root/'game/csgo_addons/test/models/sample.vmdl_c'
        compiled.parent.mkdir(parents=True);compiled.write_bytes(b'old original')
        return source,compiled

    def resource(self):
        return struct.pack('<IHHII',29,12,0,8,1)+struct.pack('<4sII',b'DATA',8,1)+b'x'

    def test_preview_and_fresh_compile_never_replace_original(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source,original=self.fixture(root)
            def compile(command,compiler,folder,record):
                Path(record['output']).write_bytes(self.resource())
                record['process_tree_exited']=True
                return 0
            with patch('hammer_mcp.asset_build.tempfile.gettempdir',return_value=temporary),patch(
                    'hammer_mcp.asset_build._compile',side_effect=compile) as run,patch(
                    'hammer_mcp.asset_build.inspect_inputs',return_value={'declared_inputs_match':True,
                        'special_input_count':0,'special_dependency_count':0,'coverage_complete':False,
                        'evidence_path':'fixture','inputs':[]}):
                self.assertTrue(cs2_asset_compile(str(source))['preview']);run.assert_not_called()
                result=cs2_asset_compile(str(source),True)
                self.assertTrue(result['ok']);self.assertNotEqual(result['output'],str(original))
                self.assertEqual(original.read_bytes(),b'old original')
                self.assertEqual(result['resource_blocks'],['DATA'])
                self.assertTrue(Path(result['record_path']).is_file())

    def test_zero_exit_valid_resource_still_fails_on_dependency_mismatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            source,original=self.fixture(Path(temporary))
            def compile(command,compiler,folder,record):
                Path(record['output']).write_bytes(self.resource());return 0
            with patch('hammer_mcp.asset_build.tempfile.gettempdir',return_value=temporary),patch(
                    'hammer_mcp.asset_build._compile',side_effect=compile),patch(
                    'hammer_mcp.asset_build.inspect_inputs',return_value={'declared_inputs_match':False,
                        'special_input_count':0,'special_dependency_count':0,'coverage_complete':False,
                        'evidence_path':'fixture','inputs':[]}):
                result=cs2_asset_compile(str(source),True)
            self.assertFalse(result['ok']);self.assertEqual(result['exit_code'],0)
            self.assertFalse(result['input_dependency_validation']['declared_inputs_match'])
            self.assertEqual(original.read_bytes(),b'old original')

    def test_stale_original_empty_and_malformed_fresh_outputs_rejected(self):
        for payload in (None,b'',b'bad'):
            with self.subTest(payload=payload),tempfile.TemporaryDirectory() as temporary:
                source,original=self.fixture(Path(temporary))
                def compile(command,compiler,folder,record):
                    if payload is not None:Path(record['output']).write_bytes(payload)
                    return 0
                with patch('hammer_mcp.asset_build.tempfile.gettempdir',return_value=temporary),patch(
                        'hammer_mcp.asset_build._compile',side_effect=compile):
                    result=cs2_asset_compile(str(source),True)
                self.assertFalse(result['ok']);self.assertEqual(result['status'],'failed')
                self.assertEqual(original.read_bytes(),b'old original')

    def test_source_change_during_compile_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            source,_=self.fixture(Path(temporary))
            def compile(command,compiler,folder,record):
                Path(record['output']).write_bytes(self.resource());source.write_text('changed');return 0
            with patch('hammer_mcp.asset_build.tempfile.gettempdir',return_value=temporary),patch(
                    'hammer_mcp.asset_build._compile',side_effect=compile):
                result=cs2_asset_compile(str(source),True)
            self.assertFalse(result['ok']);self.assertIn('changed',result['error'])

    def test_outside_addon_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            source=Path(temporary)/'sample.vmdl';source.touch()
            with patch('hammer_mcp.asset_build._compile') as run:
                self.assertFalse(cs2_asset_compile(str(source),True)['ok']);run.assert_not_called()
