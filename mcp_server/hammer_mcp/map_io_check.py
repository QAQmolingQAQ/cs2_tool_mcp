"""Read-only saved VMAP checks against installed FGD; never save editor state."""
from __future__ import annotations
from collections import Counter
import fnmatch
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import uuid
from .build_jobs import atomic_json
from .fgd import FgdCatalog
from .project import load_project, sha256
from .source_parsing import map_entities
from .script_check import check_scripts


def parameter_error(type_name: str, value: str) -> str | None:
    if type_name in ('string', 'target_destination', 'void'):
        return None
    if not value:
        return 'event_parameter_deferred'
    if type_name in ('integer', 'int', 'boolean', 'bool'):
        if not re.fullmatch(r'[+-]?\d+', value):
            return 'expected_integer'
        if type_name in ('boolean', 'bool') and int(value) not in (0, 1):
            return 'expected_boolean_0_or_1'
        return None
    if type_name in ('float', 'vector', 'vector3', 'angle', 'color255'):
        try:
            numbers = [float(part) for part in value.split()]
        except ValueError:
            return 'expected_numeric_parameter'
        expected = 1 if type_name == 'float' else 3
        if len(numbers) != expected or not all(math.isfinite(n) for n in numbers):
            return 'invalid_numeric_shape_or_value'
        if type_name == 'color255' and any(n < 0 or n > 255 or not n.is_integer() for n in numbers):
            return 'expected_rgb_0_to_255'
        return None
    return 'unsupported_fgd_parameter_type'


def check_entities(entities: list[dict], catalog: FgdCatalog, max_issues: int = 100, script_audit: dict | None = None) -> dict:
    issues = []
    counts = Counter()
    names = {}
    schemas = {}
    script_count = 0
    def issue(code, entity, severity='error', **details):
        counts[severity] += 1
        if len(issues) < max_issues:
            issues.append({'code': code, 'severity': severity, 'entity': entity.get('id'), **details})
    for entity in entities:
        props = entity['properties']
        name = props.get('targetname', '').casefold()
        if name:
            names.setdefault(name, []).append(entity)
        schemas[entity['id']] = catalog.resolve(props.get('classname', ''))
        if props.get('cs_script') or props.get('vscripts') or props.get('classname') == 'point_script':
            script_count += 1
            if script_audit is None or props.get('classname') != 'point_script':
                issue('script_semantics_not_yet_validated', entity, 'warning')

    if script_audit is not None:
        for finding in script_audit['issues']:
            counts[finding['severity']] += 1
            if len(issues) < max_issues:
                issues.append(finding)

    def targets(name, source=None):
        if name.casefold() == '!self':
            return [source] if source else []
        if name.startswith('!'):
            return None  # Runtime event context is not a missing map entity.
        return [entity for key, values in names.items() if fnmatch.fnmatchcase(key, name.casefold()) for entity in values]

    for entity in entities:
        props = entity['properties']
        schema = schemas[entity['id']]
        if schema is None:
            issue('class_not_declared_in_fgd', entity, 'warning', classname=props.get('classname'))
        else:
            for key, kind in schema['properties'].items():
                value = props.get(key, '')
                if not value or kind not in ('filterclass', 'target_destination'):
                    continue
                matches = targets(value, entity)
                if matches == []:
                    issue('missing_filter' if kind == 'filterclass' else 'missing_property_target', entity, property=key, target=value)
                if kind == 'filterclass' and matches:
                    for target in matches:
                        if not target['properties'].get('classname', '').startswith('filter_'):
                            issue('filter_target_not_filter_class', entity, property=key, target=target['id'])
        if props.get('classname') == 'env_entity_maker':
            template_name = props.get('entitytemplate', '')
            if not template_name:
                issue('maker_template_not_configured', entity, 'warning')
            for template in (targets(template_name, entity) or []):
                if template['properties'].get('classname') != 'point_template':
                    issue('maker_template_wrong_class', entity, target=template['id'])
        for connection in entity['connections']:
            output = connection.get('outputName', '').casefold()
            name = connection.get('targetName', '')
            input_name = connection.get('inputName', '').casefold()
            value = connection.get('overrideParam', '')
            if schema and output not in schema['outputs']:
                issue('output_not_declared_in_fgd', entity, 'warning', output=output)
            try:
                delay = float(connection.get('delay', '0'))
                fires = int(connection.get('timesToFire', '-1'))
                if not math.isfinite(delay) or delay < 0 or fires < -1:
                    raise ValueError()
            except ValueError:
                issue('invalid_connection_timing', entity, output=output)
            matches = targets(name, entity)
            if matches is None:
                issue('runtime_target_deferred', entity, 'info', target=name, input=input_name)
                continue
            if not matches:
                issue('missing_io_target', entity, target=name, input=input_name)
            for target in matches:
                target_schema = schemas[target['id']]
                if target_schema is None or input_name not in target_schema['inputs']:
                    issue('input_not_declared_in_fgd', entity, 'warning', target=target['id'], input=input_name)
                    continue
                kind = target_schema['inputs'][input_name]
                error = parameter_error(kind, value)
                if error:
                    issue(error, entity, 'warning' if error in ('event_parameter_deferred', 'unsupported_fgd_parameter_type') else 'error',
                          target=target['id'], input=input_name, parameter_type=kind, value=value)
                if kind == 'target_destination' and value and targets(value, entity) == []:
                    issue('missing_input_parameter_target', entity, target=value, input=input_name)
                # Requested project policy, not an engine requirement: maker
                # spawn info_target should be represented in its point_template.
                if target['properties'].get('classname') == 'env_entity_maker' and input_name == 'forcespawnatentityorigin':
                    templates = targets(target['properties'].get('entitytemplate', ''), target) or []
                    members = set()
                    for template in templates:
                        for key, pattern in template['properties'].items():
                            if re.fullmatch(r'template\d+', key) and pattern:
                                members.update(member['id'] for member in (targets(pattern, template) or []))
                    for spawn in (targets(value, entity) or []):
                        if spawn['properties'].get('classname') == 'info_target' and spawn['id'] not in members:
                            issue('maker_spawn_target_outside_template', target, 'warning', spawn_target=spawn['id'], policy='project_template_coverage')
    return {'passed': counts['error'] == 0, 'entities': len(entities),
            'connections': sum(len(entity['connections']) for entity in entities),
            'issues': issues, 'issue_count': sum(counts.values()), 'severity_counts': dict(counts),
            'issues_truncated': sum(counts.values()) > len(issues), 'script_entities': script_count,
            'coverage_complete': False,
            'coverage': 'saved source FGD declarations and static names only; scripts, instances/prefabs, runtime targets and unsaved editor state not certified'}


