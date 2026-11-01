"""Project memory port: durable notes about architecture and past tasks."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class MemoryEntry:
    kind: str
    content: str
    path: str = ""
    created_at: str = ""


@runtime_checkable
class MemoryStorePort(Protocol):
    def add(self, entry: MemoryEntry) -> None: ...

    def recent(self, *, limit: int = 10) -> list[MemoryEntry]: ...

    def for_paths(self, paths: list[str], *, limit: int = 10) -> list[MemoryEntry]: ...
