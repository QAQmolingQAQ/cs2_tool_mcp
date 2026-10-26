import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mcp_server'))
from hammer_mcp.qt_text_catalog import load_catalog,lookup,annotate_snapshot

class QtTextCatalogTests(unittest.TestCase):
    def test_variants_reverse_ambiguity_and_observed_text_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/'hammer.json').write_text(json.dumps({'Save':'保存','Store':'保存','Open':{'en':'Open','zh':'打开'},'Blank':''}),encoding='utf-8')
            (root/'common.json').write_text(json.dumps({'Save':'存储'}),encoding='utf-8')
            cat=load_catalog(root,'hammer')
            self.assertEqual(len(lookup(cat,'Save')),2)
            self.assertEqual(len(lookup(cat,'保存')),2)
            snap={'widgets':[{'button_text':'Save','address':'0x1234'}]}
            result=annotate_snapshot(snap,cat)
            self.assertEqual(result['widgets'][0]['button_text'],'Save')
            self.assertEqual(result['widgets'][0]['address'],'0x1234')
            self.assertNotIn('text_reference',snap['widgets'][0])
            self.assertEqual(len(result['widgets'][0]['text_reference']),2)
            self.assertEqual(len(cat['files'][0]['sha256']),64)
    def test_invalid_scope_root_shape_and_rich_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with self.assertRaises(ValueError):load_catalog(root,'../private')
            path=root/'hammer.json'
            for data in ([],{'Save':7},{'Save':{'en':'Delete','zh':'保存'}}):
                path.write_text(json.dumps(data),encoding='utf-8')
                with self.assertRaises(ValueError):load_catalog(root,'hammer')

if __name__=='__main__':unittest.main()
