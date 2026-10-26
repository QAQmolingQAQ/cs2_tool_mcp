"""Artifact success must depend on content, including visibility and lighting."""
from pathlib import Path
import struct
import sys
import tempfile
import tracemalloc
import unittest
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'mcp_server'))
from hammer_mcp.build_artifact import verify_map_artifact, inspect_vpk


def resource(tag=b'DATA'):
    return struct.pack('<IHHII', 29, 12, 0, 8, 1) + struct.pack('<4sII', tag, 8, 1) + b'x'


def package(path, entries):
    tree = bytearray()
    payload = bytearray()
    groups = {}
    for name, data in entries.items():
        item = Path(name)
        groups.setdefault(item.suffix[1:], {}).setdefault(item.parent.as_posix(), []).append((item.stem, data))
    for extension, folders in groups.items():
        tree += extension.encode() + b'\0'
        for folder, items in folders.items():
            tree += folder.encode() + b'\0'
            for stem, data in items:
                tree += stem.encode() + b'\0'
                tree += struct.pack('<IHHIIH', zlib.crc32(data), 0, 0x7FFF, len(payload), len(data), 0xFFFF)
                payload += data
            tree += b'\0'
        tree += b'\0'
    tree += b'\0'
    path.write_bytes(struct.pack('<III', 0x55AA1234, 1, len(tree)) + tree + payload)


class BuildArtifactTests(unittest.TestCase):
    def test_large_entry_streams_crc_and_fingerprint_with_bounded_memory(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'large.vpk'
            block = b'Z' * (1024 * 1024)
            count = 513  # Exceeds both old per-entry and aggregate payload caps.
            crc = 0
            for _ in range(count):
                crc = zlib.crc32(block, crc)
            tree = b'bin\0 \0blob\0' + struct.pack('<IHHIIH', crc, 0, 0x7FFF, 0, len(block) * count, 0xFFFF) + b'\0\0\0'
            with path.open('wb') as stream:
                stream.write(struct.pack('<III', 0x55AA1234, 1, len(tree)) + tree)
                for _ in range(count):
                    stream.write(block)
            tracemalloc.start()
            try:
                inspection = inspect_vpk(path)
                fingerprints = inspection.fingerprints()
                _, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
            self.assertEqual(inspection.validated_bytes, 513 * 1024 * 1024)
            self.assertEqual(fingerprints[str(path.resolve())]['size'], path.stat().st_size)
            self.assertLess(peak, 16 * 1024 * 1024)

    def test_preload_split_volume_crc_hash_and_storage_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'split_dir.vpk'
            volume = Path(folder) / 'split_005.vpk'
            preload = b'preload'
            stored = b'remaining contents'
            tree = b'bin\0 \0blob\0' + struct.pack('<IHHIIH', zlib.crc32(preload + stored),
                len(preload), 5, 16, len(stored), 0xFFFF) + preload + b'\0\0\0'
            path.write_bytes(struct.pack('<III', 0x55AA1234, 1, len(tree)) + tree)
            volume.write_bytes(b'padding ignored!' + stored)
            inspection = inspect_vpk(path)
            self.assertEqual(inspection.entries['blob.bin'].prefix(10), (preload + stored)[:10])
            self.assertEqual(len(inspection.fingerprints()), 2)
            volume.write_bytes(b'padding ignored!' + b'changed contents!!')
            with self.assertRaisesRegex(ValueError, 'changed'):
                inspection.fingerprints()
            with self.assertRaisesRegex(ValueError, 'CRC'):
                inspect_vpk(path)
            volume.unlink()
            with self.assertRaises(OSError):
                inspect_vpk(path)

    def test_cs2_signature_payload_is_outside_twenty_byte_header_size(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'signed.vpk'
            body = (struct.pack('<7I', 0x55AA1234, 2, 1, 0, 0, 0, 20) + b'\0' +
                    struct.pack('<5I', 0x55AA1234, 1, 3, 3, 0) + b'keysig')
            path.write_bytes(body)
            inspection = inspect_vpk(path)
            self.assertEqual(inspection.signature['format'], 'cs2')
            self.assertFalse(inspection.signature['cryptographic_validation'])
            for malformed in (body[:-1], body + b'junk'):
                path.write_bytes(malformed)
                with self.assertRaisesRegex(ValueError, 'bounds'):
                    inspect_vpk(path)

    def test_root_reference_manifest_may_have_empty_data_but_vis_must_not(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'map.vpk'
            root = (struct.pack('<IHHII', 41, 12, 0, 8, 2) +
                    struct.pack('<4sII', b'RERL', 20, 1) + struct.pack('<4sII', b'DATA', 9, 0) + b'x')
            entries = {'maps/sample.vmap_c': root, 'maps/sample/world.vwrld_c': resource(),
                       'maps/sample/world_visibility.vvis_c': resource(b'VXVS')}
            package(path, entries)
            self.assertTrue(verify_map_artifact(str(path), 'sample', 'quick')['ok'])
            entries['maps/sample/world_visibility.vvis_c'] = (struct.pack('<IHHII', 28, 12, 0, 8, 1) +
                struct.pack('<4sII', b'VXVS', 8, 0))
            package(path, entries)
            self.assertFalse(verify_map_artifact(str(path), 'sample', 'quick')['ok'])

    def test_validation_cancellation_is_explicit(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'map.vpk'
            package(path, {'data/large.bin': b'x' * (4 * 1024 * 1024)})
            checks = 0
            def cancelled():
                nonlocal checks
                checks += 1
                return checks >= 3
            result = verify_map_artifact(str(path), 'sample', 'quick', cancelled=cancelled)
            self.assertFalse(result['ok'])
            self.assertTrue(result['cancelled'])

    def test_full_requires_real_lightmap_resources(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'map.vpk'
            entries = {'maps/sample.vmap_c': resource(), 'maps/sample/world.vwrld_c': resource(),
                       'maps/sample/world_visibility.vvis_c': resource(b'VXVS')}
            package(path, entries)
            self.assertTrue(verify_map_artifact(str(path), 'sample', 'quick')['ok'])
            self.assertFalse(verify_map_artifact(str(path), 'sample')['ok'])
            for name in ('irradiance', 'directional_irradiance', 'direct_light_shadows'):
                entries[f'maps/sample/lightmaps/{name}.vtex_c'] = resource()
            package(path, entries)
            self.assertTrue(verify_map_artifact(str(path), 'sample')['ok'])
            corrupted = bytearray(path.read_bytes())
            corrupted[-1] ^= 1
            path.write_bytes(corrupted)
            self.assertIn('CRC', verify_map_artifact(str(path), 'sample')['error'])

    def test_visibility_name_alone_is_insufficient(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'map.vpk'
            package(path, {'maps/sample/world_visibility.vvis_c': resource()})
            result = verify_map_artifact(str(path), 'sample', 'quick')
            self.assertFalse(result['ok'])
            self.assertFalse(result['visibility'])

    def test_bad_resource_and_unsafe_path(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'map.vpk'
            package(path, {'maps/sample.vmap_c': b'invalid'})
            self.assertFalse(verify_map_artifact(str(path), 'sample')['ok'])
            package(path, {'../escape.vmap_c': resource()})
            self.assertIn('unsafe', verify_map_artifact(str(path), 'sample')['error'])


if __name__ == '__main__':
    unittest.main()
