"""Workspace-relative path helpers shared by the compiler, editor and index."""
from __future__ import annotations

import os
from pathlib import Path

from quetz.domain.exceptions import TaskError
from quetz.domain.task_spec import normalize_rel_path

EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "build",
    "dist",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".uv",
    ".tox",
    "coverage",
    ".next",
    ".turbo",
}

LANGUAGE_BY_EXT = {
    ".py": "python",
    ".pyi": "python",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "jsx",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".json": "json",
    ".md": "markdown",
    ".mdx": "markdown",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".sql": "sql",
    ".css": "css",
    ".html": "html",
    ".vue": "vue",
    ".svelte": "svelte",
}

INDEXABLE_EXTENSIONS = {
    ".py",
    ".pyi",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".json",
    ".sql",
}


def language_for(path: str | Path) -> str:
    return LANGUAGE_BY_EXT.get(Path(path).suffix.lower(), "text")


def is_indexable(path: str | Path) -> bool:
    return Path(path).suffix.lower() in INDEXABLE_EXTENSIONS


def workspace_root(workspace: str | Path) -> Path:
    return Path(workspace).expanduser().resolve()


def resolve_workspace_path(workspace: str | Path, rel_path: str) -> Path:
    """Resolve ``rel_path`` inside ``workspace`` or raise ``TaskError``."""
    rel = normalize_rel_path(rel_path)
    root = workspace_root(workspace)
    candidate = (root / rel).resolve()
    if candidate != root and root not in candidate.parents:
        raise TaskError(f"Path escapes the workspace: {rel_path!r}")
    if ".quetz" in candidate.relative_to(root).parts or ".git" in candidate.relative_to(root).parts:
        raise TaskError(f"Refusing to edit internal path: {rel_path!r}")
    return candidate


def read_text(path: str | Path, *, max_chars: int | None = None) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        data = handle.read()
    if max_chars is not None and len(data) > max_chars:
        return data[:max_chars]
    return data


def read_lines(path: str | Path, start_line: int, end_line: int) -> str:
    start = max(1, start_line)
    end = max(start, end_line)
    lines: list[str] = []
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for index, line in enumerate(handle, start=1):
            if index < start:
                continue
            if index > end:
                break
            lines.append(line)
    return "".join(lines)


def count_lines(text: str) -> int:
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def iter_workspace_files(workspace: str | Path, *, max_bytes: int = 524288):
    """Yield workspace-relative POSIX paths for indexable, non-noisy files."""
    root = workspace_root(workspace)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDED_DIRS and not d.startswith("."))
        for filename in sorted(filenames):
            if filename.startswith(".") and filename not in (".env.example",):
                continue
            full = Path(dirpath) / filename
            if not is_indexable(full):
                continue
            try:
                if full.stat().st_size > max_bytes:
                    continue
            except OSError:
                continue
            yield full.relative_to(root).as_posix()
