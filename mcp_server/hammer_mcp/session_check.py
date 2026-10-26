"""Installation and active pipe diagnostics, composed above the transport gate."""
import json
import os
from pathlib import Path
from .process_snapshot import WATCHED, disk_identity
from .project import DEFAULT_CONFIG
from .session import get_session
from .versioning import inspect_live, steam_version

def cs2_session_selfcheck(config: str = '') -> dict:
    """Report installed/live versions, DLL hashes, bridge identity and write gate."""
    result = {'ok': True, 'writes_enabled': False, 'current_map': None,
              'current_map_status': 'not_read_without_verified_offsets'}
    try:
        path = Path(config or os.environ.get('CS2_MCP_PROJECT', str(DEFAULT_CONFIG)))
        data = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
        game = Path(data.get('game_root') or os.environ.get('CS2_GAME_ROOT',
            r'C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive'))
        result['installed_game_version'] = steam_version(game)
        result['installed_modules'] = {}
        for name in sorted(WATCHED - {'cs2_tool.dll'}):
            candidates = (game / 'game/bin/win64' / name, game / 'game/bin/win64/tools' / name)
            found = [path for path in candidates if path.is_file()]
            if len(found) == 1:
                result['installed_modules'][name] = disk_identity(found[0])
            elif len(found) > 1:
                result.setdefault('installation_issues', []).append('ambiguous module path: ' + name)
        selected = data.get('profiles', {}).get(data.get('active_profile'), {})
        result['configured_project'] = {'addon': selected.get('addon'), 'map': selected.get('map'),
                                        'role': 'configuration_only_not_current_editor_state'}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result['installation_error'] = str(exc)
    try:
        result.update(inspect_live(get_session().pipe), connected=True)
        result['active_addon'] = result['bridge'].get('addon') or None
        result['launch_map'] = result['bridge'].get('launch_map') or None
        if 'hammer.dll' in result['live']['modules']:
            try:
                from .hammer_layout import observe_live_layout
                observation=observe_live_layout(get_session().pipe,result)
                documents=[row for row in observation['sessions'] if row.get('document_path')]
                result['open_hammer_documents']=documents
                result['hammer_dirty_state']='unknown'
                if len(documents)==1 and observation['session_count_candidate']==1:
                    result['current_map']=documents[0]['document_path']
                    result['current_map_status']='single_open_hammer_document_read_only_verified_identity'
                elif observation['session_count_candidate']==0:
                    result['current_map_status']='no_open_hammer_documents_observed'
                else:
                    result['current_map_status']='multiple_or_pathless_documents_active_document_unknown'
            except (OSError,ValueError,KeyError,TypeError) as exc:
                result['current_map_status']='read_only_layout_unavailable'
                result['current_map_error']=str(exc)

    except (OSError, ValueError, KeyError, TypeError) as exc:
        result.update(connected=False, connection_or_version_error=str(exc), writes_enabled=False)
    return result
