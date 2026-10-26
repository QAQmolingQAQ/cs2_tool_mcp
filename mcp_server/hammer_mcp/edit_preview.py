"""Saved-source batch plans with explicit compare-and-set expectations."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from uuid import uuid4

from .build_jobs import atomic_json
from .edit_preflight import cs2_edit_preflight, file_evidence
from .project import load_project, sha256
from .source_parsing import map_entities


def plan_properties(entities: list[dict], operations: list) -> list[dict]:
    if not isinstance(operations, list) or not 1 <= len(operations) <= 256:
        raise ValueError('operations must contain between 1 and 256 items')
    by_id = {}
    for entity in entities:
        if entity['id'] in by_id:
            raise ValueError('ambiguous entity id')
        by_id[entity['id']] = entity
    results, touched = [], set()
    for index, operation in enumerate(operations):
        row = {'index': index, 'status': 'invalid', 'executed': False}
        results.append(row)
        if not isinstance(operation, dict) or set(operation) != {'entity_id', 'property', 'expected', 'value'}:
            row['error'] = 'expected entity_id, property, expected and value only'
            continue
        if not all(isinstance(v, str) for v in operation.values()):
            row['error'] = 'all operation fields must be strings'
            continue
        identifier, key = operation['entity_id'], operation['property'].casefold()
        row.update(entity_id=identifier, property=key, expected=operation['expected'], after=operation['value'])
        if not key or key in ('id', 'classname') or any(ord(c) < 32 for c in key) or any(
                '\0' in v or len(v) > 16384 for v in operation.values()):
            row['error'] = 'unsupported property or oversized/invalid text'
            continue
        pair = (identifier, key)
        if pair in touched:
            row['error'] = 'duplicate target property in batch'
            continue
        touched.add(pair)
        entity = by_id.get(identifier)
        if entity is None or key not in entity['properties']:
            row['error'] = 'entity or existing property not found'
            continue
        before = entity['properties'][key]
        row['before'] = before
        row['status'] = ('conflict' if before != operation['expected'] else
                         'no_change' if before == operation['value'] else 'planned')
    return results


def cs2_edit_preview(operations_json: str, expected_source_hash: str,
                     config: str = '', profile: str = '', baseline_id: str = '') -> dict:
    """Preview up to 256 existing entity-property changes against a saved map copy.

    operations_json: [{entity_id,property,expected,value}], all string fields.
    No operations execute. Unsaved editor contents are not represented by disk.
    """
    try:
        if len(operations_json) > 1024 * 1024:
            raise ValueError('operations JSON exceeds 1 MiB')
        operations = json.loads(operations_json)
        # Bound the batch before starting a converter or writing evidence.
        plan_properties([], operations)
        if len(expected_source_hash) != 64 or any(c not in '0123456789abcdef' for c in expected_source_hash):
            raise ValueError('expected_source_hash must be lowercase SHA-256')
        project = load_project(config, profile)
        first = cs2_edit_preflight(config, profile, baseline_id, expected_source_hash)
        if not first.get('ok'):
            raise ValueError('preflight failed: ' + first.get('error', 'unknown'))
        if (first['evidence']['config']['sha256'] != project['config_sha256']
                or Path(first['evidence']['source']['path']) != Path(project['source'])
                or first['evidence']['profile'] != project['profile']):
            raise ValueError('project scope changed before preview')
        if first['conflicts']:
            return {'ok': False, 'safe_to_write': False, 'executed_count': 0,
                    'error': 'preflight conflict', 'preflight': first}
        source = Path(project['source'])
        folder = Path(project['state_root']) / 'edit_plans' / uuid4().hex
        folder.mkdir(parents=True)
        snapshot, output = folder/'input.vmap', folder/'map.kv2'
        shutil.copyfile(source, snapshot)
        if sha256(snapshot) != expected_source_hash or file_evidence(source) != first['evidence']['source']:
            raise ValueError('map changed while taking plan snapshot')
        converter = Path(project['game_root'])/'game/bin/win64/dmxconvert.exe'
        converter_identity = file_evidence(converter)
        run = subprocess.run([str(converter), '-i', str(snapshot), '-o', str(output), '-oe', 'keyvalues2'],
                             cwd=converter.parent, capture_output=True, timeout=120,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        (folder/'conversion.log').write_bytes(run.stdout + run.stderr)
        if run.returncode or not output.is_file():
            raise ValueError('snapshot conversion failed: ' + str(folder/'conversion.log'))
        if output.stat().st_size > 128 * 1024 * 1024:
            raise ValueError('converted map exceeds parser bound')
        rows = plan_properties(map_entities(output.read_text(encoding='utf-8-sig')), operations)
        second = cs2_edit_preflight(config, profile, first['id'], expected_source_hash)
        if not second.get('ok'):
            raise ValueError('post-preview preflight failed')
        if sha256(snapshot) != expected_source_hash:
            raise ValueError('inspection snapshot changed during preview')
        if file_evidence(converter) != converter_identity:
            raise ValueError('converter changed during preview')
        valid = all(row['status'] in ('planned', 'no_change') for row in rows)
        canonical = json.dumps(operations, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        report = {'version': 1, 'id': folder.name, 'ok': True, 'safe_to_write': False,
                  'source_basis': 'saved_disk_snapshot_not_unsaved_editor',
                  'source_sha256': expected_source_hash, 'operations_sha256': hashlib.sha256(canonical.encode()).hexdigest(),
                  'plan_valid': valid and not second['conflicts'], 'executed_count': 0,
                  'results': rows, 'preflight_before': first['id'], 'preflight_after': second['id'],
                  'conflicts': second['conflicts'], 'blockers': second['blockers'],
                  'converter': converter_identity, 'report_path': str(folder/'report.json')}
        atomic_json(folder/'report.json', report)
        return report
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        return {'ok': False, 'safe_to_write': False, 'executed_count': 0, 'error': str(exc)}
