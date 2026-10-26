"""Bounded lexical parsing shared by disk DMX snapshots and installed FGD."""
from __future__ import annotations
from dataclasses import dataclass, field
import re

TOKEN = re.compile(r'\s+|//[^\n]*|/\*[\s\S]*?\*/|<!--[^>]*-->|"(?:\\.|[^"\\])*"|[{}\[\](),:=+]|[^\s{}\[\](),:=+"/]+|/(?![/*])', re.S)


def lex(source: str) -> list[str]:
    tokens = []
    position = 0
    for match in TOKEN.finditer(source):
        if match.start() != position:
            raise ValueError(f'unsupported source syntax at character {position}')
        position = match.end()
        value = match.group()
        if value.isspace() or value.startswith(('//', '/*', '<!--')):
            continue
        tokens.append(value)
        if len(tokens) > 4_000_000:
            raise ValueError('source token limit exceeded')
    if position != len(source):
        raise ValueError('unterminated source token')
    return tokens


def unquote(value: str) -> str:
    if not value.startswith('"'):
        return value
    return re.sub(r'\\(["\\nrt])', lambda m: {'n': '\n', 'r': '\r', 't': '\t'}.get(m[1], m[1]), value[1:-1])


@dataclass
class DmxElement:
    kind: str
    attrs: dict = field(default_factory=dict)
    types: dict = field(default_factory=dict)


class DmxText:
    def __init__(self, source: str):
        if not re.match(r'^<!--\s*dmx encoding keyvalues2(?:_flat)? 4 format vmap \d+\s*-->', source):
            raise ValueError('expected converted keyvalues2 vmap')
        self.tokens = lex(source)
        self.position = 0
        self.elements = []

    def take(self):
        if self.position >= len(self.tokens):
            raise ValueError('truncated DMX text')
        value = self.tokens[self.position]
        self.position += 1
        return value

    def peek(self):
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def element(self, kind: str, depth: int = 0) -> DmxElement:
        if depth > 128:
            raise ValueError('DMX nesting limit exceeded')
        if self.take() != '{':
            raise ValueError('expected DMX element body')
        node = DmxElement(kind)
        self.elements.append(node)
        while self.peek() != '}':
            name, type_name = unquote(self.take()), unquote(self.take())
            if name in node.attrs:
                raise ValueError(f'duplicate DMX attribute: {name}')
            node.types[name] = type_name
            if self.peek() == '{':
                node.attrs[name] = self.element(type_name, depth + 1)
            elif self.peek() == '[':
                self.take()
                values = []
                while self.peek() != ']':
                    first = self.take()
                    if first == ',':
                        continue
                    if self.peek() == '{':
                        values.append(self.element(unquote(first), depth + 1))
                    elif unquote(first) == 'element' and type_name == 'element_array':
                        values.append({'ref': unquote(self.take())})
                    else:
                        values.append(unquote(first))
                self.take()
                node.attrs[name] = values
            else:
                value = unquote(self.take())
                node.attrs[name] = {'ref': value} if type_name == 'element' else value
        self.take()
        return node

    def parse(self) -> list[DmxElement]:
        while self.peek() is not None:
            self.element(unquote(self.take()))
        return self.elements


def map_entities(source: str) -> list[dict]:
    elements = DmxText(source).parse()
    by_id = {}
    for element in elements:
        identifier = element.attrs.get('id')
        if identifier:
            if identifier in by_id:
                raise ValueError('duplicate DMX element id')
            by_id[identifier] = element

    def resolve(value):
        if isinstance(value, dict) and 'ref' in value:
            if value['ref'] and value['ref'] not in by_id:
                raise ValueError('unresolved DMX element reference')
            return by_id.get(value['ref'])
        return value

    result = []
    for element in elements:
        if element.kind != 'CMapEntity':
            continue
        if not isinstance(element.attrs.get('id'), str) or not element.attrs['id']:
            raise ValueError('CMapEntity lacks stable element id')
        props = resolve(element.attrs.get('entity_properties'))
        if not isinstance(props, DmxElement):
            raise ValueError('CMapEntity lacks entity_properties')
        properties = {}
        for key, value in props.attrs.items():
            if key == 'id':
                continue
            if not isinstance(value, str) or key.casefold() in properties:
                raise ValueError('unsupported or duplicate entity property')
            properties[key.casefold()] = value
        connections = []
        for value in element.attrs.get('connectionsData', []):
            connection = resolve(value)
            if not isinstance(connection, DmxElement) or connection.kind != 'DmeConnectionData':
                raise ValueError('unsupported map connection encoding')
            connections.append(dict(connection.attrs))
        result.append({'id': element.attrs.get('id'), 'node_id': element.attrs.get('nodeID'),
                       'properties': properties,
                       'connections': connections, 'editor_only': element.attrs.get('editorOnly') in ('1', 'true')})
    return result
