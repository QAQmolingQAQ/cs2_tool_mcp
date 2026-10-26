"""Explicit per-project scope for builds, installs and subsequent workflows."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / 'config/project.local.json'


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def within(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f'path is outside configured scope: {path}')
    return resolved


def load_project(config: str = '', profile: str = '') -> dict:
    path = Path(config or os.environ.get('CS2_MCP_PROJECT', str(DEFAULT_CONFIG))).resolve(strict=True)
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('version') != 1:
        raise ValueError('unsupported project config version')
    name = profile or data['active_profile']
    selected = data['profiles'][name]
    game_root = Path(data['game_root']).resolve(strict=True)
    addon = selected['addon']
    if not isinstance(addon, str) or not addon or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in addon):
        raise ValueError('invalid addon identifier')
    source_root = (game_root / 'content/csgo_addons' / addon).resolve(strict=True)
    install_root = (game_root / 'game/csgo_addons' / addon).resolve(strict=True)
    source = within(source_root / selected['map'], source_root)
    if source.suffix.lower() != '.vmap' or not source.is_file():
        raise ValueError('configured map must be an existing .vmap')
    compiler = game_root / 'game/bin/win64/resourcecompiler.exe'
    if not compiler.is_file():
        raise FileNotFoundError(compiler)
    state_root = Path(data.get('state_root') or Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'CS2ToolMCP/builds').resolve()
    if state_root.is_relative_to(source_root) or state_root.is_relative_to(install_root):
        raise ValueError('state_root must be outside game addon directories')
    return {'config_path': str(path), 'config_sha256': sha256(path), 'profile': name,
            'game_root': str(game_root), 'addon': addon, 'source_root': str(source_root),
            'install_root': str(install_root), 'source': str(source), 'compiler': str(compiler),
            'state_root': str(state_root), 'release': bool(selected.get('release', False))}


def cs2_project_info(config: str = '', profile: str = '') -> dict:
    """Resolve the configured test/release addon and map; never change editor state."""
    try:
        return {'ok': True, **load_project(config, profile)}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {'ok': False, 'error': f'{type(exc).__name__}: {exc}'}
