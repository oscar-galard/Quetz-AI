"""Edit-plan value objects and execution results.

The local model never receives tools or conversation history. It returns a
single JSON document shaped like :class:`EditPlan`; this module parses and
validates that document without touching the filesystem.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from quetz.domain.exceptions import EditError
from quetz.domain.task_spec import normalize_rel_path


class EditOp(str, Enum):
    CREATE = "create"
    REPLACE = "replace"


_OP_ALIASES = {
    "create": EditOp.CREATE,
    "write": EditOp.CREATE,
    "new": EditOp.CREATE,
    "replace": EditOp.REPLACE,
    "edit": EditOp.REPLACE,
    "update": EditOp.REPLACE,
    "patch": EditOp.REPLACE,
}


@dataclass(frozen=True, slots=True)
class FileEdit:
    file: str
    op: EditOp
    content: str = ""
    find: str = ""
    replace: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "file", normalize_rel_path(self.file))
        if self.op is EditOp.REPLACE and not self.find:
            raise EditError(f"Replace edit for {self.file!r} has an empty 'find' anchor.")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FileEdit":
        if not isinstance(data, dict):
            raise EditError(f"Invalid edit payload: {data!r}")
        raw_op = str(data.get("op") or data.get("operation") or "replace").lower()
        op = _OP_ALIASES.get(raw_op)
        if op is None:
            raise EditError(f"Unknown edit operation: {raw_op!r}")
        return cls(
            file=str(data.get("file") or data.get("path") or ""),
            op=op,
            content=str(data.get("content", "")),
            find=str(data.get("find") or data.get("old") or data.get("search") or ""),
            replace=str(
                data.get("replace") or data.get("new") or data.get("replacement") or ""
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "op": self.op.value,
            "content": self.content,
            "find": self.find,
            "replace": self.replace,
        }


@dataclass(frozen=True, slots=True)
class EditPlan:
    task_id: str
    status: str
    edits: tuple[FileEdit, ...] = ()
    summary: str = ""
    assumptions: tuple[str, ...] = ()
    reason: str = ""

    def __post_init__(self) -> None:
        status = (self.status or "done").strip().lower()
        if status not in ("done", "blocked"):
            raise EditError(f"EditPlan status must be 'done' or 'blocked', got {status!r}.")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "task_id", (self.task_id or "").strip())
        if status == "done" and not self.edits:
            raise EditError("EditPlan status is 'done' but it contains no edits.")
        if status == "blocked" and not (self.reason or self.summary):
            raise EditError("Blocked EditPlan must include a reason.")

    @property
    def blocked(self) -> bool:
        return self.status == "blocked"

    @classmethod
    def from_dict(cls, data: dict[str, Any], task_id: str | None = None) -> "EditPlan":
        if not isinstance(data, dict):
            raise EditError(f"Invalid EditPlan payload: {data!r}")
        raw_edits = data.get("edits", ()) or ()
        if not isinstance(raw_edits, (list, tuple)):
            raise EditError("EditPlan 'edits' must be a list.")
        raw_assumptions = data.get("assumptions", ()) or ()
        if isinstance(raw_assumptions, str):
            raw_assumptions = (raw_assumptions,)
        return cls(
            task_id=str(task_id or data.get("task_id", "")),
            status=str(data.get("status", "done")),
            edits=tuple(FileEdit.from_dict(e) for e in raw_edits),
            summary=str(data.get("summary", "")),
            assumptions=tuple(str(a) for a in raw_assumptions),
            reason=str(data.get("reason", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "summary": self.summary,
            "edits": [e.to_dict() for e in self.edits],
            "assumptions": list(self.assumptions),
            "reason": self.reason,
        }


def _fix_json(text: str) -> str:
    """Fix common JSON quirks from local models (escaped quotes, trailing commas)."""
    # Fix literal backslash-quotes that appear at string boundaries
    # Pattern: "value": \"text\" -> "value": "text"
    text = re.sub(r'(?<=": )\\"(.+?)\\"(?=[,\s}])', r'"\1"', text)
    # Remove trailing commas before } or ]
    text = re.sub(r',\s*([}\]])', r'\1', text)
    return text


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Extract the first JSON object from model output, tolerating prose/fences."""
    if not text:
        return None

    candidate = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", candidate, re.DOTALL)
    if fence:
        candidate = fence.group(1).strip()

    # Try parsing as-is first
    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass

    # Try with common fixes
    fixed = _fix_json(candidate)
    try:
        parsed = json.loads(fixed)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass

    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", candidate):
        try:
            parsed, _ = decoder.raw_decode(candidate[match.start():])
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed

    # Last resort: try fixed version with raw_decode
    for match in re.finditer(r"\{", fixed):
        try:
            parsed, _ = decoder.raw_decode(fixed[match.start():])
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def parse_edit_plan(text: str, expected_task_id: str) -> EditPlan:
    """Parse raw model text into a validated :class:`EditPlan`."""
    data = extract_json_object(text)
    if data is None:
        raise EditError(
            "Model response did not contain a JSON object. "
            "Return ONLY the edit-plan JSON document."
        )
    return EditPlan.from_dict(data, task_id=expected_task_id)


@dataclass(frozen=True, slots=True)
class CommandResult:
    command: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    expected_exit: int = 0

    @property
    def ok(self) -> bool:
        return not self.timed_out and self.exit_code == self.expected_exit


@dataclass(frozen=True, slots=True)
class ValidationResult:
    ok: bool
    results: tuple[CommandResult, ...] = ()
    syntax_error: str = ""

    @property
    def summary(self) -> str:
        if self.syntax_error:
            return f"Syntax check failed:\n{self.syntax_error}"
        lines: list[str] = []
        for result in self.results:
            if result.ok:
                continue
            lines.append(f"Command failed: {result.command}")
            if result.timed_out:
                lines.append("  timed out")
            else:
                lines.append(f"  exit code: {result.exit_code}")
            if result.stdout.strip():
                lines.append("  stdout:\n" + _indent(result.stdout.strip()))
            if result.stderr.strip():
                lines.append("  stderr:\n" + _indent(result.stderr.strip()))
        return "\n".join(lines) if lines else "Validation failed."

    def render(self, limit: int = 4000) -> str:
        text = self.summary
        return text if len(text) <= limit else text[:limit] + "\n...[truncated]..."


def _indent(text: str) -> str:
    return "\n".join("    " + line for line in text.splitlines())


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    task_id: str
    ok: bool
    status: str
    attempts: int
    summary: str = ""
    error: str = ""
    changed_paths: tuple[str, ...] = ()
    validation: ValidationResult | None = field(default=None)
