from pathlib import Path
import sys,unittest
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mcp_server'))
from hammer_mcp.runtime_diagnostics import summarize
from hammer_mcp.runtime_diagnostics import _diagnostic_lines


class RuntimeDiagnosticsTests(unittest.TestCase):
    def test_groups_only_accepts_active_server_main_map(self):
        d=summarize(['SV:  [1: mcp_test | main lump | mapload] (ACTIVE)\n',
                     'SV:  [1: mcp_test | main lump | mapload]: client private-name fully loaded\n',
                     'SV:  [2: stale | main lump | mapload] (LOADING)\n',
                     'CL:  [3: clientonly | main lump | mapload] (ACTIVE)\n',
                     'SV:  [4: other | child lump | mapload] (ACTIVE)\n'])
        self.assertEqual(d['observed_maps'],['mcp_test'])
        self.assertNotIn('private-name',str(d))

    def test_completion_marker_bounds_observation(self):
        reader=Mock()
        with patch('hammer_mcp.runtime_diagnostics.print_text',side_effect=[
                'outside','probe_END','probe','status line','probe_END','outside after']):
            self.assertEqual(_diagnostic_lines(reader,'probe'),['status line'])
        self.assertEqual(reader.frame.call_count,5)

    def test_timeout_after_start_is_not_completed_diagnostic(self):
        reader=Mock();reader.frame.side_effect=[object(),object(),TimeoutError('partial')]
        with patch('hammer_mcp.runtime_diagnostics.print_text',side_effect=['probe','status line']):
            with self.assertRaises(TimeoutError):_diagnostic_lines(reader,'probe')

    def test_diagnostic_frame_and_line_budgets(self):
        reader=Mock()
        with patch('hammer_mcp.runtime_diagnostics.print_text',return_value=None):
            with self.assertRaisesRegex(ValueError,'completion marker'):_diagnostic_lines(reader,'probe')
        with patch('hammer_mcp.runtime_diagnostics.print_text',side_effect=['probe']+['line']*4001):
            with self.assertRaisesRegex(ValueError,'line budget'):_diagnostic_lines(reader,'probe')

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
