"""Read VPK directory entries and verify map build evidence without extraction."""
from __future__ import annotations

from pathlib import Path, PurePosixPath
from dataclasses import dataclass
import hashlib
import struct
from typing import Callable
import zlib

CHUNK_SIZE = 1024 * 1024


class ArtifactCheckCancelled(ValueError):
    pass


def _check_cancel(cancelled):
    if cancelled is not None and cancelled():
        raise ArtifactCheckCancelled('artifact validation cancelled')


def _stamp(path: Path) -> tuple:
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


@dataclass(frozen=True)
class VpkEntry:
    storage: Path | None
    offset: int
    stored_size: int
    preload: bytes
    crc: int

    @property
    def size(self):
        return len(self.preload) + self.stored_size

    def chunks(self):
        if self.preload:
            yield self.preload
        if self.stored_size:
            with self.storage.open('rb') as stream:
                stream.seek(self.offset)
                remaining = self.stored_size
                while remaining:
                    chunk = stream.read(min(CHUNK_SIZE, remaining))
                    if not chunk:
                        raise ValueError('VPK payload truncated during read')
                    remaining -= len(chunk)
                    yield chunk

    def prefix(self, count: int) -> bytes:
        data = self.preload[:count]
        if count > len(data) and self.stored_size:
            with self.storage.open('rb') as stream:
                stream.seek(self.offset)
                data += stream.read(min(self.stored_size, count - len(data)))
        return data


@dataclass
class VpkInspection:
    entries: dict[str, VpkEntry]
    stamps: dict[Path, tuple]
    validated_bytes: int
    signature: dict

    def unchanged(self):
        for path, expected in self.stamps.items():
            if _stamp(path) != expected:
                raise ValueError(f'VPK storage changed during validation: {path.name}')

    def fingerprints(self, cancelled=None) -> dict:
        result = {}
        for path in self.stamps:
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                while chunk := stream.read(CHUNK_SIZE):
                    _check_cancel(cancelled)
                    digest.update(chunk)
            result[str(path)] = {'sha256': digest.hexdigest(), 'size': self.stamps[path][2]}
        self.unchanged()
        return result


def inspect_vpk(path: Path, cancelled: Callable[[], bool] | None = None) -> VpkInspection:
    """Stream every entry's CRC; retain only the bounded directory and metadata."""
    path = path.resolve(strict=True)
    stamps = {path: _stamp(path)}
    signature = {'format': 'none', 'cryptographic_validation': False}
    with path.open('rb') as stream:
        header = stream.read(12)
        if len(header) != 12:
            raise ValueError('truncated VPK header')
        magic, version, tree_size = struct.unpack('<III', header)
        if magic != 0x55AA1234 or version not in (1, 2):
            raise ValueError('unsupported VPK header')
        header_size = 28 if version == 2 else 12
        if tree_size > 64 * 1024 * 1024:
            raise ValueError('VPK directory exceeds limit')
        data_end = stamps[path][2]
        if version == 2:
            extra = stream.read(16)
            if len(extra) != 16:
                raise ValueError('truncated VPK v2 header')
            sections = struct.unpack('<IIII', extra)
            data_end = header_size + tree_size + sections[0]
            declared_end = header_size + tree_size + sum(sections)
            expected_end = declared_end
            if sections[3] == 20 and declared_end <= stamps[path][2]:
                # CS2's new signature size covers only its 20-byte header.
                # See ValvePak/ValvePak/Package.Read.cs, ReadSignatureSection.
                stream.seek(declared_end - 20)
                magic2, kind, key_size, signature_size, reserved = struct.unpack('<IIIII', stream.read(20))
                if magic2 == 0x55AA1234:
                    if kind not in (0, 1):
                        raise ValueError('unsupported VPK signature type')
                    expected_end += key_size + signature_size
                    signature = {'format': 'cs2', 'type': kind, 'public_key_bytes': key_size,
                                 'signature_bytes': signature_size, 'cryptographic_validation': False}
                else:
                    signature['format'] = 'legacy'
            elif sections[3]:
                signature['format'] = 'legacy'
            if expected_end != stamps[path][2]:
                raise ValueError('invalid VPK v2 section bounds')
        if header_size + tree_size > data_end:
            raise ValueError('VPK directory exceeds file bounds')
        stream.seek(header_size)
        tree = stream.read(tree_size)
        if len(tree) != tree_size:
            raise ValueError('truncated VPK directory')
    cursor = 0
    entries = {}
    total_size = 0

    def string():
        nonlocal cursor
        end = tree.find(b'\0', cursor)
        if end < 0:
            raise ValueError('unterminated VPK directory string')
        value = tree[cursor:end].decode('utf-8')
        cursor = end + 1
        return value

    while extension := string():
        while folder := string():
            while stem := string():
                _check_cancel(cancelled)
                if cursor + 18 > len(tree):
                    raise ValueError('truncated VPK entry')
                crc, preload, archive, offset, size, terminator = struct.unpack_from('<IHHIIH', tree, cursor)
                cursor += 18
                if terminator != 0xFFFF or cursor + preload > len(tree):
                    raise ValueError('invalid VPK entry')
                name = ('' if folder == ' ' else folder + '/') + stem + ('' if extension == ' ' else '.' + extension)
                parts = PurePosixPath(name)
                if '\\' in name or ':' in name or parts.is_absolute() or '..' in parts.parts or name.casefold() in entries:
                    raise ValueError('unsafe or duplicate VPK path')
                if len(entries) >= 250000:
                    raise ValueError('VPK directory entry count exceeds limit')
                total_size += size + preload
                payload = tree[cursor:cursor + preload]
                cursor += preload
                storage = path
                start = header_size + tree_size + offset
                bound = data_end
                if size and archive != 0x7FFF:
                    if not path.stem.endswith('_dir'):
                        raise ValueError('split VPK requires _dir filename')
                    storage = path.with_name(path.stem[:-4] + f'_{archive:03d}.vpk')
                    start = offset
                    stamp = _stamp(storage)
                    if storage in stamps and stamps[storage] != stamp:
                        raise ValueError('split VPK changed while reading directory')
                    stamps[storage] = stamp
                    bound = stamp[2]
                if size and start + size > bound:
                    raise ValueError(f'truncated VPK payload: {name}')
                entry = VpkEntry(storage if size else None, start, size, payload, crc)
                actual_crc = 0
                for chunk in entry.chunks():
                    _check_cancel(cancelled)
                    actual_crc = zlib.crc32(chunk, actual_crc)
                if actual_crc & 0xFFFFFFFF != crc:
                    raise ValueError(f'VPK CRC mismatch: {name}')
                entries[name.casefold()] = entry
    if cursor != len(tree):
        raise ValueError('unexpected trailing directory bytes')
    result = VpkInspection(entries, stamps, total_size, signature)
    result.unchanged()
    return result


