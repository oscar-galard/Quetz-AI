"""SQLite-backed project index with incremental file/symbol/import storage."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from quetz import config as q_config
from quetz.application.ports.index import ImportRef, IndexedFile, IndexedSymbol
from quetz.infrastructure.fs.paths import (
    iter_workspace_files,
    language_for,
    workspace_root,
)
from quetz.infrastructure.index.base import SourceOutline
from quetz.infrastructure.index.python_ast import outline_python
from quetz.infrastructure.index.typescript_outline import outline_typescript

_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY,
    language TEXT NOT NULL,
    hash TEXT NOT NULL,
    mtime REAL NOT NULL,
    docstring TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS symbols (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL,
    name TEXT NOT NULL,
    qualname TEXT NOT NULL,
    kind TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    signature TEXT NOT NULL DEFAULT '',
    docstring TEXT NOT NULL DEFAULT '',
    decorators TEXT NOT NULL DEFAULT '[]',
    bases TEXT NOT NULL DEFAULT '[]',
    tags TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    src TEXT NOT NULL,
    module TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    alias TEXT NOT NULL DEFAULT '',
    level INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_symbols_path ON symbols(path);
CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_imports_src ON imports(src);
"""


def _json_tuple(values: tuple[str, ...]) -> str:
    return json.dumps(list(values))


def _load_tuple(value: str) -> tuple[str, ...]:
    try:
        data = json.loads(value or "[]")
    except Exception:
        return ()
    return tuple(str(v) for v in data) if isinstance(data, list) else ()


