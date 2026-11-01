"""Shared outline record returned by language extractors."""
from __future__ import annotations

from dataclasses import dataclass

from quetz.application.ports.index import ImportRef, IndexedSymbol


@dataclass(frozen=True, slots=True)
class SourceOutline:
    language: str
    docstring: str
    imports: tuple[ImportRef, ...]
    symbols: tuple[IndexedSymbol, ...]
