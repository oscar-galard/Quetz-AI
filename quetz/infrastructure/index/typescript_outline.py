"""TypeScript/TSX/JavaScript outline extraction via tree-sitter.

Produces imports and top-level symbols (components, hooks, classes, interfaces,
types, enums) plus class methods. A regex fallback keeps indexing usable if the
native parser is unavailable.
"""
from __future__ import annotations

import re
from pathlib import Path

from quetz.application.ports.index import ImportRef, IndexedSymbol
from quetz.infrastructure.index.base import SourceOutline

_DECLARATION_TYPES = {
    "function_declaration",
    "generator_function_declaration",
    "class_declaration",
    "abstract_class_declaration",
    "interface_declaration",
    "type_alias_declaration",
    "enum_declaration",
    "lexical_declaration",
    "variable_declaration",
}

_IMPORT_PATTERNS = (
    re.compile(r"""(?:import|export)\s+(?:[^'"]*?\s+from\s+)?['"]([^'"]+)['"]"""),
    re.compile(r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)"""),
    re.compile(r"""import\s*\(\s*['"]([^'"]+)['"]\s*\)"""),
)

_FALLBACK_SYMBOL_PATTERNS = (
    (re.compile(r"(?:export\s+)?(?:async\s+)?function\s+(\w+)"), "function"),
    (re.compile(r"(?:export\s+)?(?:abstract\s+)?class\s+(\w+)"), "class"),
    (re.compile(r"(?:export\s+)?interface\s+(\w+)"), "interface"),
    (re.compile(r"(?:export\s+)?type\s+(\w+)\s*="), "type"),
    (re.compile(r"(?:export\s+)?enum\s+(\w+)"), "enum"),
    (re.compile(r"(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\("), "function"),
)


def _parser_for(path: str):
    from tree_sitter import Language, Parser

    import tree_sitter_javascript as tsj
    import tree_sitter_typescript as tst

    suffix = Path(path).suffix.lower()
    if suffix == ".ts":
        language = Language(tst.language_typescript())
    elif suffix == ".tsx":
        language = Language(tst.language_tsx())
    else:
        language = Language(tsj.language())
    try:
        return Parser(language)
    except TypeError:
        parser = Parser()
        parser.language = language
        return parser


def _text(node, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _signature(node, source: bytes) -> str:
    body = node.child_by_field_name("body")
    if body is None:
        for child in node.named_children:
            if child.type in ("arrow_function", "function_expression"):
                body = child.child_by_field_name("body") or child
                break
            if child.type == "statement_block":
                body = child
                break
    end = body.start_byte if body is not None else node.end_byte
    raw = source[node.start_byte : end].decode("utf-8", errors="replace")
    raw = " ".join(raw.split())
    return raw[:240]


def _names(node) -> str:
    name = node.child_by_field_name("name")
    if name is None:
        for child in node.named_children:
            if child.type in ("identifier", "type_identifier", "property_identifier"):
                name = child
                break
    return _text(name, b"") if name is None else name.text.decode("utf-8", errors="replace")


def _imports(text: str) -> tuple[ImportRef, ...]:
    modules: list[str] = []
    for pattern in _IMPORT_PATTERNS:
        for match in pattern.finditer(text):
            module = match.group(1).strip()
            if module and module not in modules:
                modules.append(module)
    return tuple(ImportRef(module=module) for module in modules)


def _tags(
    *,
    path: str,
    name: str,
    kind: str,
    text: str,
    imports: set[str],
) -> tuple[str, ...]:
    tags: set[str] = set()
    suffix = Path(path).suffix.lower()
    is_component_file = suffix in (".tsx", ".jsx")
    if "react" in imports:
        tags.add("react")
    if is_component_file and name[:1].isupper():
        tags.add("react.component")
    if re.match(r"^use[A-Z]", name):
        tags.add("react.hook")
    if kind in ("interface", "type") and name.endswith("Props"):
        tags.add("react.props")
    if "className=" in text:
        tags.add("tailwind")
    if "components/ui/" in path or "@/components/ui" in text:
        tags.add("shadcn.ui")
    if any(module in imports for module in ("@tanstack/react-query", "swr")):
        tags.add("data.fetch")
    if any(module in imports for module in ("axios",)) or "fetch(" in text:
        tags.add("api.client")
    if any(module in imports for module in ("vite",)) or Path(path).name.startswith("vite.config"):
        tags.add("vite")
    if any(module in imports for module in ("react-router", "react-router-dom", "@tanstack/react-router")):
        tags.add("route")
    if "websocket" in text.lower() or "new WebSocket" in text:
        tags.add("websocket")
    return tuple(sorted(tags))


def _symbol(
    node,
    *,
    path: str,
    source: bytes,
    imports: set[str],
    text: str,
    qualname: str | None = None,
    kind: str | None = None,
) -> IndexedSymbol:
    name = _names(node)
    if not name and node.type in ("lexical_declaration", "variable_declaration"):
        for child in node.named_children:
            if child.type == "variable_declarator":
                name = _names(child)
                break
    symbol_kind = kind or node.type
    if symbol_kind in ("function_declaration", "generator_function_declaration"):
        symbol_kind = "function"
    elif symbol_kind in ("class_declaration", "abstract_class_declaration"):
        symbol_kind = "class"
    elif symbol_kind == "interface_declaration":
        symbol_kind = "interface"
    elif symbol_kind == "type_alias_declaration":
        symbol_kind = "type"
    elif symbol_kind == "enum_declaration":
        symbol_kind = "enum"
    elif symbol_kind in ("lexical_declaration", "variable_declaration"):
        symbol_kind = "variable"

    if Path(path).suffix.lower() in (".tsx", ".jsx") and name[:1].isupper():
        symbol_kind = "component"
    elif re.match(r"^use[A-Z]", name):
        symbol_kind = "hook"

    decorators = tuple(
        _text(child, source) for child in node.children if child.type == "decorator"
    )
    bases: tuple[str, ...] = ()
    for child in node.children:
        if child.type in ("class_heritage", "extends_clause", "implements_clause"):
            bases = (*bases, " ".join(_text(child, source).split()))

    return IndexedSymbol(
        path=path,
        name=name,
        qualname=qualname or name,
        kind=symbol_kind,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        signature=_signature(node, source),
        docstring="",
        decorators=decorators,
        bases=bases,
        tags=_tags(path=path, name=name, kind=symbol_kind, text=text, imports=imports),
    )


def _unwrap_export(node):
    if node.type != "export_statement":
        return node
    declaration = node.child_by_field_name("declaration")
    if declaration is not None:
        return declaration
    for child in node.named_children:
        if child.type in _DECLARATION_TYPES:
            return child
    return None


def _outline_with_parser(path: str, text: str) -> SourceOutline:
    source = text.encode("utf-8")
    parser = _parser_for(path)
    tree = parser.parse(source)
    imports = _imports(text)
    import_set = {ref.module for ref in imports}
    symbols: list[IndexedSymbol] = []

    for raw_child in tree.root_node.named_children:
        child = _unwrap_export(raw_child)
        if child is None or child.type not in _DECLARATION_TYPES:
            continue
        if child.type in ("lexical_declaration", "variable_declaration"):
            for declarator in child.named_children:
                if declarator.type != "variable_declarator":
                    continue
                value = declarator.child_by_field_name("value")
                if value is None or value.type not in ("arrow_function", "function_expression"):
                    continue
                symbols.append(
                    _symbol(
                        declarator,
                        path=path,
                        source=source,
                        imports=import_set,
                        text=text,
                        kind="function",
                    )
                )
            continue

        symbols.append(
            _symbol(
                child,
                path=path,
                source=source,
                imports=import_set,
                text=text,
            )
        )

        if child.type in ("class_declaration", "abstract_class_declaration"):
            class_name = _names(child)
            class_body = child.child_by_field_name("body")
            members = class_body.named_children if class_body is not None else ()
            for member in members:
                if member.type in ("method_definition", "public_field_definition"):
                    value = member.child_by_field_name("value")
                    if member.type == "public_field_definition" and (
                        value is None or value.type != "arrow_function"
                    ):
                        continue
                    symbols.append(
                        _symbol(
                            member,
                            path=path,
                            source=source,
                            imports=import_set,
                            text=text,
                            qualname=f"{class_name}.{_names(member)}",
                            kind="method" if member.type == "method_definition" else "function",
                        )
                    )

    return SourceOutline(
        language="typescript" if Path(path).suffix.lower() in (".ts", ".tsx") else "javascript",
        docstring="",
        imports=imports,
        symbols=tuple(symbols),
    )


def _fallback_outline(path: str, text: str) -> SourceOutline:
    imports = _imports(text)
    import_set = {ref.module for ref in imports}
    symbols: list[IndexedSymbol] = []
    for pattern, kind in _FALLBACK_SYMBOL_PATTERNS:
        for match in pattern.finditer(text):
            name = match.group(1)
            line = text.count("\n", 0, match.start()) + 1
            symbols.append(
                IndexedSymbol(
                    path=path,
                    name=name,
                    qualname=name,
                    kind=kind,
                    start_line=line,
                    end_line=line,
                    signature=" ".join(match.group(0).split())[:240],
                    tags=_tags(path=path, name=name, kind=kind, text=text, imports=import_set),
                )
            )
    return SourceOutline(
        language="typescript" if Path(path).suffix.lower() in (".ts", ".tsx") else "javascript",
        docstring="",
        imports=imports,
        symbols=tuple(symbols),
    )


def outline_typescript(path: str, text: str) -> SourceOutline:
    try:
        return _outline_with_parser(path, text)
    except Exception:
        return _fallback_outline(path, text)