def resource_blocks(resource: bytes | VpkEntry, *, nonempty: bool = False) -> list[str]:
    data = resource.prefix(16) if isinstance(resource, VpkEntry) else resource
    if len(data) < 16:
        raise ValueError('truncated compiled resource')
    length, header_version, _, relative, count = struct.unpack_from('<IHHII', data)
    table = 8 + relative
    available = resource.size if isinstance(resource, VpkEntry) else len(data)
    if header_version != 12 or length > available or length < 16 or table < 16 or table + count * 12 > length:
        raise ValueError('invalid compiled resource header')
    if isinstance(resource, VpkEntry):
        if table + count * 12 > CHUNK_SIZE:
            raise ValueError('compiled resource block directory exceeds inspection limit')
        data = resource.prefix(table + count * 12)
    if len(data) < table + count * 12:
        raise ValueError('truncated compiled resource block directory')
    blocks = []
    for index in range(count):
        position = table + index * 12
        tag, offset, size = struct.unpack_from('<4sII', data, position)
        start = position + 4 + offset
        if start < table + count * 12 or start + size > length:
            raise ValueError('compiled resource block outside bounds')
        if size or not nonempty:
            blocks.append(tag.decode('ascii'))
    return blocks


def verify_map_artifact(path: str, map_name: str, mode: str = 'full', *, cancelled: Callable[[], bool] | None = None) -> dict:
    """Check CRCs, map/world resources, visibility and recognized lightmap sets.

    Presence proves packaged resources, not lighting quality or in-game correctness.
    """
    try:
        if mode not in ('quick', 'full'):
            raise ValueError('mode must be quick or full')
        prefix = 'maps/' + map_name.replace('\\', '/').removeprefix('maps/').removesuffix('.vmap')
        if '..' in PurePosixPath(prefix).parts or ':' in prefix:
            raise ValueError('invalid map name')
        inspection = inspect_vpk(Path(path), cancelled)
        entries = inspection.entries
        required = [prefix + '.vmap_c', prefix + '/world.vwrld_c', prefix + '/world_visibility.vvis_c']
        missing = [name for name in required if name.casefold() not in entries]
        blocks = {name: resource_blocks(entries[name.casefold()]) for name in required if name.casefold() in entries}
        populated = {name: resource_blocks(entries[name.casefold()], nonempty=True) for name in required if name.casefold() in entries}
        content = bool({'RERL', 'DATA'} & set(populated.get(required[0], []))) and 'DATA' in populated.get(required[1], [])
        visibility = 'VXVS' in populated.get(required[2], [])
        lightmaps = {PurePosixPath(name).stem for name, data in entries.items()
                     if name.startswith(prefix.casefold() + '/lightmaps/') and name.endswith('.vtex_c')
                     and 'DATA' in resource_blocks(data, nonempty=True)}
        sets = [ {'irradiance', 'directional_irradiance', 'direct_light_shadows'},
                 {'irradiance', 'directional_irradiance', 'direct_light_indices', 'direct_light_strengths'},
                 {'irradiance', 'directional_irradiance_sh2_r', 'directional_irradiance_sh2_g', 'directional_irradiance_sh2_b', 'direct_light_shadows'} ]
        lighting = any(group <= lightmaps for group in sets)
        files = inspection.fingerprints(cancelled)
        _check_cancel(cancelled)
        return {'ok': not missing and content and visibility and (mode == 'quick' or lighting), 'mode': mode,
                'sha256': files[str(Path(path).resolve())]['sha256'], 'entries': len(entries), 'missing': missing,
                'storage_files': files, 'validated_bytes': inspection.validated_bytes,
                'signature': inspection.signature,
                'visibility': visibility, 'lighting': lighting, 'lightmaps': sorted(lightmaps),
                'resource_blocks': blocks, 'artifact_complete': not missing and content and visibility and lighting,
                'release_ready': False,
                'evidence': 'VPK entry CRCs, compiled-resource bounds and named resource presence; no runtime validation'}
    except ArtifactCheckCancelled as exc:
        return {'ok': False, 'cancelled': True, 'error': str(exc)}
    except (OSError, ValueError, UnicodeError, struct.error) as exc:
        return {'ok': False, 'error': str(exc)}


def cs2_build_artifact_check(path: str, map_name: str, mode: str = 'full') -> dict:
    """Read-only VPK CRC, VIS and lightmap validation; does not prove runtime quality."""
    return verify_map_artifact(path, map_name, mode)
