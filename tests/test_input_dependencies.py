from pathlib import Path
import sys,unittest,tempfile,zlib
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mcp_server'))
from hammer_mcp.input_dependencies import parse_inputs,inspect_inputs


class InputDependencyTests(unittest.TestCase):
    def test_input_crc_is_checked_not_merely_trusted_from_dump(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);tool=root/'game/bin/win64/resourceinfo.exe';tool.parent.mkdir(parents=True);tool.write_bytes(b'fixture')
            resource=root/'game/csgo_addons/private/materials/example.vmat_c';resource.parent.mkdir(parents=True);resource.write_bytes(b'fixture')
            source=root/'content/csgo_addons/private/materials/example.vmat';source.parent.mkdir(parents=True);source.write_bytes(b'original')
            crc=zlib.crc32(b'original')&0xffffffff
            def native(*args,**kwargs):
                kwargs['stdout'].write(self.text(crc=str(crc)).encode());return SimpleNamespace(returncode=0)
            with patch('hammer_mcp.input_dependencies.subprocess.run',side_effect=native):
                self.assertTrue(inspect_inputs(resource,root,root/'evidence')['declared_inputs_match'])
                source.write_bytes(b'changed')
                result=inspect_inputs(resource,root,root/'evidence')
                self.assertFalse(result['declared_inputs_match'])
                self.assertEqual(result['inputs'][0]['status'],'input_crc_or_existence_changed')

    def text(self,name='materials/example.vmat',search='csgo_addons/private',flags='false',crc='26'):
        return '''--- RED2 Block (CResourceEditInfo) ---
        { m_InputDependencies = [{ m_RelativeFilename = "'''+name+'''"
          m_SearchPath = "'''+search+'''" m_nFileCRC = '''+crc+'''
          m_bOptional = '''+flags+''' m_bFileExists = true m_bIsGameFile = false }]
          m_AdditionalInputDependencies = [] m_SpecialInputDependencies = [] m_SpecialDependencies = [] }
        '''

    def test_native_metadata_typed_flags_and_search_path(self):
        rows,meta=parse_inputs(self.text())
        self.assertEqual(rows[0]['search_path'],'csgo_addons/private')
        self.assertEqual(rows[0]['crc32'],26);self.assertFalse(rows[0]['is_game_file'])
        self.assertEqual(meta['special_input_count'],0)

    def test_unknown_cli_output_or_partial_metadata_is_not_empty_success(self):
        for text in ('Unknown KVType 26','--- RED2 Block (CResourceEditInfo) --- {}',self.text()+' exception'):
            with self.assertRaises((ValueError,KeyError)):parse_inputs(text)

    def test_path_escape_types_and_duplicate_keys_fail_closed(self):
        for text in (self.text(name='../escape'),self.text(search='C:/escape'),
                     self.text(flags='0'),self.text(crc='-1'),
                     self.text().replace('m_nFileCRC = 26','m_nFileCRC = 26 m_nFileCRC = 27')):
            with self.assertRaises(ValueError):parse_inputs(text)
