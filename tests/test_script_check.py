"""Parse source declarations without executing map scripts."""
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'mcp_server'))
from hammer_mcp.script_check import analyze_text, check_scripts, HELPER
from hammer_mcp.map_io_check import check_entities
from hammer_mcp.fgd import FgdCatalog

SDK = 'import {Instance as I} from "cs_script/point_script";\n'


@unittest.skipUnless(shutil.which('node') and (HELPER.parent/'node_modules/acorn').is_dir(),
                     'requires Node.js and npm ci in mcp_server/script_tools')
class ScriptCheckTests(unittest.TestCase):
    def test_ast_ignores_comments_strings_and_does_not_execute(self):
        result = analyze_text(SDK + '''
// I.OnScriptInput("Comment", () => {});
const text = 'I.OnScriptInput("String", () => {})';
throw new Error("must never execute");
I.OnScriptInput("Go", input => { input?.caller; });
''')
        self.assertTrue(result['syntax_ok'])
        self.assertEqual([r['name'] for r in result['registrations']], ['Go'])
        # Syntactic declarations cannot prove the registration is reached.
        self.assertIn('saved source AST', check_scripts([], Path('.'), Path('.'))['basis'])

    def test_dynamic_registration_is_incomplete_and_syntax_is_distinct(self):
        for source in ['if (true) I.OnScriptInput("Go", () => {});',
                       'I.OnScriptInput(name, () => {});',
                       'false && I.OnScriptInput("Go", () => {});',
                       'I?.OnScriptInput("Go", () => {});',
                       'const f = I.OnScriptInput; f("Go", () => {});',
                       'function f(I) { I.OnScriptInput("Go", () => {}); }']:
            result = analyze_text(SDK + source)
            self.assertTrue(result['syntax_ok'])
            self.assertFalse(result['registration_scan_complete'])
        self.assertFalse(analyze_text(SDK + 'const = ;')['syntax_ok'])

    def run_fixture(self, root, source, entry='Go'):
        root.mkdir(exist_ok=True)
        (root/'main.js').write_text(source, encoding='utf-8')
        script = {'id':'s', 'properties':{'classname':'point_script','targetname':'script1',
                                        'cs_script':'main.vjs'}, 'connections':[]}
        relay = {'id':'r','properties':{'classname':'logic_relay'},'connections':[
            {'targetName':'script*','inputName':'RunScriptInput','overrideParam':entry}]}
        return check_scripts([script,relay],root,root.parent/'game')

    def test_virtual_source_imports_and_exact_input_name(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'addon';root.mkdir()
            (root/'child.js').write_text(SDK+'I.OnScriptInput("Go", () => {});',encoding='utf-8')
            result=self.run_fixture(root,'import "./child.vjs";', 'go')
            self.assertEqual(result['scripts']['s']['inputs'],['Go'])
            self.assertEqual(len(result['source_files']),2)
            self.assertIn('script_input_not_statically_declared',[i['code'] for i in result['issues']])
            self.assertFalse(result['coverage_complete'])
            self.assertFalse(result['static_checks_passed'])

    def test_missing_source_is_warning_and_ambiguous_sources_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'addon';root.mkdir()
            (root/'main.vjs').write_text('',encoding='utf-8')
            result=self.run_fixture(root,SDK)
            self.assertEqual(result['issues'][0]['code'],'script_source_unresolved')
            self.assertEqual(result['issues'][0]['severity'],'warning')
            self.assertIn('ambiguous',result['issues'][0]['detail'])

    def test_escape_import_and_parser_failure_remain_unverified(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'addon'
            result=self.run_fixture(root,'import "../outside.js";')
            self.assertFalse(result['scripts']['s']['registration_analysis_complete'])
            self.assertIn('script_import_unresolved',[i['code'] for i in result['issues']])
            with patch('hammer_mcp.script_check.analyze_text',side_effect=ValueError('parser unavailable')):
                result=self.run_fixture(root,SDK)
            self.assertIn('script_analysis_unavailable',[i['code'] for i in result['issues']])
            self.assertFalse(result['declaration_analysis_complete'])
            self.assertFalse(result['runtime_registration_verified'])
            self.assertFalse(result['static_checks_passed'])

    def test_source_mutation_during_parse_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'addon'
            def mutate(source):
                (root/'main.js').write_text('changed source',encoding='utf-8')
                return {'syntax_ok':True,'registrations':[],'imports':[],
                        'registration_scan_complete':True}
            with patch('hammer_mcp.script_check.analyze_text',side_effect=mutate):
                result=self.run_fixture(root,SDK)
            self.assertFalse(result['declaration_analysis_complete'])
            self.assertIn('script_analysis_unavailable',[i['code'] for i in result['issues']])

    def test_virtual_js_symlink_cannot_escape_source_root(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'addon';root.mkdir()
            outside=Path(folder)/'outside.js';outside.write_text(SDK,encoding='utf-8')
            try:(root/'main.js').symlink_to(outside)
            except OSError:self.skipTest('symlink creation unavailable')
            script={'id':'s','properties':{'classname':'point_script','cs_script':'main.vjs'},'connections':[]}
            result=check_scripts([script],root,root.parent/'game')
            self.assertFalse(result['declaration_analysis_complete'])
            self.assertEqual(result['source_files'],{})
            self.assertEqual(result['issues'][0]['code'],'script_source_unresolved')

    def test_script_errors_merge_into_map_counts_and_truncation(self):
        audit={'issues':[{'code':'script_syntax_error','severity':'error','entity':'s'},
                         {'code':'script_import_unresolved','severity':'warning','entity':'s'}]}
        result=check_entities([],FgdCatalog(Path('/unused')),1,audit)
        self.assertFalse(result['passed'])
        self.assertEqual(result['issue_count'],2)
        self.assertTrue(result['issues_truncated'])
        self.assertEqual(result['severity_counts'],{'error':1,'warning':1})
