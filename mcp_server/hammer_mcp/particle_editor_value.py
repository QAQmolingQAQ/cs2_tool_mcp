"""Bounded read-only access to live Particle Editor KV3 parameters."""
from __future__ import annotations

import re
import struct

from .bindings import cs2_editor_document, _tool_module, _editor_session_class
from .particle_catalog import cs2_particle_function_info
from .runtime import _read_bytes, _read_int, _read_string
from .session import get_session

_NAMES = {2: 'bool', 3: 'int', 5: 'double', 6: 'string', 8: 'array', 9: 'object'}
_SEGMENT = re.compile(r'[A-Za-z_][A-Za-z_0-9]*(?:\[\d{1,3}\])*\Z')
_INDEX = re.compile(r'\[(\d+)\]')


def _hash_name(name: str) -> int:
    """pet.dll+0x26F30, case-insensitive MurmurHash2 key."""
    data = name.encode('utf-8').lower()
    h = len(data) ^ 0x31415926
    pos = 0
    while len(data) - pos >= 4:
        key = int.from_bytes(data[pos:pos + 4], 'little')
        key = key * 0x5BD1E995 & 0xFFFFFFFF
        key ^= key >> 24
        key = key * 0x5BD1E995 & 0xFFFFFFFF
        h = (h * 0x5BD1E995 & 0xFFFFFFFF) ^ key
        pos += 4
    if pos < len(data):
        h ^= int.from_bytes(data[pos:], 'little')
        h = h * 0x5BD1E995 & 0xFFFFFFFF
    h ^= h >> 13
    h = h * 0x5BD1E995 & 0xFFFFFFFF
    return (h ^ (h >> 15)) & 0xFFFFFFFF


def _value(address: int) -> tuple[int, int, bytes]:
    raw = _read_bytes(address, 16)
    head, payload = struct.unpack('<QQ', raw)
    return (head >> 2) & 15, payload, raw


def _object(table: int) -> dict[int, int]:
    head = _read_bytes(table, 32)
    cap, count = struct.unpack_from('<I', head, 4)[0], struct.unpack_from('<I', head, 16)[0]
    if count > cap or cap > 256:
        raise ValueError('KV3 object size failed validation')
    slots = struct.unpack_from('<Q', head, 24)[0] if head[21] else table + 24
    if count and not slots:
        raise ValueError('KV3 object slots pointer is null')
    keys = _read_bytes(slots, 4 * count) if count else b''
    ptrs = _read_bytes(slots + ((4 * cap + 7) & ~7), 8 * count) if count else b''
    result = {}
    for i in range(count):
        key = struct.unpack_from('<I', keys, i * 4)[0]
        ptr = struct.unpack_from('<Q', ptrs, i * 8)[0]
        if not ptr or key in result:
            raise ValueError('KV3 object has null or duplicate member')
        result[key] = ptr
    return result


def _array(container: int) -> list[int]:
    head = _read_bytes(container, 24)
    cap, count = struct.unpack_from('<II', head, 4)
    if count > cap or cap > 256:
        raise ValueError('KV3 array size failed validation')
    slots = struct.unpack_from('<Q', head, 16)[0] if head[13] else container + 16
    if count and not slots:
        raise ValueError('KV3 array slots pointer is null')
    raw = _read_bytes(slots, 8 * count) if count else b''
    result = list(struct.unpack('<' + 'Q' * count, raw)) if count else []
    if any(not ptr for ptr in result):
        raise ValueError('KV3 array has null member')
    return result


def _decode(address: int, depth: int = 0) -> dict:
    kind, payload, raw = _value(address)
    result = {'kv3_type': _NAMES.get(kind, f'unknown_{kind}')}
    if kind == 2:
        result['value'] = bool(payload)
    elif kind == 3:
        result['value'] = struct.unpack('<q', raw[8:])[0]
    elif kind == 5:
        result['value'] = struct.unpack('<d', raw[8:])[0]
    elif kind == 6:
        result['value'] = _read_string(payload, 1024) if payload else ''
    elif kind == 8:
        entries = _array(payload)
        result['count'] = len(entries)
        if depth < 3:
            result['value'] = [_decode(ptr, depth + 1) for ptr in entries[:64]]
            if len(entries) > 64:
                result['truncated'] = True
    elif kind == 9:
        entries = _object(payload)
        result['count'] = len(entries)
        result['field_hashes'] = [f'{key:08x}' for key in entries]
    else:
        result['raw_hex'] = raw.hex()
    return result


