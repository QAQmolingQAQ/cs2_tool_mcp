"""Named editor actions must route only verified bind targets and default to preview."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
