"""Generate a self-contained per-function particle API reference."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'mcp_server/hammer_mcp/data/particle_functions.json'
TARGET = ROOT / 'PARTICLE_API_REFERENCE.json'


def build_reference(catalog):
    classes = catalog['classes']
    names = catalog['categories']
    functions = []
    for row in catalog['functions']:
        chain, parameters = [], []
        cls = row['class_name']
        while cls:
            if cls in chain or cls not in classes:
                raise ValueError(f'invalid class chain: {row["class_name"]}, {cls}')
            chain.append(cls)
            for field in classes[cls]['fields']:
                parameters.append({
                    'name': field['name'],
                    'editor_label': field['annotations'].get('MPropertyFriendlyName', ''),
                    'type': field['type'],
                    'offset': field['offset'],
                    'declared_in': cls,
                    'editor_hidden_by_schema': 'MPropertySuppressField' in field['annotations'],
                    'annotations': field['annotations'],
                })
            cls = classes[cls]['parent']
        functions.append({
            'category': row['category'],
            'category_name': names[row['category']],
            'index': row['index'],
            'display_name': row['display_name'],
            'class_name': row['class_name'],
            'class_size': row['class_size'],
            'class_rva': row['class_rva'],
            'inheritance': chain,
            'parameter_count': len(parameters),
            'non_suppressed_parameter_count': sum(not field['editor_hidden_by_schema'] for field in parameters),
            'parameters': parameters,
        })
    if len(functions) != 376:
        raise ValueError(f'expected 376 functions, found {len(functions)}')
    return {
        'source': catalog['source'],
        'particles_dll_sha256': catalog['sha256'],
        'particles_dll_size': catalog['file_size'],
        'notes': [
            'Parameters are reflected Schema fields, including inherited fields.',
            'editor_label and annotations come from particles.dll; no inferred usage prose is added.',
            'Some fields may be hidden, conditional, or version-dependent in Particle Editor.',
            'Validate the DLL version again after a game update.',
        ],
        'categories': [{'index': i, 'name': name,
                        'function_count': sum(row['category'] == i for row in functions)}
                       for i, name in enumerate(names)],
        'function_count': len(functions),
        'functions': functions,
    }


def main():
    catalog = json.loads(SOURCE.read_text(encoding='utf-8'))
    reference = build_reference(catalog)
    TARGET.write_text(json.dumps(reference, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(f'{TARGET}: {reference["function_count"]} functions, '
          f'{sum(row["parameter_count"] for row in reference["functions"])} parameter occurrences')


if __name__ == '__main__':
    main()
