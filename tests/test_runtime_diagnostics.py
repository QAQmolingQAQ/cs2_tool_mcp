from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mcp_server'))
from hammer_mcp.runtime_diagnostics import summarize


class RuntimeDiagnosticsTests(unittest.TestCase):
    def test_fixed_summary_keeps_map_coordinates_cvar_without_private_status_fields(self):
        lines=['Client:  Connected [loopback:1] [last packet 0.001 sec ago]\n',
               'loaded spawngroup(  1)  : SV:  [1: mcp_example | main lump | mapload]\n',
               'setpos 1.000000 -2.500000 0.015625;setang 0.000000 90.000000 0.000000\n',
               'sv_cheats = true\n','Unknown command: meta\n','Unknown command: css_plugins\n',
               'hostname : private-host\n','steamid : private-id\n']
        d=summarize(lines)
        self.assertEqual(d['observed_maps'],['mcp_example']);self.assertTrue(d['client_connected'])
        self.assertEqual(d['world_position'],[1,-2.5,0.015625]);self.assertTrue(d['final_cvars']['sv_cheats'])
        self.assertEqual(d['plugin_commands_unavailable'],['css_plugins','meta'])
        self.assertNotIn('private',str(d));self.assertFalse(d['sound_lifetimes_verified'])
    def test_missing_output_does_not_infer_position_plugin_absence_or_connection(self):
        d=summarize(['Unknown command: getpos\n','sv_cheats = maybe\n'])
        self.assertIsNone(d['world_position']);self.assertIsNone(d['final_cvars']['sv_cheats'])
        self.assertFalse(d['client_connected']);self.assertEqual(d['plugin_commands_unavailable'],[])
