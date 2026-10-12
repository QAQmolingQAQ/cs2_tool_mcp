"""Validation for editor sessions derived from live App vectors and MSVC RTTI."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp_server"))
from hammer_mcp import bindings


class EditorSessionTests(unittest.TestCase):
    def test_rtti_uses_target_module_image_not_hammer(self):
        md = {"base": 0x100000, "size": 0x10000}
        values = {0x300000: 0x100200, 0x1001F8: 0x100300, 0x10030C: 0x400}
        with patch.object(bindings, "_read_int", side_effect=lambda address, kind: values[address]), \
             patch.object(bindings, "_read_string", return_value=".?AVCModelDocEditorSession@@"):
            self.assertEqual(bindings._editor_session_class(0x300000, md), "CModelDocEditorSession")
        values[0x300000] = 0x900000
        with patch.object(bindings, "_read_int", side_effect=lambda address, kind: values[address]):
            self.assertEqual(bindings._editor_session_class(0x300000, md), "")

    def test_active_context_requires_matching_session_rtti(self):
        md = {"label": "modeldoc", "tool_system": 0x200000,
              "base": 0x100000, "size": 0x10000, "cls": "CModelDocEditorApp"}
        values = {0x200050: 0x300000, 0x200058: 2, 0x200060: 0x400000,
                  0x400000: 0x300000, 0x400008: 0x300100}
        with patch.object(bindings, "_read_int", side_effect=lambda address, kind: values[address]), \
             patch.object(bindings, "_editor_session_class",
                          side_effect=lambda address, module: "CModelDocEditorSession" if address == 0x300000 else "CWrongClass"):
            self.assertEqual(bindings._editor_sessions(md), ([0x300000], 0x300000))
            self.assertEqual(bindings._bind_ctx(md, "ModelDocEditorSession", "CModelDocEditorSession", "")[0], 0x300000)
            values[0x200050] = 0x300100
            self.assertEqual(bindings._editor_sessions(md), ([0x300000], 0))
            self.assertEqual(bindings._bind_ctx(md, "ModelDocEditorSession", "CModelDocEditorSession", "")[0], 0)

    def test_rejects_implausible_session_count(self):
        md = {"label": "pet", "tool_system": 0x200000}
        with patch.object(bindings, "_read_int", return_value=999):
            with self.assertRaisesRegex(ValueError, "implausible"):
                bindings._editor_sessions(md)


if __name__ == "__main__":
    unittest.main()