def cs2_map_io_check(config: str = '', profile: str = '', max_issues: int = 100) -> dict:
    """Check a saved map copy for FGD I/O, filters, targets and template coverage."""
    try:
        if not 1 <= max_issues <= 1000:
            raise ValueError('max_issues must be between 1 and 1000')
        project = load_project(config, profile)
        source = Path(project['source'])
        source_hash = sha256(source)
        folder = Path(project['state_root']) / 'checks' / uuid.uuid4().hex
        folder.mkdir(parents=True)
        snapshot = folder / 'input.vmap'
        shutil.copyfile(source, snapshot)
        if sha256(snapshot) != source_hash or sha256(source) != source_hash:
            raise ValueError('map changed while making inspection snapshot')
        game = Path(project['game_root'])
        converter = game / 'game/bin/win64/dmxconvert.exe'
        converter_hash = sha256(converter)
        output = folder / 'map.kv2'
        command = [str(converter), '-i', str(snapshot), '-o', str(output), '-oe', 'keyvalues2']
        result = subprocess.run(command, cwd=converter.parent, capture_output=True, timeout=120,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        (folder / 'conversion.log').write_bytes(result.stdout + result.stderr)
        if result.returncode != 0 or not output.is_file():
            raise ValueError('DMX snapshot conversion failed; see ' + str(folder / 'conversion.log'))
        if output.stat().st_size > 128 * 1024 * 1024:
            raise ValueError('converted DMX exceeds parser size limit')
        entities = map_entities(output.read_text(encoding='utf-8-sig'))
        catalog = FgdCatalog(game)
        catalog.load(game / 'game/csgo/csgo.fgd')
        script_audit = check_scripts(entities, Path(project['source_root']), game)
        checked = check_entities(entities, catalog, max_issues, script_audit)
        if (sha256(source) != source_hash or sha256(converter) != converter_hash or
                any(sha256(Path(path)) != digest for path, digest in catalog.files.items()) or
                any(sha256(Path(path)) != digest for path, digest in script_audit['source_files'].items())):
            raise ValueError('map, converter, FGD or script changed during inspection')
        response = {'ok': True, **checked, 'source_basis': 'saved_disk_snapshot',
                    'source_sha256': source_hash, 'source': str(source),
                    'fgd_files': catalog.files, 'fgd_classes': len(catalog.classes), 'script_audit': script_audit,
                    'converter_sha256': converter_hash, 'report_path': str(folder / 'report.json'), 'release_ready': False}
        atomic_json(folder / 'report.json', response)
        return response
    except (OSError, ValueError, KeyError, IndexError, TypeError, subprocess.SubprocessError) as exc:
        return {'ok': False, 'passed': False, 'coverage_complete': False, 'error': str(exc)}