def _path(field: str) -> list[str | int]:
    if not 1 <= len(field) <= 160:
        raise ValueError('field must be 1-160 characters')
    segments = field.split('.')
    if len(segments) > 8 or any(not _SEGMENT.fullmatch(part) for part in segments):
        raise ValueError('field must use dotted names and [index] selectors')
    path: list[str | int] = []
    for part in segments:
        path.append(part.split('[', 1)[0])
        path.extend(int(i) for i in _INDEX.findall(part))
    if len(path) > 12:
        raise ValueError('field path is too deep')
    return path


def _follow(root: int, path: list[str | int]) -> int:
    current = root
    for part in path:
        kind, payload, _ = _value(current)
        if isinstance(part, str):
            if kind != 9:
                raise ValueError(f'{part} requires a KV3 object')
            current = _object(payload).get(_hash_name(part), 0)
            if not current:
                raise KeyError(f'field {part} is absent from live node')
        else:
            if kind != 8:
                raise ValueError(f'[{part}] requires a KV3 array')
            entries = _array(payload)
            if part >= len(entries):
                raise IndexError(f'index {part} outside array length {len(entries)}')
            current = entries[part]
    return current


def cs2_particle_editor_value(category: int, index: int, field: str = '') -> dict:
    """Read live function values, including unsaved edits; optionally follow a named path.

    category 0-6, index within that group. Empty field lists Schema properties.
    Example: m_InputValue.m_flLiteralValue or m_vecTexturesInput[0].m_hTexture.
    Complex objects expose hashes until their named path is known. Never writes.
    """
    if not 0 <= category <= 6 or not 0 <= index < 10000:
        return {'ok': False, 'error': 'category must be 0-6 and index must be 0-9999'}
    try:
        path = _path(field) if field else []
        doc = cs2_editor_document('pet')
        if not doc.get('ok'):
            raise RuntimeError(doc.get('error', 'no active Pet document'))
        module = _tool_module('pet')
        if module.get('cls') != 'CPetApp':
            raise RuntimeError('Pet App RTTI validation failed')
        base = module['base']
        nt = base + _read_int(base + 0x3C, 'u32')
        if (_read_int(nt + 8, 'u32'), _read_int(nt + 0x50, 'u32')) != (0x6AC7FFFE, 0xA76000):
            raise RuntimeError('unsupported pet.dll build; offsets need revalidation')
        root = int(doc['root'], 16)
        vec = root + 0x30 + 0x18 * category
        count, array = _read_int(vec, 'u32'), _read_int(vec + 8, 'u64')
        cap = _read_int(vec + 16, 'u32') & 0x3FFFFFFF
        if count > 10000 or count > cap or (count and not array):
            raise ValueError('Pet function vector failed validation')
        if index >= count:
            raise IndexError(f'index {index} outside category length {count}')
        node = _read_int(array + 8 * index, 'u64')
        if not node or _editor_session_class(node, module) != 'CPetFunctionNode':
            raise ValueError('Pet function node RTTI validation failed')
        response = get_session().pipe.call('call_virtual', {
            'this': hex(node), 'vtable_offset': 144, 'args': [], 'on_main_thread': False})
        if 'error' in response:
            raise RuntimeError(str(response['error']))
        name_ptr = response['result']['ret']
        cls = _read_string(name_ptr, 256) if name_ptr else ''
        info = cs2_particle_function_info(cls)
        if not info.get('ok') or info['category'] != category:
            raise ValueError(f'function class {cls} mismatches particle catalog')
        val = node + 0x20
        if _value(val)[0] != 9:
            raise ValueError('function parameters are not a KV3 object')
        result = {'ok': True, 'scope': 'live editor memory; includes unsaved state',
                  'session': doc['session'], 'category': category, 'index': index,
                  'class_name': cls, 'field': field}
        if path:
            if path[0] not in {row['name'] for row in info['fields']}:
                raise ValueError(f'{path[0]} is not a catalog field of {cls}')
            result.update(_decode(_follow(val, path)))
        else:
            entries = _object(_value(val)[1])
            result['fields'] = [
                {'name': row['name'], 'schema_type': row['type'],
                 **(_decode(entries[_hash_name(row['name'])]) if _hash_name(row['name']) in entries
                    else {'present': False})}
                for row in info['fields']]
            result['field_count'] = len(result['fields'])
        after = cs2_editor_document('pet')
        if not after.get('ok') or after['session'] != doc['session'] or after['root'] != doc['root']:
            raise RuntimeError('active Particle Editor document changed during read')
        return result
    except (ConnectionError, RuntimeError, ValueError, KeyError, IndexError, OSError) as error:
        return {'ok': False, 'error': f'{type(error).__name__}: {error}'}
