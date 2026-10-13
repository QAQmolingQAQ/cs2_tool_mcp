"""Named editor actions must route only verified bind targets and default to preview."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp_server"))
from hammer_mcp import editor_actions


class EditorActionTests(unittest.TestCase):
    def test_modeldoc_action_previews_active_session_command(self):
        with patch.object(editor_actions, "cs2_bind_run", return_value="preview") as run:
            self.assertEqual(editor_actions.cs2_modeldoc_action("select_mode"), "preview")
            run.assert_called_once_with("modeldoc", "ModelDocEditorSession",
                                        "SetManipulationMode_Selection", confirm=False)

    def test_particle_action_uses_session_and_requires_confirm(self):
        with patch.object(editor_actions, "cs2_bind_run", return_value="executed") as run:
            self.assertEqual(editor_actions.cs2_particle_editor_action("add_function", confirm=True), "executed")
            run.assert_called_once_with("pet", "PetSession", "AddFunction", confirm=True)

    def test_unknown_action_does_not_execute(self):
        with patch.object(editor_actions, "cs2_bind_run") as run:
            self.assertIn("ERROR", editor_actions.cs2_particle_editor_action("invalid", confirm=True))
            self.assertIn("select_mode", editor_actions.cs2_modeldoc_action())
            run.assert_not_called()

    def test_modeldoc_open_previews_and_reads_back_native_session(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "content" / "csgo_addons" / "test" / "models" / "sample.vmdl"
            source.parent.mkdir(parents=True)
            source.write_text("<!-- kv3 encoding:text:version{x} format:modeldoc36:version{x} -->\n{}")
            session = Mock()
            session.pipe.call.return_value = {"result": {"main_thread_status": 0, "ret": 0x1234}}
            with patch.object(editor_actions, "get_session", return_value=session), \
                 patch.object(editor_actions, "_tool_module", return_value={"cls": "CModelDocEditorApp", "tool_system": 0x2000}), \
                 patch.object(editor_actions, "cs2_editor_document", return_value={"ok": True, "session": "0x1234", "document": "0x3000", "root": "0x4000"}):
                self.assertTrue(editor_actions.cs2_modeldoc_open(str(source))["preview"])
                session.pipe.call.assert_not_called()
                result = editor_actions.cs2_modeldoc_open(str(source), confirm=True)
                self.assertEqual(result["root"], "0x4000")
                self.assertEqual(session.pipe.call.call_args.args[0], "call_virtual")
                self.assertEqual(session.pipe.call.call_args.args[1]["args"], ["str:" + str(source), 1])

    def test_modeldoc_open_rejects_non_addon_source(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "sample.vmdl"
            source.write_text("<!-- kv3 format:modeldoc36:version{x} -->\n{}")
            with patch.object(editor_actions, "get_session") as session:
                self.assertFalse(editor_actions.cs2_modeldoc_open(str(source), confirm=True)["ok"])
                session.assert_not_called()


if __name__ == "__main__":
    unittest.main()