class SqliteProjectIndex:
    """Index the workspace into ``.quetz/index.db``.

    The index is intentionally simple and deterministic: hashes/mtimes drive
    incremental refreshes, and all queries return neutral records from the
    application port.
    """

    def __init__(self, workspace: str, db_path: str | Path | None = None) -> None:
        self.workspace = workspace_root(workspace)
        self.db_path = Path(db_path) if db_path else self.workspace / q_config.QUETZ_DIR / q_config.INDEX_DB

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()

    def _init(self, connection: sqlite3.Connection) -> None:
        connection.executescript(_SCHEMA)
        connection.commit()

    def build(self, *, force: bool = False) -> int:
        with self._connect() as connection:
            self._init(connection)
            if force:
                connection.executescript(
                    "DELETE FROM symbols; DELETE FROM imports; DELETE FROM files; DELETE FROM meta;"
                )
                existing: dict[str, str] = {}
            else:
                existing = {
                    row["path"]: row["hash"] for row in connection.execute("SELECT path, hash FROM files")
                }

            changed = 0
            seen: set[str] = set()
            for rel_path in iter_workspace_files(self.workspace, max_bytes=q_config.INDEX_MAX_FILE_BYTES):
                seen.add(rel_path)
                full_path = self.workspace / rel_path
                try:
                    raw = full_path.read_text(encoding="utf-8", errors="replace")
                    mtime = full_path.stat().st_mtime
                except OSError:
                    continue
                digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
                if not force and existing.get(rel_path) == digest:
                    continue

                outline = self._outline(rel_path, raw)
                self._replace_file(connection, rel_path, raw, digest, mtime, outline)
                changed += 1

            for stale in set(existing) - seen:
                connection.execute("DELETE FROM symbols WHERE path = ?", (stale,))
                connection.execute("DELETE FROM imports WHERE src = ?", (stale,))
                connection.execute("DELETE FROM files WHERE path = ?", (stale,))
                changed += 1

            connection.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('built_at', datetime('now'))"
            )
            connection.commit()
            return changed

    def ensure_built(self) -> None:
        if not self.db_path.exists():
            self.build()
            return
        try:
            with self._connect() as connection:
                self._init(connection)
                row = connection.execute("SELECT COUNT(*) AS n FROM files").fetchone()
                empty = row is None or row["n"] == 0
            if empty:
                self.build()
        except sqlite3.DatabaseError:
            self.build(force=True)

    @staticmethod
    def _outline(path: str, text: str) -> SourceOutline:
        language = language_for(path)
        if language == "python":
            return outline_python(path, text)
        if language in ("typescript", "tsx", "javascript", "jsx"):
            return outline_typescript(path, text)
        return SourceOutline(language=language, docstring="", imports=(), symbols=())

    @staticmethod
    def _replace_file(
        connection: sqlite3.Connection,
        path: str,
        raw: str,
        digest: str,
        mtime: float,
        outline: SourceOutline,
    ) -> None:
        connection.execute("DELETE FROM symbols WHERE path = ?", (path,))
        connection.execute("DELETE FROM imports WHERE src = ?", (path,))
        connection.execute(
            "INSERT OR REPLACE INTO files(path, language, hash, mtime, docstring) VALUES (?, ?, ?, ?, ?)",
            (path, outline.language, digest, mtime, outline.docstring),
        )
        for symbol in outline.symbols:
            connection.execute(
                """
                INSERT INTO symbols(
                    path, name, qualname, kind, start_line, end_line, signature,
                    docstring, decorators, bases, tags
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol.path,
                    symbol.name,
                    symbol.qualname,
                    symbol.kind,
                    symbol.start_line,
                    symbol.end_line,
                    symbol.signature,
                    symbol.docstring,
                    _json_tuple(symbol.decorators),
                    _json_tuple(symbol.bases),
                    _json_tuple(symbol.tags),
                ),
            )
        for ref in outline.imports:
            connection.execute(
                "INSERT INTO imports(src, module, name, alias, level) VALUES (?, ?, ?, ?, ?)",
                (path, ref.module, ref.name, ref.alias, ref.level),
            )

    def file(self, path: str) -> IndexedFile | None:
        with self._connect() as connection:
            self._init(connection)
            row = connection.execute("SELECT * FROM files WHERE path = ?", (path,)).fetchone()
            if row is None:
                return None
            symbols = self.symbols(path=path)
            imports = self.imports_of(path)
            return IndexedFile(
                path=row["path"],
                language=row["language"],
                hash=row["hash"],
                mtime=row["mtime"],
                docstring=row["docstring"],
                imports=imports,
                symbols=tuple(symbols),
            )

    def files(self) -> list[IndexedFile]:
        with self._connect() as connection:
            self._init(connection)
            rows = connection.execute("SELECT * FROM files ORDER BY path").fetchall()
            return [
                IndexedFile(
                    path=row["path"],
                    language=row["language"],
                    hash=row["hash"],
                    mtime=row["mtime"],
                    docstring=row["docstring"],
                )
                for row in rows
            ]

    def symbols(
        self,
        *,
        path: str | None = None,
        name: str | None = None,
        query: str | None = None,
    ) -> list[IndexedSymbol]:
        clauses: list[str] = []
        params: list[str] = []
        if path:
            clauses.append("path = ?")
            params.append(path)
        if name:
            clauses.append("(name = ? OR qualname = ?)")
            params.extend([name, name])
        if query:
            clauses.append("(name LIKE ? OR signature LIKE ? OR docstring LIKE ? OR tags LIKE ?)")
            like = f"%{query}%"
            params.extend([like, like, like, like])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            self._init(connection)
            rows = connection.execute(
                f"SELECT * FROM symbols {where} ORDER BY path, start_line", params
            ).fetchall()
            return [self._row_to_symbol(row) for row in rows]

    @staticmethod
    def _row_to_symbol(row: sqlite3.Row) -> IndexedSymbol:
        return IndexedSymbol(
            path=row["path"],
            name=row["name"],
            qualname=row["qualname"],
            kind=row["kind"],
            start_line=row["start_line"],
            end_line=row["end_line"],
            signature=row["signature"],
            docstring=row["docstring"],
            decorators=_load_tuple(row["decorators"]),
            bases=_load_tuple(row["bases"]),
            tags=_load_tuple(row["tags"]),
        )

    def imports_of(self, path: str) -> list[ImportRef]:
        with self._connect() as connection:
            self._init(connection)
            rows = connection.execute(
                "SELECT module, name, alias, level FROM imports WHERE src = ? ORDER BY id",
                (path,),
            ).fetchall()
            return [
                ImportRef(
                    module=row["module"],
                    name=row["name"],
                    alias=row["alias"],
                    level=row["level"],
                )
                for row in rows
            ]

    def dependents_of(self, path: str) -> list[str]:
        dependents: list[str] = []
        for indexed in self.files():
            for ref in self.imports_of(indexed.path):
                if self.resolve_import(indexed.path, ref.module) == path:
                    dependents.append(indexed.path)
                    break
        return dependents

    def resolve_import(
        self,
        src_path: str,
        module: str,
        *,
        level: int = 0,
        name: str = "",
    ) -> str | None:
        module = (module or "").strip()
        if not module and not name:
            return None

        candidates: list[str] = []
        src_dir = Path(src_path).parent

        if level > 0:
            base = src_dir
            for _ in range(max(0, level - 1)):
                base = base.parent
            if module:
                base = base / module.replace(".", "/")
            if name and not module:
                base = base / name
            candidates.extend(self._with_extensions(base.as_posix()))
            candidates.append((base / "__init__.py").as_posix())
        elif module.startswith("."):
            base = (src_dir / module).as_posix()
            candidates.extend(self._with_extensions(base))
        elif module.startswith("@/"):
            tail = module[2:]
            candidates.extend(self._with_extensions(f"src/{tail}"))
            candidates.extend(self._with_extensions(tail))
        else:
            pythonish = module.replace(".", "/")
            candidates.append(f"{pythonish}.py")
            candidates.append(f"{pythonish}/__init__.py")
            candidates.extend(self._with_extensions(module))
            # Also try common source roots.
            for root in ("src", "app", "backend", "frontend/src"):
                candidates.extend(self._with_extensions(f"{root}/{module}"))

        known = {indexed.path for indexed in self.files()}
        for candidate in candidates:
            normalized = candidate.replace("\\", "/").lstrip("./")
            if normalized in known:
                return normalized

        # Last resort: suffix match by module path (handles monorepo roots).
        module_path = (module or name).replace(".", "/").lstrip("./")
        if not module_path:
            return None
        for known_path in sorted(known):
            if known_path.endswith(module_path) or known_path.endswith(f"{module_path}.py"):
                return known_path
            if known_path.endswith(f"{module_path}.ts") or known_path.endswith(f"{module_path}.tsx"):
                return known_path
        return None

    @staticmethod
    def _with_extensions(base: str) -> list[str]:
        base = base.replace("\\", "/")
        suffix = Path(base).suffix
        if suffix:
            return [base]
        return [
            f"{base}.ts",
            f"{base}.tsx",
            f"{base}.js",
            f"{base}.jsx",
            f"{base}.py",
            f"{base}/index.ts",
            f"{base}/index.tsx",
            f"{base}/index.js",
        ]
