"""Durable read-only conflict evidence. A matching baseline never grants writes."""
from __future__ import annotations

import json
from pathlib import Path
import re
from uuid import uuid4

from .project import load_project, sha256
from .session import get_session
from .versioning import inspect_live
from .hammer_layout import observe_live_layout


def file_evidence(path: Path) -> dict:
    def identity():
        s = path.stat()
        return [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns]
    before = identity()
    digest = sha256(path)
    if identity() != before:
        raise ValueError('file changed while hashing: ' + str(path))
    return {'path': str(path.resolve()), 'sha256': digest, 'identity': before}


def collect(project: dict) -> dict:
    source = Path(project['source'])
    config = Path(project['config_path'])
    evidence = {'config': file_evidence(config), 'source': file_evidence(source),
                'profile': project['profile'], 'addon': project['addon'], 'connected': False}
    if evidence['config']['sha256'] != project['config_sha256']:
        raise ValueError('project config changed after scope resolution')
    try:
        pipe = get_session().pipe
        live = inspect_live(pipe)
        evidence.update(connected=True, runtime=live)
        evidence['layout'] = observe_live_layout(pipe, live)
        # Detect module/process/code changes across the read, not merely PID reuse.
        if inspect_live(pipe) != live:
            raise ValueError('runtime identity changed during preflight')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        evidence['observation_error'] = str(exc)
    if file_evidence(source) != evidence['source'] or file_evidence(config) != evidence['config']:
        raise ValueError('source or config changed during preflight')
    return evidence


def compare(previous: dict, current: dict) -> list[str]:
    # Report top-level domains, preserving raw detail in both durable records.
    return [key + '_changed' for key in sorted(previous.keys() | current.keys())
            if previous.get(key) != current.get(key)]


def cs2_edit_preflight(config: str = '', profile: str = '', baseline_id: str = '',
                       expected_source_hash: str = '') -> dict:
    """Record/recheck project file, version and Hammer session conflict evidence.

    Read-only; safe_to_write is always false pending verified dirty/Undo/rollback.
    baseline_id is a returned UUID, never a caller-supplied filesystem path.
    """
    try:
        if baseline_id and not re.fullmatch('[0-9a-f]{32}', baseline_id):
            raise ValueError('baseline_id must be a lowercase UUID hex identifier')
        if expected_source_hash and not re.fullmatch('[0-9a-f]{64}', expected_source_hash):
            raise ValueError('expected_source_hash must be lowercase SHA-256')
        project = load_project(config, profile)
        root = Path(project['state_root']) / 'edit_preflights'
        previous = None
        if baseline_id:
            path = root / (baseline_id + '.json')
            if path.stat().st_size > 2 * 1024 * 1024:
                raise ValueError('baseline exceeds size bound')
            previous = json.loads(path.read_text(encoding='utf-8'))
            if (not isinstance(previous, dict) or previous.get('version') != 1
                    or previous.get('id') != baseline_id
                    or not isinstance(previous.get('evidence'), dict)):
                raise ValueError('invalid baseline schema or identity')
        evidence = collect(project)
        conflicts = compare(previous['evidence'], evidence) if previous else []
        if expected_source_hash and expected_source_hash != evidence['source']['sha256']:
            conflicts.append('expected_source_hash_mismatch')
        blockers = ['dirty_semantics_unverified', 'batch_apply_and_verified_rollback_unimplemented']
        if not evidence['connected'] or evidence.get('observation_error'):
            blockers.append('live_observation_unavailable')
        layout = evidence.get('layout', {})
        if layout.get('direct_document_unsaved_changes'):
            blockers.append('direct_document_unsaved_changes_observed')
        docs = layout.get('sessions', [])
        if len(docs) != 1 or not docs[0].get('document_path') or (
                Path(docs[0]['document_path']).resolve() != Path(project['source']).resolve()):
            blockers.append('configured_map_not_uniquely_open')
        runtime = evidence.get('runtime', {})
        if runtime.get('bridge', {}).get('addon') != project['addon']:
            blockers.append('active_addon_mismatch_or_unknown')
        if not runtime.get('writes_enabled'):
            blockers.append('native_write_profile_unavailable')
        identifier = uuid4().hex
        result = {'version': 1, 'id': identifier, 'baseline_id': baseline_id or None,
                  'ok': True, 'safe_to_write': False, 'atomic_snapshot': False,
                  'conflict_check': 'conflicts' if conflicts else 'matched' if previous else 'baseline_only',
                  'conflicts': conflicts, 'blockers': blockers, 'evidence': evidence}
        root.mkdir(parents=True, exist_ok=True)
        with (root / (identifier + '.json')).open('x', encoding='utf-8') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
        return result
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {'ok': False, 'safe_to_write': False, 'error': f'{type(exc).__name__}: {exc}'}
