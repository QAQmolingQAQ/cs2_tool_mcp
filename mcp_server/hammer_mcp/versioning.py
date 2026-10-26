"""Inspect installation and pipe identity; refuse unverified native operations."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from .process_snapshot import pipe_snapshot

SAFE_METHODS = frozenset(('ping', 'list_tools', 'get_status', 'list_modules', 'get_module',
    'read_memory', 'read_qword', 'read_value', 'read_string', 'read_ptr_chain',
    'find_pattern', 'scan_heap', 'list_interfaces', 'module_interfaces', 'main_thread_selftest', 'qt_widgets_snapshot', 'qt_menu_actions', 'qt_hammer_outliner'))
STABLE_UI_METHODS = frozenset(('qt_open_editor', 'qt_hammer_open_dialog', 'qt_file_dialog_map', 'qt_hammer_probe_action', 'qt_hammer_outliner_select', 'qt_hammer_targetname_probe'))  # fixed Qt ABI adapter; no editor RVAs
MANIFEST = Path(__file__).with_name('data') / 'native_compatibility.json'


def implementation_hash() -> str:
    root = Path(__file__).parent
    files = sorted([*root.glob('*.py'), *root.glob('data/*.json')])
    digest = hashlib.sha256()
    for path in files:
        if path == MANIFEST:
            continue
        digest.update(path.relative_to(root).as_posix().encode() + b'\0')
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def steam_version(game: Path) -> dict:
    result = {}
    for line in (game / 'game/csgo/steam.inf').read_text(encoding='utf-8-sig').splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            if key.strip() in ('ClientVersion', 'ServerVersion', 'PatchVersion', 'SourceRevision', 'VersionDate', 'VersionTime'):
                result[key.strip()] = value.strip()
    return result


def evaluate_native(version: dict, live: dict, bridge: dict, implementation: str, profiles: list) -> dict:
    """Pure gate evaluator. Observation alone never creates a verified profile."""
    failures = []
    for profile in profiles:
        reasons = []
        if profile.get('source_revision') != version.get('SourceRevision') or not version.get('SourceRevision'):
            reasons.append('game_revision_mismatch')
        if not bridge.get('bridge_version') or profile.get('bridge_version') != bridge.get('bridge_version'):
            reasons.append('bridge_version_mismatch')
        if bridge.get('bridge_api_version') != 1 or bridge.get('protocol_version') != 1:
            reasons.append('bridge_api_or_protocol_mismatch')
        if bridge.get('pid') != live.get('pid'):
            reasons.append('bridge_pid_mismatch')
        if profile.get('implementation_sha256') != implementation:
            reasons.append('python_implementation_mismatch')
        if profile.get('verification') != 'write_readback_undo_redo' or not profile.get('evidence'):
            reasons.append('verification_evidence_missing')
        hashes = profile.get('module_hashes', {})
        modules = live.get('modules', {})
        for required in ('cs2.exe', 'cs2_tool.dll'):
            if required not in modules:
                reasons.append('required_module_missing:' + required)
        for name, module in modules.items():
            if hashes.get(name) != module.get('sha256'):
                reasons.append('module_hash_mismatch:' + name)
            if not module.get('loaded_matches_disk_headers'):
                reasons.append('loaded_disk_header_mismatch:' + name)
        if not reasons:
            return {'writes_enabled': True, 'profile': profile['id'], 'allowed_methods': profile.get('allowed_methods', []), 'reasons': []}
        failures.append({'profile': profile.get('id'), 'reasons': reasons})
    return {'writes_enabled': False, 'allowed_methods': [],
            'reasons': ['no_matching_verified_native_profile'], 'profile_failures': failures}


def inspect_live(pipe) -> dict:
    response = pipe.call('ping')
    if 'error' in response:
        raise OSError(response['error'])
    bridge = response['result']
    live = pipe_snapshot(pipe)
    executable = live['modules'].get('cs2.exe')
    if executable is None:
        raise ValueError('pipe server is not a CS2 process')
    game = Path(executable['path']).parents[3]
    version = steam_version(game)
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    if manifest.get('version') != 1:
        raise ValueError('unsupported native compatibility manifest')
    implementation = implementation_hash()
    gate = evaluate_native(version, live, bridge, implementation, manifest['profiles'])
    return {'bridge': bridge, 'live': live, 'game_root': str(game), 'game_version': version,
            'implementation_sha256': implementation, **gate}


class NativeVersionError(PermissionError):
    pass


def guard_native_request(pipe, method: str, params: dict | None):
    if method in SAFE_METHODS or method in STABLE_UI_METHODS:
        return
    try:
        report = inspect_live(pipe)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise NativeVersionError(f'native request {method!r} blocked before dispatch: cannot verify live version ({exc})') from exc
    if not report['writes_enabled'] or method not in report['allowed_methods']:
        raise NativeVersionError(f'native request {method!r} blocked before dispatch: no verified compatibility permission; run cs2_session_selfcheck')
    return {'profile': report['profile'], 'pid': report['live']['pid'],
            'bridge_api_version': 1, 'implementation_sha256': report['implementation_sha256']}
