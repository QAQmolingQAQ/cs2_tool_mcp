"""Installed FGD class schemas with includes, inheritance and I/O signatures."""
from __future__ import annotations
from pathlib import Path
from .project import sha256, within
from .source_parsing import lex, unquote


class FgdCatalog:
    def __init__(self, game: Path):
        self.root = (game / 'game').resolve()
        self.search = [self.root / 'csgo', self.root / 'core']
        self.classes = {}
        self.files = {}
        self._stack = set()
        self._resolved = {}

    def load(self, path: Path):
        path = within(path, self.root)
        if path in self._stack:
            raise ValueError('FGD include cycle')
        if str(path) in self.files:
            return
        if path.stat().st_size > 16 * 1024 * 1024 or len(self.files) > 256:
            raise ValueError('FGD source limits exceeded')
        self._stack.add(path)
        before = sha256(path)
        tokens = lex(path.read_text(encoding='utf-8-sig'))
        self.files[str(path)] = before
        if sha256(path) != before:
            raise ValueError('FGD changed during read')
        position = 0
        while position < len(tokens):
            token = tokens[position]
            position += 1
            if token.casefold() == '@include':
                name = unquote(tokens[position]); position += 1
                candidates = [path.parent / name, *(root / name for root in self.search)]
                target = next((candidate for candidate in candidates if candidate.is_file()), None)
                if target is None:
                    raise ValueError(f'missing FGD include: {name}')
                self.load(target)
                continue
            if not (token.startswith('@') and token.casefold().endswith('class')):
                continue
            header = []
            nesting = 0
            while position < len(tokens):
                value = tokens[position]; position += 1
                if value == '=' and nesting == 0:
                    break
                header.append(value)
                if value in ('(', '{'): nesting += 1
                if value in (')', '}'): nesting -= 1
            else:
                raise ValueError('unterminated FGD class header')
            name = unquote(tokens[position]).casefold(); position += 1
            while position < len(tokens) and tokens[position] != '[':
                position += 1
            if position >= len(tokens):
                raise ValueError('FGD class has no body')
            position += 1
            body = []
            depth = 1
            while position < len(tokens) and depth:
                value = tokens[position]; position += 1
                if value == '[': depth += 1
                if value == ']': depth -= 1
                if depth: body.append(value)
            if depth:
                raise ValueError('unterminated FGD class body')
            bases = []
            for index, value in enumerate(header[:-1]):
                if value.casefold() == 'base' and header[index + 1] == '(':
                    end = header.index(')', index + 2)
                    bases.extend(unquote(value).casefold() for value in header[index + 2:end] if value != ',')
            schema = {'name': name, 'bases': bases, 'inputs': {}, 'outputs': {}, 'properties': {}, 'source': str(path)}
            depth = 0
            for index, value in enumerate(body):
                if value == '[': depth += 1
                elif value == ']': depth -= 1
                elif depth == 0:
                    section = {'input': 'inputs', 'output': 'outputs'}.get(value.casefold())
                    if not section and index and body[index - 1].casefold() in ('input', 'output'):
                        continue
                    start = index + 1 if section else index
                    if start + 3 < len(body) and body[start + 1] == '(':
                        end = body.index(')', start + 2)
                        schema[section or 'properties'][unquote(body[start]).casefold()] = ''.join(body[start + 2:end]).casefold()
            self.classes[name] = schema
        self._stack.remove(path)
        self._resolved.clear()

    def resolve(self, name: str, stack: tuple = ()) -> dict | None:
        name = name.casefold()
        if name in self._resolved:
            return self._resolved[name]
        if name not in self.classes:
            return None
        if name in stack:
            raise ValueError('FGD inheritance cycle')
        own = self.classes[name]
        result = {'name': name, 'ancestors': [], 'inputs': {}, 'outputs': {}, 'properties': {}}
        for base in own['bases']:
            inherited = self.resolve(base, (*stack, name))
            if inherited is None:
                raise ValueError(f'missing FGD base class: {base}')
            result['ancestors'].extend([base, *inherited['ancestors']])
            for section in ('inputs', 'outputs', 'properties'):
                result[section].update(inherited[section])
        for section in ('inputs', 'outputs', 'properties'):
            result[section].update(own[section])
        self._resolved[name] = result
        return result
