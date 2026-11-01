"""Bounded, deterministic directory-tree rendering for prompts."""
from __future__ import annotations

import os
from pathlib import Path

from quetz.infrastructure.fs.paths import EXCLUDED_DIRS


def build_tree(root: str | Path, *, max_depth: int = 3, max_entries: int = 200) -> str:
    root_path = Path(root)
    lines: list[str] = []
    count = 0

    def walk(directory: Path, depth: int, prefix: str) -> None:
        nonlocal count
        if depth > max_depth or count >= max_entries:
            return
        try:
            entries = sorted(os.listdir(directory))
        except OSError:
            return
        entries = [
            e
            for e in entries
            if not (e.startswith(".") and e != ".env.example") and e not in EXCLUDED_DIRS
        ]
        for index, entry in enumerate(entries):
            if count >= max_entries:
                lines.append(f"{prefix}... [tree truncated at {max_entries} entries]")
                return
            full = directory / entry
            is_last = index == len(entries) - 1
            connector = "└── " if is_last else "├── "
            suffix = "/" if full.is_dir() else ""
            lines.append(f"{prefix}{connector}{entry}{suffix}")
            count += 1
            if full.is_dir():
                child_prefix = prefix + ("    " if is_last else "│   ")
                walk(full, depth + 1, child_prefix)

    walk(root_path, 1, "")
    return "\n".join(lines) if lines else "(empty workspace)"
