from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mcp_server'))
from hammer_mcp.plugin_diagnostics import summarize_queries


class PluginDiagnosticTests(unittest.TestCase):
    def test_versions_are_parsed_only_from_named_query_response(self):
        result=summarize_queries({'meta version':['Metamod:Source version 2.0.0-dev+100\n'],
            'meta list':[' [01] "CS2Fixes" (1.2.3-test) by test\n']})
        self.assertEqual(result['plugin_versions'],{'metamod':'2.0.0-dev+100','cs2fixes':'1.2.3-test'})
        self.assertFalse(result['plugin_presence_verified'])
        result=summarize_queries({'css_plugins list':['Metamod:Source version 2.0.0-dev+100\n']})
        self.assertEqual(result['plugin_versions'],{})

    def test_empty_unknown_and_failed_rows_never_prove_absence_or_version(self):
        result=summarize_queries({'meta version':['Unknown command: meta\n'],
            'meta list':[' [01] <FAILED> "CS2Fixes" (1.2.3) by test\n']})
        self.assertEqual(result['plugin_versions'],{})
        self.assertEqual(result['plugin_query_observations']['meta version']['status'],'command_unavailable')
        self.assertEqual(result['plugin_query_observations']['css_plugins list']['status'],'no_response_observed')
        self.assertFalse(result['plugin_presence_verified'])

    def test_conflicting_versions_omit_value_and_numeric_cvars_are_bounded(self):
        result=summarize_queries({'meta version':['Metamod:Source version 1.0\n','Metamod:Source version 2.0\n'],
            'cs2f_commands_enable':['cs2f_commands_enable = true\n'],
            'snd_musicvolume':['snd_musicvolume = nan\n']})
        self.assertEqual(result['plugin_versions'],{})
        self.assertEqual(result['plugin_query_observations']['meta version']['status'],'conflicting_versions')
        self.assertTrue(result['queried_cvars']['cs2f_commands_enable'])
        self.assertIsNone(result['queried_cvars']['snd_musicvolume'])
        result=summarize_queries({'snd_musicvolume':['snd_musicvolume = 0.25\n','snd_musicvolume = 0.5\n']})
        self.assertIsNone(result['queried_cvars']['snd_musicvolume'])
        self.assertEqual(result['plugin_query_observations']['snd_musicvolume']['status'],'conflicting_values')
        result=summarize_queries({'cs2f_commands_enable':['Unknown command: cs2f_commands_enable\n',
            'cs2f_commands_enable = true\n']})
        self.assertIsNone(result['queried_cvars']['cs2f_commands_enable'])
