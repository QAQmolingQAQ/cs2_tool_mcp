"""Read-only inspection of text KV3 ModelDoc and Particle Editor source assets."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any


_HEADER = re.compile(r"^<!--\s*kv3\s+.*?format:(modeldoc|vpcf)\d+:version\{", re.I | re.S)
_TOKEN = re.compile(
    r"\s+|//[^\n]*|/\*[\s\S]*?\*/|<!--[^>]*-->|"
    r'"(?:\\.|[^"\\])*"|[{}\[\]=,]|[^\s{}\[\]=,"]+',
    re.S,
)
_MAX_BYTES = 8 * 1024 * 1024
_MAX_TOKENS = 1_000_000


def _tokens(source: str) -> list[str]:
    out: list[str] = []
    pos = 0
    for match in _TOKEN.finditer(source):
        if match.start() != pos:
            raise ValueError(f"unsupported KV3 syntax at byte {pos}")
        pos = match.end()
        value = match.group()
        if value.isspace() or value.startswith(("//", "/*", "<!--")):
            continue
        out.append(value)
        if len(out) > _MAX_TOKENS:
            raise ValueError("KV3 token limit exceeded")
    if pos != len(source):
        raise ValueError(f"unsupported KV3 syntax at byte {pos}")
    return out


class _Parser:
    def __init__(self, tokens: list[str]):
        self.tokens, self.pos = tokens, 0

    def _take(self) -> str:
        if self.pos >= len(self.tokens):
            raise ValueError("unexpected end of KV3")
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def _value(self, depth: int = 0) -> Any:
        if depth > 128:
            raise ValueError("KV3 nesting limit exceeded")
        token = self._take()
        if token == "{":
            result: dict[str, Any] = {}
            while self.pos < len(self.tokens) and self.tokens[self.pos] != "}":
                key = self._take()
                if key == ",":
                    continue
                if self._take() != "=":
                    raise ValueError(f"expected '=' after {key!r}")
                if key.startswith('"'):
                    key = _unquote(key)
                result[key] = self._value(depth + 1)
                if self.pos < len(self.tokens) and self.tokens[self.pos] == ",":
                    self.pos += 1
            if self._take() != "}":
                raise ValueError("unterminated KV3 object")
            return result
        if token == "[":
            result = []
            while self.pos < len(self.tokens) and self.tokens[self.pos] != "]":
                if self.tokens[self.pos] == ",":
                    self.pos += 1
                    continue
                result.append(self._value(depth + 1))
            if self._take() != "]":
                raise ValueError("unterminated KV3 array")
            return result
        if token.startswith('"'):
            return _unquote(token)
        if token.endswith(":"):
            return {"type": token[:-1], "value": self._value(depth + 1)}
        if token in ("true", "false"):
            return token == "true"
        if token == "null":
            return None
        try:
            return float(token) if any(c in token for c in ".eE") else int(token, 0)
        except ValueError:
            return token

    def parse(self) -> Any:
        result = self._value()
        if self.pos != len(self.tokens):
            raise ValueError(f"trailing KV3 tokens at index {self.pos}")
        return result


def _unquote(token: str) -> str:
    # KV3 uses JSON-like string escapes; preserve unknown escapes rather than
    # silently deleting them.
    import json
    try:
        return json.loads(token)
    except ValueError:
        return token[1:-1]


def _select(root: Any, path: str) -> Any:
    node = root
    if not path:
        return node
    for part in re.findall(r"[^.\[\]]+|\[\d+\]", path):
        if part.startswith("["):
            if not isinstance(node, list):
                raise KeyError(f"{part} requires an array")
            node = node[int(part[1:-1])]
        else:
            if not isinstance(node, dict):
                raise KeyError(f"{part} requires an object")
            node = node[part]
    return node


def _summary(node: Any, path: str, depth: int, limit: int, out: list[dict]) -> None:
    if len(out) >= limit:
        return
    if isinstance(node, dict):
        def simple(value: Any) -> bool:
            return (not isinstance(value, (dict, list)) or
                    isinstance(value, dict) and set(value) == {"type", "value"} or
                    isinstance(value, list) and len(value) <= 16 and
                    all(not isinstance(item, (dict, list)) for item in value))

        scalars = {k: v for k, v in node.items() if simple(v)}
        out.append({"path": path or "$", "class": node.get("_class"),
                    "fields": scalars, "children": {
                        k: len(v) if isinstance(v, list) else 1
                        for k, v in node.items() if not simple(v)}})
        if depth <= 0:
            return
        for key, child in node.items():
            if not simple(child):
                _summary(child, f"{path}.{key}" if path else key, depth - 1, limit, out)
    elif isinstance(node, list):
        for index, child in enumerate(node):
            if len(out) >= limit:
                break
            if isinstance(child, (dict, list)):
                _summary(child, f"{path}[{index}]", depth, limit, out)


def cs2_asset_tree(path: str, node_path: str = "", depth: int = 2,
                   limit: int = 100) -> dict:
    """Inspect nodes and attributes in a saved text-KV3 .vmdl or .vpcf.

    Args:
        path: Absolute source-file path. Binary compiled assets are unsupported.
        node_path: Optional field/index path such as rootNode.children[0] or m_Children[0].
        depth: Number of object levels to expand, 0-8.
        limit: Maximum returned nodes, 1-500.
    """
    try:
        file = Path(path).resolve(strict=True)
        if not file.is_file() or file.suffix.lower() not in (".vmdl", ".vpcf"):
            raise ValueError("expected a source .vmdl or .vpcf file")
        if file.stat().st_size > _MAX_BYTES:
            raise ValueError("asset exceeds 8 MiB inspection limit")
        source = file.read_text(encoding="utf-8-sig")
        header = _HEADER.match(source)
        if not header:
            raise ValueError("expected text KV3 modeldoc/vpcf header")
        kind = header.group(1).lower()
        if (kind, file.suffix.lower()) not in (("modeldoc", ".vmdl"), ("vpcf", ".vpcf")):
            raise ValueError("KV3 format does not match file extension")
        tree = _Parser(_tokens(source)).parse()
        selected = _select(tree, node_path)
        rows: list[dict] = []
        cap = max(1, min(int(limit), 500))
        _summary(selected, node_path, max(0, min(int(depth), 8)), cap + 1, rows)
        return {"ok": True, "path": str(file), "format": kind,
                "node_path": node_path or "$", "nodes": rows[:cap],
                "value": selected if not isinstance(selected, dict) and
                         (not isinstance(selected, list) or len(selected) <= 16) else None,
                "truncated": len(rows) > cap,
                "scope": "saved source asset; unsaved editor changes are not included"}
    except (OSError, UnicodeError, ValueError, KeyError, IndexError) as exc:
        return {"ok": False, "path": path, "error": f"{type(exc).__name__}: {exc}"}
