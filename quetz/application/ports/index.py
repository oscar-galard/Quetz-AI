"""Project index port and neutral index records.

The Context Compiler depends on this interface only. The SQLite/tree-sitter
implementation lives in infrastructure, which keeps the compiler testable with
an in-memory fake index.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class ImportRef:
    module: str
    name: str = ""
    alias: str = ""
    level: int = 0


@dataclass(frozen=True, slots=True)
class IndexedSymbol:
    path: str
    name: str
    qualname: str
    kind: str
    start_line: int
    end_line: int
    signature: str = ""
    docstring: str = ""
    decorators: tuple[str, ...] = ()
    bases: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class IndexedFile:
    path: str
    language: str
    hash: str
    mtime: float
    docstring: str = ""
    imports: tuple[ImportRef, ...] = ()
    symbols: tuple[IndexedSymbol, ...] = ()


@runtime_checkable
class ProjectIndexPort(Protocol):
    def build(self, *, force: bool = False) -> int:
        """Index or refresh the workspace; return the number of changed files."""

    def ensure_built(self) -> None:
        """Build the index if it does not exist yet."""

    def file(self, path: str) -> IndexedFile | None: ...

    def files(self) -> list[IndexedFile]: ...

    def symbols(
        self,
        *,
        path: str | None = None,
        name: str | None = None,
        query: str | None = None,
    ) -> list[IndexedSymbol]: ...

    def imports_of(self, path: str) -> list[ImportRef]: ...

    def dependents_of(self, path: str) -> list[str]: ...

    def resolve_import(
        self,
        src_path: str,
        module: str,
        *,
        level: int = 0,
        name: str = "",
    ) -> str | None: ...
