import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'mcp_server'))
from hammer_mcp import particle_editor_open, particle_editor_tree


class ParticleEditorLiveTests(unittest.TestCase):
    def test_native_open_preview_and_readback(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'content' / 'csgo_addons' / 'test' / 'particles' / 'sample.vpcf'
            source.parent.mkdir(parents=True)
            source.write_text('<!-- kv3 encoding:text:version{x} format:vpcf66:version{x} -->\n{}')
            session = Mock()
            session.pipe.call.return_value = {'result': {'main_thread_status': 0, 'ret': 0x1234}}
            with patch.object(particle_editor_open, 'get_session', return_value=session), \
                 patch.object(particle_editor_open, '_tool_module', return_value={'cls': 'CPetApp', 'tool_system': 0x2000}), \
                 patch.object(particle_editor_open, 'cs2_editor_document', return_value={
                     'ok': True, 'session': '0x1234', 'document': '0x3000', 'root': '0x4000'}):
                self.assertTrue(particle_editor_open.cs2_particle_editor_open(str(source))['preview'])
                session.pipe.call.assert_not_called()
                result = particle_editor_open.cs2_particle_editor_open(str(source), confirm=True)
                self.assertTrue(result['ok'])
                self.assertEqual(result['root'], '0x4000')
                self.assertEqual(session.pipe.call.call_args.args[1]['vtable_offset'], 144)

    def test_live_tree_validates_and_reads_function_name(self):
        reads = {0x4030: 1, 0x4038: 0x5000, 0x4040: 2, 0x5000: 0x6000}
        session = Mock()
        session.pipe.call.return_value = {'result': {'ret': 0x7000}}
        with patch.object(particle_editor_tree, 'cs2_editor_document', return_value={
                 'ok': True, 'session': '0x1000', 'document': '0x3000', 'root': '0x4000'}), \
             patch.object(particle_editor_tree, '_tool_module', return_value={'cls': 'CPetApp'}), \
             patch.object(particle_editor_tree, '_read_int', side_effect=lambda addr, kind: reads[addr]), \
             patch.object(particle_editor_tree, '_editor_session_class', return_value='CPetFunctionNode'), \
             patch.object(particle_editor_tree, '_read_string', return_value='C_OP_Test'), \
             patch.object(particle_editor_tree, 'get_session', return_value=session):
            result = particle_editor_tree.cs2_particle_editor_tree(category=0)
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['groups'][0]['nodes'][0]['class_name'], 'C_OP_Test')
        self.assertEqual(result['groups'][0]['count'], 1)
        self.assertFalse(particle_editor_tree.cs2_particle_editor_tree(category=9)['ok'])


if __name__ == '__main__':
    unittest.main()
