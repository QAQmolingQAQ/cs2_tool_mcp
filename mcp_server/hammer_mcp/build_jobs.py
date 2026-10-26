"""Durable build requests and detached workers; no compiler wait in MCP calls."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import time
import uuid

from .build_process import process_identity, spawn_worker
from .operation_lock import operation_lock
from .project import DEFAULT_CONFIG, load_project, sha256, within

TERMINAL = frozenset(('succeeded', 'failed', 'cancelled', 'interrupted', 'source_changed', 'inputs_changed'))


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, data: dict):
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        deadline = time.monotonic() + 2
        while True:
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                # Windows readers briefly hold a non-delete-sharing file handle.
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.005)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def _state_root(config: str) -> Path:
    path = Path(config or os.environ.get('CS2_MCP_PROJECT', str(DEFAULT_CONFIG)))
    data = read_json(path) if path.exists() or config else {}
    return Path(data.get('state_root') or Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'CS2ToolMCP/builds').resolve()


def _job_directory(job_id: str, config: str) -> Path:
    if not re.fullmatch('[0-9a-f]{32}', job_id):
        raise ValueError('invalid job_id')
    return within(_state_root(config) / job_id, _state_root(config))


def _status(folder: Path) -> dict:
    state = read_json(folder / 'state.json')
    if state['status'] in TERMINAL:
        return state
    identity_file = folder / 'worker.json'
    if not identity_file.exists():
        identity_file = folder / 'launch.json'
    if identity_file.exists():
        identity = read_json(identity_file)
        try:
            alive = process_identity(identity['pid']) == identity['created']
        except OSError as exc:
            return {**state, 'observation_error': str(exc)}
        if alive:
            return {**state, 'worker': identity, 'cancel_requested': (folder / 'cancel.request').exists()}
        # Re-read after observing process death: the worker may have just committed success.
        state = read_json(folder / 'state.json')
        if state['status'] not in TERMINAL:
            state.update(status='interrupted', stage='interrupted', finished_at=now(),
                         error='worker exited without a terminal result; job-owned compiler processes are terminated')
            atomic_json(folder / 'state.json', state)
    elif time.time() - state['created_epoch'] > 30:
        state.update(status='interrupted', stage='interrupted', finished_at=now(), error='worker did not establish process identity')
        atomic_json(folder / 'state.json', state)
    return state


def cs2_build_status(job_id: str, config: str = '', log_bytes: int = 8192) -> dict:
    """Read durable job state and bounded log tail across MCP restarts."""
    try:
        if not 0 <= log_bytes <= 65536:
            raise ValueError('log_bytes must be between 0 and 65536')
        folder = _job_directory(job_id, config)
        state = _status(folder)
        log = folder / 'compiler.log'
        tail = ''
        if log.exists() and log_bytes:
            with log.open('rb') as stream:
                stream.seek(max(0, log.stat().st_size - log_bytes))
                tail = stream.read(log_bytes).decode('utf-8', errors='replace')
        return {'ok': True, **state, 'log_tail': tail}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {'ok': False, 'error': str(exc)}


def cs2_build_cancel(job_id: str, config: str = '') -> dict:
    """Request cancellation; cancelled is reported only after the process tree exits."""
    try:
        folder = _job_directory(job_id, config)
        with operation_lock('build-cancel:' + str(folder)):
            state = _status(folder)
            if state['status'] in TERMINAL:
                return {'ok': True, 'accepted': False, **state}
            (folder / 'cancel.request').touch(exist_ok=True)
            return {'ok': True, 'accepted': True, 'job_id': job_id,
                    'status': state['status'], 'cancel_requested': True}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {'ok': False, 'error': str(exc)}


def _plan(project: dict, mode: str, job_id: str) -> dict:
    if mode not in ('quick', 'full'):
        raise ValueError('mode must be quick or full')
    source = Path(project['source'])
    relative = Path('maps') / '__mcp_builds' / job_id / source.name
    snapshot = within(Path(project['source_root']) / relative, Path(project['source_root']))
    artifact = within((Path(project['install_root']) / relative).with_suffix('.vpk'), Path(project['install_root']))
    flags = ['-fshallow', '-world', '-phys', '-vis'] if mode == 'quick' else ['-f']
    game = Path(project['game_root'])
    installation = {relative: sha256(game / relative) for relative in (
        'game/csgo/steam.inf', 'game/csgo/gameinfo.gi', 'game/bin/win64/resourcecompiler.dll',
        'game/bin/win64/visbuilder.dll', 'game/bin/win64/vrad3.dll', 'game/bin/win64/vrad3.exe')
        if (game / relative).is_file()}
    return {'job_id': job_id, 'mode': mode, 'project': project, 'source': str(source),
            'source_sha256': sha256(source), 'snapshot': str(snapshot), 'artifact': str(artifact),
            'map_name': relative.with_suffix('').as_posix().removeprefix('maps/'),
            'command': [project['compiler'], '-nop4', '-i', str(snapshot), *flags],
            'compiler_sha256': sha256(Path(project['compiler'])),
            'installation_hashes': installation,
            'source_basis': 'saved_disk_snapshot', 'editor_dirty_state': 'not_inspected',
            'builders': ['world', 'phys', 'vis'] if mode == 'quick' else 'installed_game_defaults',
            'note': 'Builds use an isolated map copy; original VPK is not replaced. Dependencies are not frozen.'}


def cs2_build_start(mode: str = 'quick', config: str = '', profile: str = '',
                    confirm: bool = False, expected_source_hash: str = '') -> dict:
    """Preview or start an isolated disk-map build. Confirm requires preview source hash."""
    try:
        if os.name != 'nt':
            raise OSError('build jobs currently require Windows')
        project = load_project(config, profile)
        plan = _plan(project, mode, uuid.uuid4().hex)
        if not confirm:
            return {'ok': True, 'preview': True, **plan}
        if expected_source_hash != plan['source_sha256']:
            raise ValueError('source hash missing or changed; preview again and pass expected_source_hash')
        root = Path(project['state_root'])
        root.mkdir(parents=True, exist_ok=True)
        with operation_lock('build-source:' + project['source']):
            for folder in root.iterdir():
                if not folder.is_dir() or not re.fullmatch('[0-9a-f]{32}', folder.name):
                    continue
                if not (folder / 'state.json').exists():
                    continue  # No worker is spawned until initial state has been committed.
                old = _status(folder)
                if old.get('source', '').casefold() == plan['source'].casefold() and old['status'] not in TERMINAL:
                    return {'ok': False, 'error': 'source already has an active build', 'job_id': old['job_id'], 'status': old['status']}
            folder = root / plan['job_id']
            folder.mkdir()
            atomic_json(folder / 'request.json', plan)
            atomic_json(folder / 'state.json', {'job_id': plan['job_id'], 'source': plan['source'],
                'source_sha256': plan['source_sha256'], 'mode': mode, 'status': 'queued', 'stage': 'queued',
                'created_at': now(), 'created_epoch': time.time(), 'events': [], 'compiler_exit_code': None,
                'log_path': str(folder / 'compiler.log'), 'artifact': plan['artifact']})
            worker = Path(__file__).with_name('build_worker.py')
            try:
                identity = spawn_worker([sys.executable, str(worker), str(folder)], str(worker.parent))
            except OSError as exc:
                state = read_json(folder / 'state.json')
                state.update(status='failed', stage='failed', error=f'worker launch failed: {exc}', finished_at=now())
                atomic_json(folder / 'state.json', state)
                return {'ok': False, 'job_id': plan['job_id'], 'status': 'failed', 'error': state['error']}
            if identity['created'] is not None:
                atomic_json(folder / 'launch.json', identity)
            # Worker owns subsequent state writes. Never wait for compilation in MCP.
            return {'ok': True, 'preview': False, 'job_id': plan['job_id'], 'state_path': str(folder / 'state.json'),
                    'status': 'queued', 'source_sha256': plan['source_sha256'], 'artifact': plan['artifact']}
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        return {'ok': False, 'error': str(exc)}
