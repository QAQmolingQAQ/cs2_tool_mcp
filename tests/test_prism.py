import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'mcp_server'))
from hammer_mcp import meshes


class PrismGeometryTests(unittest.TestCase):
    def test_caps_and_sides_point_outward(self):
        for sides in (3, 4, 16, 64):
            with self.subTest(sides=sides):
                faces = meshes._prism_faces((64.0, 48.0, 32.0), sides, 12.0)
                self.assertEqual(len(faces), sides + 2)
                self.assertEqual([len(f) for f in faces], [sides, sides] + [4] * sides)
                self.assertLess(meshes._face_normal_newell(faces[0])[2], 0)
                self.assertGreater(meshes._face_normal_newell(faces[1])[2], 0)
                for face in faces[2:]:
                    nx, ny, nz = meshes._face_normal_newell(face)
                    cx = sum(p[0] for p in face) / 4
                    cy = sum(p[1] for p in face) / 4
                    self.assertGreater(nx * cx + ny * cy, 0)
                    self.assertAlmostEqual(nz, 0)

    def test_invalid_request_does_not_touch_hammer(self):
        with patch.object(meshes, '_hammer_base', side_effect=AssertionError('must not connect')):
            for kwargs in ({'sides': 2}, {'sides': 65}, {'sides': 4.5},
                           {'rotation': float('nan')}, {'size': '0 8 8'},
                           {'size': 'inf 8 8'}, {'tex_size': 0}):
                with self.subTest(kwargs=kwargs):
                    result = meshes.create_prism(**kwargs)
                    self.assertFalse(result.ok)
                    self.assertIsNone(result.element)


if __name__ == '__main__':
    unittest.main()
