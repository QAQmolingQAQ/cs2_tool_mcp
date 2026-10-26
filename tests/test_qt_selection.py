"""A UI selection must retain configured document scope and observed identity."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mcp_server'))
from hammer_mcp.qt_diagnostics import cs2_qt_hammer_select


class QtSelectionTests(unittest.TestCase):
    def test_invalid_paths_stop_before_project_or_transport(self):
        for path in ('[]','[true]','[1.5]','[-1]','[100000]','{}','[0,0,0,0,0,0,0,0,0]'):
            with self.subTest(path=path), patch('hammer_mcp.qt_diagnostics.load_project') as project, patch('hammer_mcp.qt_diagnostics._call') as native:
                with self.assertRaises(ValueError):cs2_qt_hammer_select(path,'label','key')
                project.assert_not_called();native.assert_not_called()

    def test_root_comes_from_config_and_preview_is_default(self):
        with patch('hammer_mcp.qt_diagnostics.load_project',return_value={'source':'C:/Game/Map.vmap'}) as project, patch('hammer_mcp.qt_diagnostics._call',return_value='preview') as native:
            self.assertEqual(cs2_qt_hammer_select('[0,1]','Entity','observed','project.json','test'),'preview')
            project.assert_called_once_with('project.json','test')
            native.assert_called_once_with('qt_hammer_outliner_select',{'row_path':[0,1],
                'expected_root':'c:/game/map.vmap','expected_label':'Entity','expected_row_key':'observed','confirm':False})

    def test_invalid_confirm_or_missing_identity_never_dispatches(self):
        for label,key,confirm in (('','key',True),('Entity','',True),('Entity','key',1)):
            with self.subTest(label=label,key=key,confirm=confirm), patch('hammer_mcp.qt_diagnostics._call') as native:
                with self.assertRaises(ValueError):cs2_qt_hammer_select('[0]',label,key,confirm=confirm)
                native.assert_not_called()
