import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mcp_server'))
from hammer_mcp.qt_discovery import analyze_discovery
class DiscoveryTests(unittest.TestCase):
    def test_mixed_ids_do_not_relabel_observed_functions(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)
            (p/'functions.json').write_text(json.dumps({'modules':[],'hooked':[{'id':7,'short':'setText','module':'Qt5Widgets.dll','addr':'0x1000'}]}))
            (p/'particle_operators.txt').write_text('Alpha fade\nAlpha fade\n')
            rows=[{'hook':7,'fn':'setText','mod':'Qt5Widgets.dll','t':'Alpha fade','stack':['cs2discover.dll+0x1','pet.dll+0x2']},
                  {'hook':7,'fn':'CUtlString::Set','mod':'tier0.dll','t':'debug','stack':[]}]
            (p/'calls.jsonl').write_text('\n'.join(json.dumps(r) for r in rows)+'\ninvalid\n[]\n')
            r=analyze_discovery(p)
            self.assertEqual(r['call_lines'],4);self.assertEqual(r['invalid_json_lines'],1)
            self.assertEqual(r['invalid_schema_rows'],1);self.assertEqual(r['metadata_mismatch_rows'],1)
            self.assertEqual(len(r['functions_by_record_fields']),2)
            self.assertEqual(r['operator_names_seen_in_capture'],1)
            self.assertEqual(r['first_noninfra_stack_modules'],{'pet.dll':1})
            self.assertEqual(r['unique_texts'],2)
if __name__=='__main__':unittest.main()
