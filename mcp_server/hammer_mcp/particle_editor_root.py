"""Read-only Base Properties from the active Particle Editor root."""
from __future__ import annotations

from .bindings import cs2_editor_document, _tool_module, _editor_session_class
from .particle_editor_value import _path, _follow, _decode, _value, _object, _hash_name
from .runtime import _read_int

# Names verified against the local source and the corresponding live root.
_KNOWN_FIELDS = (
    '_class', 'm_nInitialParticles', 'm_nMaxParticles', 'm_ConstantColor',
    'm_BoundingBoxMin', 'm_BoundingBoxMax', 'm_flConstantRadius',
    'm_flConstantLifespan', 'm_bShouldSort', 'm_bInfiniteBounds',
    'm_nConstantSequenceNumber', 'm_nConstantSequenceNumber1',
    'm_nBehaviorVersion', 'm_nFirstMultipleOverride_BackwardCompat',
)


def cs2_particle_editor_root_value(field: str = '') -> dict:
    """Read live Particle Editor Base Properties, such as max particles and color.

    Supply a bounded named path, e.g. m_ConstantColor[0] or m_flConstantRadius.
    Empty field lists a verified subset of named fields and all live key hashes.
    KV3 types are runtime storage types; there is no complete root Schema export.
    Function lists and child nodes are queried with cs2_particle_editor_tree.
    Never writes or saves the particle.
    """
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
        if _editor_session_class(root, module) != 'CPetRootNode':
            raise ValueError('Pet root RTTI validation failed')
        val = root + 0x20
        if _value(val)[0] != 9:
            raise ValueError('root Base Properties are not a KV3 object')
        cls = _decode(_follow(val, ['_class'])).get('value')
        if cls != 'CParticleSystemDefinition':
            raise ValueError('unexpected root definition class')
        result = {
            'ok': True, 'scope': 'live editor Base Properties; read-only',
            'session': doc['session'], 'root': doc['root'],
            'class_name': cls, 'field': field,
            'type_source': 'live KV3 storage, not a complete Schema declaration',
        }
        if path:
            result.update(_decode(_follow(val, path)))
        else:
            entries = _object(_value(val)[1])
            result['live_field_count'] = len(entries)
            result['field_hashes'] = [f'{key:08x}' for key in entries]
            result['known_fields'] = [
                {'name': name,
                 **(_decode(entries[_hash_name(name)]) if _hash_name(name) in entries
                    else {'present': False})}
                for name in _KNOWN_FIELDS
            ]
            result['named_list_complete'] = False
        after = cs2_editor_document('pet')
        if not after.get('ok') or any(after[key] != doc[key] for key in ('session', 'root')):
            raise RuntimeError('active Particle Editor document changed during read')
        return result
    except (ConnectionError, RuntimeError, ValueError, KeyError, IndexError, OSError) as error:
        return {'ok': False, 'error': f'{type(error).__name__}: {error}'}
