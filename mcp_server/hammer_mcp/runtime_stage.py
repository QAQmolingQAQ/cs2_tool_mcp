"""Explicit per-project installation of unique test VPKs; never overwrite a map."""
import json
import os
from pathlib import Path
import re
import shutil
from uuid import uuid4

from .build_artifact import verify_map_artifact
from .build_jobs import atomic_json
from .edit_preflight import file_evidence
from .operation_lock import operation_lock
from .project import load_project, sha256, within


def publish_new(source: Path, target: Path, digest: str) -> None:
    before = file_evidence(source)
    if before['sha256'] != digest:
        raise ValueError('source artifact hash mismatch')
    candidate = target.with_name(target.name+'.stage.'+uuid4().hex+'.pending')
    try:
        with source.open('rb') as reader, candidate.open('xb') as writer:
            shutil.copyfileobj(reader, writer, 1024*1024)
            writer.flush(); os.fsync(writer.fileno())
        if sha256(candidate) != digest or file_evidence(source) != before:
            raise ValueError('artifact changed while staging')
        # Same-directory atomic publication without replacing a pre-existing path.
        os.link(candidate, target)
    finally:
        candidate.unlink(missing_ok=True)


def cs2_runtime_stage_build(job_id: str, config: str = '', profile: str = '',
                            confirm: bool = False, expected_artifact_hash: str = '') -> dict:
    """Preview/install one verified test build into an explicitly configured maps directory.

    Requires profile.runtime.staging_root. Unique flat mcp_ names only; existing
    files never overwritten. Does not mount or load the map, or certify release.
    """
    try:
        if not isinstance(confirm, bool):raise ValueError('confirm must be bool')
        if not re.fullmatch('[0-9a-f]{32}', job_id):raise ValueError('invalid build job id')
        project = load_project(config, profile)
        if project['release'] or not project.get('runtime'):
            raise ValueError('explicit runtime settings on a non-release profile required')
        folder = within(Path(project['state_root'])/job_id, Path(project['state_root']))
        request = json.loads((folder/'request.json').read_text(encoding='utf-8'))
        state = json.loads((folder/'state.json').read_text(encoding='utf-8'))
        if request.get('job_id') != job_id or state.get('job_id') != job_id:
            raise ValueError('build request/state identity mismatch')
        if state['status'] != 'succeeded' or request['project']['source'] != project['source']:
            raise ValueError('successful build of the configured source required')
        if Path(request['project']['game_root']) != Path(project['game_root']):
            raise ValueError('build belongs to a different game installation')
        if sha256(Path(project['source'])) != request['source_sha256']:
            raise ValueError('source changed since build')
        game = Path(project['game_root'])
        if any(sha256(game/path) != digest for path,digest in request['installation_hashes'].items()):
            raise ValueError('installation changed since build')
        name = request['map_name']
        if not re.fullmatch('mcp_[0-9a-f]{24}', name):
            raise ValueError('flat unique runtime map name required; rebuild the source')
        source = within(Path(request['artifact']), Path(project['install_root']))
        validation = verify_map_artifact(str(source), name, request['mode'])
        if (not validation['ok'] or validation['sha256'] != state['validation']['sha256']
                or len(validation['storage_files']) != 1):
            raise ValueError('artifact validation/hash failed or split VPK staging unsupported')
        target = within(Path(project['runtime']['staging_root'])/(name+'.vpk'),
                        Path(project['runtime']['staging_root']))
        result = {'ok': True, 'preview': not confirm, 'job_id': job_id, 'map_name': name,
                  'source_sha256': request['source_sha256'],
                  'artifact_sha256': validation['sha256'], 'source': str(source), 'target': str(target),
                  'runtime_map_verified': False, 'release_ready': False}
        if not confirm:return result
        if expected_artifact_hash != validation['sha256']:
            raise ValueError('expected artifact hash required; preview again')
        with operation_lock('runtime-stage:'+str(target)):
            receipts = Path(project['state_root'])/'runtime_staging'
            receipts.mkdir(parents=True, exist_ok=True)
            receipt = receipts/(job_id+'.json')
            if target.exists():
                old = json.loads(receipt.read_text(encoding='utf-8')) if receipt.exists() else {}
                if (old.get('status') == 'staged' and old.get('target') == str(target)
                        and old.get('artifact_sha256') == validation['sha256'] and sha256(target) == validation['sha256']):
                    return {**result, 'status': 'already_staged', 'receipt_path': str(receipt)}
                raise FileExistsError('runtime target exists without a matching completed receipt; not overwritten')
            atomic_json(receipt, {**result, 'status': 'publishing_outcome_not_yet_verified'})
            publish_new(source, target, validation['sha256'])
            if sha256(target) != validation['sha256']:raise ValueError('published artifact readback failed')
            if (sha256(Path(project['source'])) != request['source_sha256']
                    or sha256(Path(project['config_path'])) != project['config_sha256']):
                raise ValueError('source/config changed during publication; pending receipt retained')
            result.update(status='staged', receipt_path=str(receipt))
            atomic_json(receipt, result)
        return result
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {'ok': False, 'runtime_map_verified': False, 'release_ready': False, 'error': str(exc)}
