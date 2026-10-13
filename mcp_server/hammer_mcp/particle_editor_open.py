"""Open a source particle document through Pet's native file-open method."""
from __future__ import annotations

from pathlib import Path

from .bindings import cs2_editor_document, _tool_module
from .session import get_session


def cs2_particle_editor_open(path: str, confirm: bool = False) -> dict:
    """Open an existing add-on text .vpcf as a separate Particle Editor session.

    This invokes CPetApp's native file-open virtual method on the main thread.
    The default is a preview; confirm=True opens the file and validates the
    resulting live document/root. Existing sessions remain open.
    """
    try:
        source = Path(path).resolve(strict=True)
        if not source.is_file() or source.suffix.lower() != '.vpcf':
            raise ValueError('path must name an existing .vpcf file')
        parts = [part.lower() for part in source.parts]
        if not any(parts[i:i + 2] == ['content', 'csgo_addons']
                   and len(parts) > i + 3 for i in range(len(parts) - 1)):
            raise ValueError('source must be inside content/csgo_addons/<addon>')
        with source.open('rb') as handle:
            header = handle.read(256).lstrip().lower()
        if not header.startswith(b'<!-- kv3 ') or b'format:vpcf' not in header:
            raise ValueError('source is not a text KV3 Particle Editor file')
        if not confirm:
            return {'ok': True, 'preview': True, 'path': str(source),
                    'action': 'open in active Particle Editor'}
        module = _tool_module('pet')
        if module.get('cls') != 'CPetApp' or not module.get('tool_system'):
            raise RuntimeError('Pet App RTTI validation failed')
        response = get_session().pipe.call('call_virtual', {
            'this': hex(module['tool_system']), 'vtable_offset': 144,
            'args': ['str:' + str(source), 1], 'on_main_thread': True,
            'timeout_ms': 20000,
        })
        if 'error' in response:
            raise RuntimeError(str(response['error']))
        result = response['result']
        if result.get('main_thread_status') != 0 or not result.get('ret'):
            raise RuntimeError(f'native open failed: {result}')
        document = cs2_editor_document('pet')
        if not document.get('ok') or int(document['session'], 16) != int(result['ret']):
            raise RuntimeError(f'opened session could not be read back: {document}')
        return {'ok': True, 'path': str(source), 'session': document['session'],
                'document': document['document'], 'root': document['root']}
    except (OSError, ConnectionError, RuntimeError, ValueError, KeyError) as error:
        return {'ok': False, 'path': path,
                'error': f'{type(error).__name__}: {error}'}
