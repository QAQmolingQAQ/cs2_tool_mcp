"""Versioned lookup of particle functions and reflected editable properties."""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path

_CATALOG = Path(__file__).with_name('data') / 'particle_functions.json'


@lru_cache(maxsize=1)
def _catalog() -> dict:
    return json.loads(_CATALOG.read_text(encoding='utf-8'))


def _category_id(value: str, names: list[str]) -> int | None:
    value = value.strip()
    if not value:
        return None
    if value.isdigit() and 0 <= int(value) < len(names):
        return int(value)
    for index, name in enumerate(names):
        if name.casefold() == value.casefold():
            return index
    raise ValueError('category must be 0-6 or one of: ' + ', '.join(names))


def cs2_particle_functions(category: str = '', query: str = '', offset: int = 0,
                           limit: int = 50) -> dict:
    """Search all 376 Particle Editor functions by category, display name, or class.

    Returns version metadata for the exact particles.dll build used for extraction.
    This read-only catalog works without a live editor connection; use
    cs2_particle_function_info to inspect editable properties and their types.
    """
    data = _catalog()
    try:
        category_id = _category_id(category, data['categories'])
    except ValueError as error:
        return {'ok': False, 'error': str(error)}
    if offset < 0 or not 1 <= limit <= 100:
        return {'ok': False, 'error': 'offset must be >= 0 and limit must be 1-100'}
    needle = query.strip().casefold()
    matches = [row for row in data['functions']
               if (category_id is None or row['category'] == category_id)
               and (not needle or needle in row['display_name'].casefold()
                    or needle in row['class_name'].casefold())]
    page = [{**row, 'category_name': data['categories'][row['category']]}
            for row in matches[offset:offset + limit]]
    return {'ok': True, 'source_sha256': data['sha256'], 'file_size': data['file_size'],
            'categories': data['categories'], 'total': len(matches),
            'offset': offset, 'limit': limit, 'functions': page}


def cs2_particle_function_info(class_name: str) -> dict:
    """Return one particle function's own and inherited editable properties.

    Supply the exact C_OP_*/C_INIT_*/C_OP_Render* class returned by
    cs2_particle_functions. Field type, friendly label, choice and range
    annotations come from particles.dll SchemaClassInfo. This is a schema
    reference, not a claim that every function has a written usage tutorial.
    """
    data = _catalog()
    row = next((item for item in data['functions']
                if item['class_name'] == class_name), None)
    if row is None:
        return {'ok': False, 'error': f'unknown particle function class: {class_name}'}
    fields = []
    classes = data['classes']
    current = class_name
    inheritance = []
    while current:
        entry = classes.get(current)
        if entry is None or current in inheritance:
            return {'ok': False, 'error': f'catalog inheritance error at {current}'}
        inheritance.append(current)
        fields.extend({**field, 'declared_in': current} for field in entry['fields'])
        current = entry['parent']
    return {'ok': True, 'source_sha256': data['sha256'],
            'category': row['category'],
            'category_name': data['categories'][row['category']],
            'index': row['index'], 'display_name': row['display_name'],
            'class_name': class_name, 'class_size': row['class_size'],
            'inheritance': inheritance, 'field_count': len(fields), 'fields': fields}
