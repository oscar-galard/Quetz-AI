"""Python symbol/import extractor built on the standard-library ``ast`` module."""
from __future__ import annotations

import ast

from quetz.application.ports.index import ImportRef, IndexedSymbol
from quetz.infrastructure.index.base import SourceOutline

_STACK_TAGS = {
    "fastapi": "fastapi",
    "pydantic": "pydantic",
    "sqlalchemy": "sqlalchemy",
    "celery": "celery",
    "langgraph": "langgraph",
    "langchain": "langchain",
}


def _decorator_text(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def _base_text(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def _short_name(text: str) -> str:
    return text.rsplit(".", 1)[-1].strip()


def _tags_for(
    *,
    name: str,
    decorators: tuple[str, ...],
    bases: tuple[str, ...],
    import_modules: set[str],
) -> tuple[str, ...]:
    tags: set[str] = set()
    base_names = {_short_name(b) for b in bases}
    decorator_text = " ".join(decorators).lower()
    modules = " ".join(sorted(import_modules)).lower()
    name_lower = name.lower()

    if any(d.startswith("@router.") or d.startswith("@app.") for d in decorators):
        tags.add("fastapi.route")
    if "route" in decorator_text or "get(" in decorator_text or "post(" in decorator_text:
        if "fastapi" in modules:
            tags.add("fastapi.route")
    if "basemodel" in base_names:
        tags.add("pydantic.model")
    if base_names & {"base", "declarativebase"}:
        tags.add("sqlalchemy.model")
    if "typeddict" in base_names:
        tags.add("typeddict")
        if name.endswith("State"):
            tags.add("langgraph.state")
    if "shared_task" in decorator_text or "celery" in decorator_text and "task" in decorator_text:
        tags.add("celery.task")
    if "node" in name_lower and "langgraph" in modules:
        tags.add("langgraph.node")
    for module, tag in _STACK_TAGS.items():
        if module in modules:
            tags.add(tag)
    return tuple(sorted(tags))


def _function_symbol(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    path: str,
    qualname: str,
    import_modules: set[str],
    kind: str | None = None,
) -> IndexedSymbol:
    decorators = tuple(_decorator_text(d) for d in node.decorator_list)
    args = ""
    try:
        args = ast.unparse(node.args)
    except Exception:
        pass
    returns = ""
    if node.returns is not None:
        try:
            returns = f" -> {ast.unparse(node.returns)}"
        except Exception:
            pass
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    signature = f"{prefix} {node.name}({args}){returns}"
    bases: tuple[str, ...] = ()
    return IndexedSymbol(
        path=path,
        name=node.name,
        qualname=qualname,
        kind=kind or ("async_function" if isinstance(node, ast.AsyncFunctionDef) else "function"),
        start_line=node.lineno,
        end_line=getattr(node, "end_lineno", node.lineno),
        signature=signature,
        docstring=ast.get_docstring(node) or "",
        decorators=decorators,
        bases=bases,
        tags=_tags_for(
            name=node.name,
            decorators=decorators,
            bases=bases,
            import_modules=import_modules,
        ),
    )


def _class_symbol(
    node: ast.ClassDef,
    *,
    path: str,
    import_modules: set[str],
) -> IndexedSymbol:
    decorators = tuple(_decorator_text(d) for d in node.decorator_list)
    bases = tuple(_base_text(b) for b in node.bases)
    base_text = f"({', '.join(bases)})" if bases else ""
    return IndexedSymbol(
        path=path,
        name=node.name,
        qualname=node.name,
        kind="class",
        start_line=node.lineno,
        end_line=getattr(node, "end_lineno", node.lineno),
        signature=f"class {node.name}{base_text}",
        docstring=ast.get_docstring(node) or "",
        decorators=decorators,
        bases=bases,
        tags=_tags_for(
            name=node.name,
            decorators=decorators,
            bases=bases,
            import_modules=import_modules,
        ),
    )


def _collect_imports(tree: ast.AST) -> tuple[ImportRef, ...]:
    refs: list[ImportRef] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                refs.append(ImportRef(module=alias.name, alias=alias.asname or ""))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                refs.append(
                    ImportRef(
                        module=module,
                        name=alias.name,
                        alias=alias.asname or "",
                        level=node.level or 0,
                    )
                )
    seen: set[tuple[str, str, str, int]] = set()
    unique: list[ImportRef] = []
    for ref in refs:
        key = (ref.module, ref.name, ref.alias, ref.level)
        if key not in seen:
            seen.add(key)
            unique.append(ref)
    return tuple(unique)


def outline_python(path: str, text: str) -> SourceOutline:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return SourceOutline(language="python", docstring="", imports=(), symbols=())

    imports = _collect_imports(tree)
    import_modules = {ref.module.split(".")[0] for ref in imports if ref.module}
    symbols: list[IndexedSymbol] = []

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append(
                _function_symbol(
                    node,
                    path=path,
                    qualname=node.name,
                    import_modules=import_modules,
                )
            )
        elif isinstance(node, ast.ClassDef):
            symbols.append(_class_symbol(node, path=path, import_modules=import_modules))
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols.append(
                        _function_symbol(
                            child,
                            path=path,
                            qualname=f"{node.name}.{child.name}",
                            import_modules=import_modules,
                            kind="method",
                        )
                    )

    return SourceOutline(
        language="python",
        docstring=ast.get_docstring(tree) or "",
        imports=imports,
        symbols=tuple(symbols),
    )
