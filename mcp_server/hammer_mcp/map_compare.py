"""Exact typed DMX node-content comparison across regenerated storage GUIDs.

Child order, transforms, mesh streams and scalar values are retained. This is
not proof of full-map equivalence: editor/root metadata is reported separately.
"""
import hashlib
import json
from pathlib import Path
from .edit_preflight import file_evidence
from .project import load_project, within
from .source_parsing import DmxText, DmxElement


def node_snapshot(text: str) -> dict:
    elements = DmxText(text).parse()
    by_id, nodes = {}, {}
    for element in elements:
        identifier = element.attrs.get('id')
        if identifier:
            if identifier in by_id:
                raise ValueError('duplicate DMX element identity')
            by_id[identifier] = element
        node_id = element.attrs.get('nodeID')
        if node_id is not None:
            if node_id in nodes:
                raise ValueError('duplicate nodeID; cannot match nodes')
            nodes[node_id] = element

    def canonical(value, root=None, active=frozenset(), depth=0):
        if depth > 128:
            raise ValueError('canonical graph depth exceeds bound')
        if isinstance(value, dict) and set(value) == {'ref'}:
            identifier = value['ref']
            if not identifier:
                return None
            if identifier not in by_id:
                raise ValueError('unresolved element reference')
            value = by_id[identifier]
        if isinstance(value, DmxElement):
            if value is not root and 'nodeID' in value.attrs:
                return {'node_ref': value.attrs['nodeID'], 'kind': value.kind}
            if id(value) in active:
                raise ValueError('cyclic non-node element graph is unsupported')
            branch = active | {id(value)}
            # Only storage identity is omitted. User/game properties named id
            # remain when their DMX type is not elementid.
            keys = [key for key in value.attrs
                    if not (key == 'id' and value.types.get(key) == 'elementid')]
            return {'kind': value.kind, 'attributes': {
                key: {'type': value.types[key], 'value': canonical(value.attrs[key], active=branch, depth=depth+1)}
                for key in keys}}
        if isinstance(value, list):
            return [canonical(item, active=active, depth=depth+1) for item in value]
        if isinstance(value, dict):
            raise ValueError('unsupported reference object')
        return value

    return {'nodes': {key: canonical(node, root=node) for key, node in nodes.items()},
            'metadata': [canonical(e) for e in elements
                         if e.kind in ('$prefix_element$', 'CMapRootElement')]}


def compare_map_text(before: str, after: str) -> dict:
    old, new = node_snapshot(before), node_snapshot(after)
    missing = sorted(old['nodes'].keys() - new['nodes'].keys())
    added = sorted(new['nodes'].keys() - old['nodes'].keys())
    changed = []
    for key in sorted(old['nodes'].keys() & new['nodes'].keys()):
        a, b = old['nodes'][key], new['nodes'][key]
        if a != b:
            aa, bb = a['attributes'], b['attributes']
            changed.append({'node_id': key, 'kind_before': a['kind'], 'kind_after': b['kind'],
                            'attributes': sorted(k for k in aa.keys() | bb.keys() if aa.get(k) != bb.get(k))})
    def digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                         separators=(',', ':')).encode()).hexdigest()
    return {'missing_nodes': missing, 'added_nodes': added, 'changed_nodes': changed,
            'before_node_count': len(old['nodes']), 'after_node_count': len(new['nodes']),
            'node_content_equal': not missing and not added and not changed,
            'metadata_equal': old['metadata'] == new['metadata'],
            'before_node_sha256': digest(old['nodes']), 'after_node_sha256': digest(new['nodes']),
            'storage_guid_policy': 'omit only id attributes typed elementid; retain types, order and scalar values',
            'full_rollback_verified': False}


def cs2_map_snapshot_compare(before_kv2: str, after_kv2: str,
                             config: str = '', profile: str = '') -> dict:
    """Compare cached saved DMX snapshots within the configured state directory.

    Retains child order, types, transforms and mesh data; omits storage GUIDs.
    Does not certify complete rollback, aliases, live state or game behavior.
    """
    try:
        project = load_project(config, profile)
        paths = [within(Path(name), Path(project['state_root'])) for name in (before_kv2, after_kv2)]
        for path in paths:
            if path.suffix.casefold() != '.kv2' or path.stat().st_size > 128*1024*1024:
                raise ValueError('expected bounded cached .kv2 snapshot')
        evidence = [file_evidence(path) for path in paths]
        texts = [path.read_text(encoding='utf-8-sig') for path in paths]
        report = compare_map_text(*texts)
        if [file_evidence(path) for path in paths] != evidence:
            raise ValueError('snapshot changed during comparison')
        return {'ok': True, **report, 'inputs': evidence,
                'source_basis': 'cached_saved_snapshots_not_live_editor', 'safe_to_write': False}
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
        return {'ok': False, 'full_rollback_verified': False, 'safe_to_write': False, 'error': str(exc)}
