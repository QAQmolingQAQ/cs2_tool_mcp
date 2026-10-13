"""Read the live, possibly unsaved Particle Editor function tree."""
from __future__ import annotations

from .bindings import cs2_editor_document, _tool_module, _editor_session_class
from .runtime import _read_int, _read_string
from .session import get_session

_CATEGORIES = (
    'Pre-Emission Operators', 'Emitters', 'Initializers', 'Operators',
    'Force Generators', 'Constraints', 'Renderers', 'Children', 'Named Value Locals',
)


def cs2_particle_editor_tree(category: int = -1, limit_per_category: int = 50) -> dict:
    """List live Particle Editor function/child nodes, including unsaved changes.

    Reads CPetDoc's validated root and its nine native node vectors. Category
    -1 lists all groups; 0-8 selects one. Returns per-group counts even when
    the node list is truncated. This does not modify or save the document.
    """
    if category < -1 or category >= len(_CATEGORIES):
        return {'ok': False, 'error': 'category must be -1 or 0-8'}
    if not 0 <= limit_per_category <= 100:
        return {'ok': False, 'error': 'limit_per_category must be 0-100'}
    try:
        document = cs2_editor_document('pet')
        if not document.get('ok'):
            raise RuntimeError(document.get('error', 'no active Pet document'))
        module = _tool_module('pet')
        if module.get('cls') != 'CPetApp':
            raise RuntimeError('Pet App RTTI validation failed')
        root = int(document['root'], 16)
        groups = []
        selected = range(9) if category == -1 else (category,)
        for group_id in selected:
            vector = root + 0x30 + 0x18 * group_id
            count = _read_int(vector, 'u32')
            array = _read_int(vector + 8, 'u64')
            capacity = _read_int(vector + 16, 'u32') & 0x3fffffff
            if count > 10000 or count > capacity or (count and not array):
                raise RuntimeError(f'category {group_id} vector failed validation')
            nodes = []
            for index in range(min(count, limit_per_category)):
                node = _read_int(array + 8 * index, 'u64')
                if not node:
                    raise RuntimeError(f'category {group_id} node {index} is null')
                node_type = _editor_session_class(node, module)
                if not node_type:
                    raise RuntimeError(f'category {group_id} node {index} failed RTTI')
                item = {'index': index, 'address': hex(node), 'node_type': node_type}
                if group_id <= 6:
                    if node_type != 'CPetFunctionNode':
                        raise RuntimeError(f'category {group_id} node {index} has type {node_type}')
                    response = get_session().pipe.call('call_virtual', {
                        'this': hex(node), 'vtable_offset': 144, 'args': [],
                        'on_main_thread': False,
                    })
                    if 'error' in response:
                        raise RuntimeError(str(response['error']))
                    name_ptr = response['result']['ret']
                    item['class_name'] = _read_string(name_ptr, 256) if name_ptr else ''
                    if not item['class_name']:
                        raise RuntimeError(f'category {group_id} node {index} has no class name')
                nodes.append(item)
            groups.append({'category': group_id, 'category_name': _CATEGORIES[group_id],
                           'count': count, 'capacity': capacity, 'returned': len(nodes), 'nodes': nodes})
        return {'ok': True, 'session': document['session'], 'document': document['document'],
                'root': document['root'], 'scope': 'live editor memory; includes unsaved state',
                'groups': groups}
    except (ConnectionError, RuntimeError, ValueError, KeyError, OSError) as error:
        return {'ok': False, 'error': f'{type(error).__name__}: {error}'}
