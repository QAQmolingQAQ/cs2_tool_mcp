"""Compare one live Pet function value with a caller-supplied saved source file."""
from __future__ import annotations

import math
from pathlib import Path

from .asset_tree import _HEADER, _MAX_BYTES, _Parser, _tokens
from .particle_editor_value import _path, cs2_particle_editor_value
from .bindings import cs2_editor_document
from .runtime import _read_int, _read_string

_SOURCE_GROUPS = (
    'm_PreEmissionOperators', 'm_Emitters', 'm_Initializers', 'm_Operators',
    'm_ForceGenerators', 'm_Constraints', 'm_Renderers',
)


def _plain_live(row: dict):
    kind = row.get('kv3_type')
    if kind in ('bool', 'int', 'double', 'string'):
        return row['value']
    if kind == 'array' and 'value' in row and not row.get('truncated'):
        return [_plain_live(item) for item in row['value']]
    raise ValueError('compare a supported scalar or fully expanded array leaf')


def _equal(left, right) -> bool:
    if isinstance(right, dict) and set(right) == {'type', 'value'}:
        right = right['value']
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(_equal(a, b) for a, b in zip(left, right))
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isclose(left, right, rel_tol=1e-6, abs_tol=1e-7)
    return left == right


def cs2_particle_editor_compare(path: str, category: int, index: int,
                                field: str) -> dict:
    """Compare one live Pet value with the same path in a supplied saved .vpcf.

    The supplied path must match the active CPetSession backing source path.
    A class mismatch is rejected. Missing source fields may be defaults and
    are not called edits.
    """
    try:
        parts = _path(field)
        if not 0 <= category <= 6 or not 0 <= index < 10000:
            raise ValueError('category must be 0-6 and index must be 0-9999')
        source = Path(path).resolve(strict=True)
        if not source.is_file() or source.suffix.lower() != '.vpcf':
            raise ValueError('expected a source .vpcf file')
        if source.stat().st_size > _MAX_BYTES:
            raise ValueError('source exceeds 8 MiB')
        text = source.read_text(encoding='utf-8-sig')
        header = _HEADER.match(text)
        if not header or header.group(1).lower() != 'vpcf':
            raise ValueError('expected text KV3 vpcf header')
        tree = _Parser(_tokens(text)).parse()
        if not isinstance(tree, dict):
            raise ValueError('VPCF root must be an object')
        nodes = tree.get(_SOURCE_GROUPS[category], [])
        if not isinstance(nodes, list) or index >= len(nodes) or not isinstance(nodes[index], dict):
            raise IndexError('source function index is absent')
        saved = nodes[index]
        live = cs2_particle_editor_value(category, index, field)
        if not live.get('ok'):
            raise RuntimeError(live.get('error', 'live Pet read failed'))
        if saved.get('_class') != live['class_name']:
            raise ValueError('source and live function classes differ at this category/index')
        context = cs2_editor_document('pet')
        if not context.get('ok') or context['session'] != live['session']:
            raise RuntimeError('active Pet session changed during source check')
        session = int(live['session'], 16)
        name_ptr = _read_int(session + 0x58, 'u64')
        backing = _read_string(name_ptr, 1024) if name_ptr else ''
        if not backing or str(Path(backing).resolve()).casefold() != str(source).casefold():
            raise ValueError('supplied source path does not match active Pet session')
        after = cs2_editor_document('pet')
        if not after.get('ok') or after['session'] != live['session']:
            raise RuntimeError('active Pet session changed during backing path read')
        current = saved
        try:
            for part in parts:
                current = current[part]
        except (KeyError, IndexError, TypeError):
            return {'ok': True, 'comparable': False, 'reason': 'field absent from saved source; may use a default',
                    'source_path': str(source), 'category': category, 'index': index,
                    'class_name': live['class_name'], 'field': field,
                    'source_file_verified_as_active': True, 'live': live}
        plain = _plain_live(live)
        if isinstance(current, dict) and set(current) == {'type', 'value'}:
            saved_value = current['value']
            source_type = current['type']
        else:
            saved_value = current
            source_type = None
        return {'ok': True, 'comparable': True, 'equal': _equal(plain, saved_value),
                'source_path': str(source), 'source_file_verified_as_active': True,
                'category': category, 'index': index, 'class_name': live['class_name'],
                'field': field, 'live_value': plain, 'saved_value': saved_value,
                'saved_type_tag': source_type, 'session': live['session'],
                'scope': 'live editor memory versus active session backing source file'}
    except (OSError, UnicodeError, ValueError, KeyError, IndexError, TypeError, RuntimeError) as error:
        return {'ok': False, 'error': f'{type(error).__name__}: {error}'}
