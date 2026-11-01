"""Fast syntax gates for files touched by an edit plan."""
from __future__ import annotations

import ast
import json
from pathlib import Path


def _first_error_line(root) -> int:
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == "ERROR" or node.is_missing:
            return node.start_point[0] + 1
        stack.extend(reversed(node.children))
    return 1


def check_syntax(path: str | Path, text: str) -> str | None:
    suffix = Path(path).suffix.lower()
    if suffix in (".py", ".pyi"):
        try:
            ast.parse(text, filename=str(path))
        except SyntaxError as exc:
            return f"{path}:{exc.lineno}: {exc.msg}"
        return None

    if suffix in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"):
        try:
            from quetz.infrastructure.index.typescript_outline import _parser_for

            parser = _parser_for(str(path))
            tree = parser.parse(text.encode("utf-8"))
            if tree.root_node.has_error:
                line = _first_error_line(tree.root_node)
                return f"{path}:{line}: parser reported a syntax error"
        except Exception:
            # If the native parser is unavailable, skip the optional gate.
            return None
        return None

    if suffix == ".json":
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            return f"{path}:{exc.lineno}: {exc.msg}"
    return None
