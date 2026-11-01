"""Append-only Markdown project memory."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from quetz import config as q_config
from quetz.application.ports.memory import MemoryEntry
from quetz.infrastructure.fs.paths import workspace_root


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")


def _one_line(text: str) -> str:
    return " ".join((text or "").split())


class FileMemoryStore:
    def __init__(self, workspace: str, path: str | Path | None = None) -> None:
        root = workspace_root(workspace)
        self.path = Path(path) if path else root / q_config.QUETZ_DIR / q_config.MEMORY_FILE

    def add(self, entry: MemoryEntry) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        header = "# Project memory\n\n" if not self.path.exists() else ""
        created = entry.created_at or _now()
        line = f"- [{created}] {entry.kind}"
        if entry.path:
            line += f" ({entry.path})"
        line += f": {_one_line(entry.content)}\n"
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(header + line)

    def _entries(self) -> list[MemoryEntry]:
        if not self.path.is_file():
            return []
        entries: list[MemoryEntry] = []
        for line in self.path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if not stripped.startswith("- ["):
                continue
            entries.append(MemoryEntry(kind="note", path="", content=stripped))
        return entries

    def recent(self, *, limit: int = 10) -> list[MemoryEntry]:
        return self._entries()[-limit:]

    def for_paths(self, paths: list[str], *, limit: int = 10) -> list[MemoryEntry]:
        wanted = [path.strip() for path in paths if path and path.strip()]
        if not wanted:
            return self.recent(limit=limit)
        matches = [
            entry
            for entry in self._entries()
            if any(path in entry.content for path in wanted)
        ]
        return matches[-limit:]
