"""Atomic application and rollback of structured edit plans."""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from quetz.domain.edit import EditOp, EditPlan
from quetz.domain.task_spec import TaskSpec
from quetz.infrastructure.fs.paths import (
    read_text,
    resolve_workspace_path,
    workspace_root,
)


@dataclass(slots=True)
class ApplyResult:
    ok: bool
    error: str = ""
    changed_paths: tuple[str, ...] = ()
    originals: dict[str, str | None] = field(default_factory=dict)


class AtomicEditor:
    """Apply a plan to the workspace with preflight checks and rollback."""

    def __init__(self, workspace: str) -> None:
        self.workspace = workspace_root(workspace)

    def apply(self, plan: EditPlan, task: TaskSpec) -> ApplyResult:
        if plan.blocked:
            return ApplyResult(
                ok=False,
                error=plan.reason or plan.summary or "Executor reported a blocked task.",
            )
        if not plan.edits:
            return ApplyResult(ok=False, error="Edit plan contains no edits.")

        allowed = set(task.editable_files)
        final_contents: dict[str, str] = {}
        originals: dict[str, str | None] = {}

        for edit in plan.edits:
            rel_path = edit.file
            if rel_path not in allowed:
                return ApplyResult(
                    ok=False,
                    error=(
                        f"Edit targets {rel_path!r}, which is not listed in task files "
                        f"or allowed_new_files."
                    ),
                )
            try:
                full_path = resolve_workspace_path(self.workspace, rel_path)
            except Exception as exc:
                return ApplyResult(ok=False, error=str(exc))

            if rel_path in final_contents:
                current = final_contents[rel_path]
            else:
                if full_path.is_file():
                    current = read_text(full_path)
                    originals[rel_path] = current
                else:
                    current = ""
                    originals[rel_path] = None

            if edit.op is EditOp.CREATE:
                if originals.get(rel_path) is not None:
                    return ApplyResult(
                        ok=False,
                        error=f"Cannot create {rel_path!r}: it already exists. Use op='replace'.",
                    )
                final_contents[rel_path] = edit.content
                continue

            if edit.op is EditOp.APPEND:
                if originals.get(rel_path) is None and rel_path not in final_contents:
                    return ApplyResult(
                        ok=False,
                        error=f"Cannot append to {rel_path!r}: file does not exist. Use op='create'.",
                    )
                separator = "\n" if current and not current.endswith("\n") else ""
                final_contents[rel_path] = current + separator + edit.content
                continue

            if edit.op is EditOp.PREPEND:
                if originals.get(rel_path) is None and rel_path not in final_contents:
                    return ApplyResult(
                        ok=False,
                        error=f"Cannot prepend to {rel_path!r}: file does not exist. Use op='create'.",
                    )
                separator = "\n" if current and not current.startswith("\n") else ""
                final_contents[rel_path] = edit.content + separator + current
                continue

            if edit.op is EditOp.REPLACE:
                if originals.get(rel_path) is None and rel_path not in final_contents:
                    return ApplyResult(
                        ok=False,
                        error=f"Cannot replace in {rel_path!r}: file does not exist. Use op='create'.",
                    )
                if not edit.find:
                    return ApplyResult(
                        ok=False,
                        error=f"Replace edit for {rel_path!r} has an empty find anchor.",
                    )
                count = current.count(edit.find)
                if count == 0:
                    preview = repr(edit.find[:120])
                    return ApplyResult(
                        ok=False,
                        error=(
                            f"find block not found in {rel_path!r}. "
                            f"Got: {preview}. "
                            "Copy the anchor exactly from the supplied file text "
                            "including whitespace and line breaks."
                        ),
                    )
                if count > 1:
                    preview = repr(edit.find[:120])
                    return ApplyResult(
                        ok=False,
                        error=(
                            f"find block matches {count} times in {rel_path!r}. "
                            f"Got: {preview}. "
                            "Include more surrounding lines so the anchor is unique."
                        ),
                    )
                final_contents[rel_path] = current.replace(edit.find, edit.replace, 1)
                continue

            return ApplyResult(ok=False, error=f"Unsupported edit operation: {edit.op!r}")

        # Strip unused imports before writing (prevents TS6133 errors)
        for rel_path in final_contents:
            if rel_path.endswith((".py", ".ts", ".tsx", ".js", ".jsx")):
                final_contents[rel_path] = self._strip_unused_imports(
                    final_contents[rel_path], rel_path
                )

        written: list[str] = []
        try:
            for rel_path, content in final_contents.items():
                full_path = resolve_workspace_path(self.workspace, rel_path)
                full_path.parent.mkdir(parents=True, exist_ok=True)
                self._atomic_write(full_path, content)
                written.append(rel_path)
        except Exception as exc:
            for rel_path in written:
                self._restore(rel_path, originals.get(rel_path))
            return ApplyResult(
                ok=False,
                error=f"Failed while writing edits: {exc}",
                originals=originals,
            )

        return ApplyResult(
            ok=True,
            changed_paths=tuple(final_contents),
            originals=originals,
        )

    def revert(self, result: ApplyResult) -> None:
        for rel_path, original in result.originals.items():
            self._restore(rel_path, original)

    @staticmethod
    def _strip_unused_imports(content: str, path: str) -> str:
        """Remove imports whose names are never used in the file body."""
        import re as _re

        lines = content.split("\n")
        import_lines = []
        body_lines = []
        in_import = False

        for line in lines:
            stripped = line.strip()
            if _re.match(r"^(import |from |const .* = require\(|import\()", stripped):
                in_import = True
                import_lines.append(line)
            elif in_import and (stripped.startswith(("(", ")", "{", "}", "  ", "  ")) or stripped.endswith((",", "(", "{"))):
                import_lines.append(line)
            else:
                in_import = False
                body_lines.append(line)

        body_text = "\n".join(body_lines)
        kept = []
        for line in import_lines:
            # Extract imported names
            names = set()
            # from X import A, B, C
            m = _re.match(r"^from\s+\S+\s+import\s+(.+)$", line.strip())
            if m:
                for part in m.group(1).split(","):
                    part = part.strip()
                    if " as " in part:
                        part = part.split(" as ")[1].strip()
                    if part and part != "*":
                        names.add(part.split(".")[0])
            # import X, Y
            m = _re.match(r"^import\s+(.+)$", line.strip())
            if m:
                for part in m.group(1).split(","):
                    part = part.strip().split(" as ")[-1].strip()
                    if part:
                        names.add(part.split(".")[0])

            # Check if any name is used in body
            used = any(
                _re.search(r"\b" + _re.escape(name) + r"\b", body_text)
                for name in names
            )
            if used or not names:
                kept.append(line)

        return "\n".join(kept + body_lines)

    def _restore(self, rel_path: str, original: str | None) -> None:
        full_path = resolve_workspace_path(self.workspace, rel_path)
        if original is None:
            try:
                full_path.unlink()
            except FileNotFoundError:
                pass
            return
        full_path.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write(full_path, original)

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".quetz-tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
            os.replace(temp_name, path)
        except Exception:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise
