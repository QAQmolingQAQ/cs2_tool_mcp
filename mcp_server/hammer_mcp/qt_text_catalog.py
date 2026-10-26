"""Read external translation tables as reference data, never as UI identity."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

SCOPES = frozenset(('common','hammer','pet','particles','met','modeldoc_editor','sfm',
    'postprocessingeditor','cs2_item_editor','cs2_workshop_manager','subrecteditor'))


def load_catalog(root: str | Path, scope: str) -> dict:
    if scope not in SCOPES:
        raise ValueError('unsupported text catalog scope')
    root = Path(root).resolve(strict=True)
    entries: dict[str, list[dict]] = {}
    files = []
    for stem in dict.fromkeys((scope, 'common')):
        path = root / (stem + '.json')
        if not path.exists():
            if stem == scope: raise FileNotFoundError(path)
            continue
        if not path.resolve().is_relative_to(root):
            raise ValueError('catalog file escapes root')
        if path.stat().st_size > 32 * 1024 * 1024:
            raise ValueError('text catalog file exceeds 32 MiB')
        raw = path.read_bytes()
        if len(raw) > 32 * 1024 * 1024: raise ValueError('text catalog file exceeds 32 MiB')
        data = json.loads(raw.decode('utf-8-sig'))
        if not isinstance(data, dict): raise ValueError('catalog must be an object')
        digest = hashlib.sha256(raw).hexdigest()
        translated = 0
        for source, value in data.items():
            if source == '_meta': continue
            if not isinstance(source, str) or not source: continue
            if isinstance(value, dict):
                if value.get('en', source) != source:
                    raise ValueError('rich catalog source disagrees with key')
                value = value.get('zh', '')
            if value is None or value == '': continue
            if not isinstance(value, str): raise ValueError('translation must be a string')
            if not value.strip(): continue
            entries.setdefault(source, []).append({'source':source,'translation':value,
                'catalog':stem + '.json','sha256':digest})
            translated += 1
        files.append({'file':stem+'.json','sha256':digest,'translated_entries':translated})
    return {'entries':entries,'files':files,'scope':scope}


def lookup(catalog: dict, text: str) -> list[dict]:
    """Preserve ambiguous reverse matches; do not pick a translated locator."""
    found = []
    for source, variants in catalog['entries'].items():
        for item in variants:
            if source == text or item['translation'] == text:
                found.append(dict(item))
    return found


def annotate_snapshot(snapshot: dict, catalog: dict) -> dict:
    result = dict(snapshot)
    result['text_reference'] = {'scope':catalog['scope'],'files':catalog['files'],
        'role':'external_translation_reference_not_observed_ui','locator_text_unchanged':True}
    if 'widgets' in snapshot:
        result['widgets'] = [dict(row, text_reference=lookup(catalog, row.get('button_text','')))
                             for row in snapshot['widgets']]
    return result
