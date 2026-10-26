import sys
from pathlib import Path
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mcp_server'))
from hammer_mcp.qt_diagnostics import cs2_qt_widgets, cs2_qt_open_editor, cs2_qt_menu_actions

class QtDiagnosticsTests(unittest.TestCase):
    def test_rejects_invalid_bounds_without_dispatch(self):
        with patch('hammer_mcp.qt_diagnostics._call') as call:
            for offset,limit in [(-1,1),(20001,1),(True,1),(0,False),(0,129),(0,0),(1.5,1)]:
                with self.assertRaises(ValueError): cs2_qt_widgets(offset,limit)
            call.assert_not_called()
    def test_fixed_method_and_unmodified_failure(self):
        with patch('hammer_mcp.qt_diagnostics._call',return_value='{"error":"unsupported loaded Qt ABI identity"}') as call:
            result=cs2_qt_widgets(12,16)
            call.assert_called_once_with('qt_widgets_snapshot',{'offset':12,'limit':16})
            self.assertIn('unsupported',result)

    def test_launch_requires_known_editor_and_explicit_boolean(self):
        with patch('hammer_mcp.qt_diagnostics._call') as call:
            for editor, confirm in [('unknown', True), ('hammer', 1), ('hammer', 'yes')]:
                with self.assertRaises(ValueError): cs2_qt_open_editor(editor, confirm)
            call.assert_not_called()
            cs2_qt_open_editor('hammer')
            call.assert_called_once_with('qt_open_editor', {'editor':'hammer','confirm':False})

    def test_menu_selection_is_bounded_and_read_only(self):
        with patch('hammer_mcp.qt_diagnostics._call') as call:
            for name in ('', 'A'*129, None):
                with self.assertRaises(ValueError):cs2_qt_menu_actions(name)
            call.assert_not_called()
            cs2_qt_menu_actions()
            call.assert_called_once_with('qt_menu_actions',{'window_object_name':'CQBaseEditorWnd'})

if __name__=='__main__':unittest.main()
