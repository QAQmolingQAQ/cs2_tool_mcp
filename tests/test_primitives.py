import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'mcp_server'))
from hammer_mcp import meshes


class PrimitiveGeometryTests(unittest.TestCase):
    def test_face_counts_and_outward_winding(self):
        size = (64.0, 48.0, 32.0)
        for shape, expected in (('quad', 1), ('cylinder', 10),
                                ('spike', 9), ('sphere', 32)):
            with self.subTest(shape=shape):
                faces = meshes._primitive_faces(size, shape, 8, 4, 0)
                self.assertEqual(len(faces), expected)
                for face in faces:
                    nx, ny, nz = meshes._face_normal_newell(face)
                    self.assertGreater(nx * nx + ny * ny + nz * nz, 1e-8)
                    if shape != 'quad':
                        cx = sum(p[0] for p in face) / len(face)
                        cy = sum(p[1] for p in face) / len(face)
                        cz = sum(p[2] for p in face) / len(face)
                        self.assertGreater(nx * cx + ny * cy + nz * cz, 0)

    def test_curved_uvs_are_continuous_at_shared_side_edges(self):
        size = (64.0, 48.0, 32.0)
        for shape in ('cylinder', 'spike'):
            faces = meshes._primitive_faces(size, shape, 8, 4, 0)
            uvs = meshes._primitive_uvs(faces, size, shape, 8, 4, 512)
            start = 2 if shape == 'cylinder' else 1
            for i in range(7):
                self.assertAlmostEqual(uvs[start + i][1][0], uvs[start + i + 1][0][0])
            self.assertGreater(uvs[-1][1][0], 0)
        faces = meshes._primitive_faces(size, 'sphere', 8, 4, 0)
        uvs = meshes._primitive_uvs(faces, size, 'sphere', 8, 4, 512)
        self.assertEqual(len(uvs), len(faces))
        self.assertTrue(all(len(a) == len(b) for a, b in zip(faces, uvs)))
        self.assertTrue(all(math.isfinite(value) for face in uvs for uv in face for value in uv))
        self.assertAlmostEqual(uvs[0][2][0], uvs[1][1][0])

    def test_invalid_request_stops_before_connecting(self):
        with patch.object(meshes, '_hammer_base', side_effect=AssertionError('connected')):
            for params in ({'shape': 'octagon'}, {'shape': 'sphere', 'rings': 1},
                           {'shape': 'cylinder', 'segments': 65},
                           {'shape': 'spike', 'rotation': float('nan')},
                           {'shape': 'quad', 'tex_size': 0}):
                with self.subTest(params=params):
                    result = meshes.create_primitive(**params)
                    self.assertFalse(result.ok)
                    self.assertIsNone(result.element)
