"""Change-spec value objects for the improvement pipeline.

The analyzer (cloud) produces a ChangeSpec: *what* to improve and *why*.
The executor (local) turns it into an EditPlan: *how* to change the code.
This separation keeps cloud=thinking and local=coding.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from quetz.domain.exceptions import EditError


@dataclass(frozen=True, slots=True)
class ChangeSpecItem:
    """One targeted change: file + action + what to change."""

    file: str
    action: str  # replace | append | prepend
    locate: str = ""  # human description of where (for the executor)
    instruction: str = ""  # what to change
    content: str = ""  # for append/prepend: the content to add

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "action": self.action,
            "locate": self.locate,
            "instruction": self.instruction,
            "content": self.content,
        }


@dataclass(frozen=True, slots=True)
class ChangeSpec:
    """A list of targeted changes produced by the analyzer."""

    changes: tuple[ChangeSpecItem, ...]
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "changes": [c.to_dict() for c in self.changes],
        }

    def render(self) -> str:
        """Render as a prompt fragment for the executor."""
        lines: list[str] = []
        for c in self.changes:
            if c.action == "replace":
                lines.append(f"- **{c.file}** — replace: {c.locate or 'the relevant block'}")
                lines.append(f"  Change: {c.instruction}")
            else:
                lines.append(f"- **{c.file}** — {c.action}: {c.instruction or c.content[:80]}")
        return "\n".join(lines)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChangeSpec":
        if not isinstance(data, dict):
            raise EditError(f"Invalid ChangeSpec payload: {data!r}")
        raw = data.get("changes", ()) or ()
        if not isinstance(raw, (list, tuple)):
            raise EditError("ChangeSpec 'changes' must be a list.")
        changes = []
        for item in raw:
            if not isinstance(item, dict):
                raise EditError(f"Invalid change item: {item!r}")
            action = str(item.get("action", "replace")).lower()
            if action not in ("replace", "append", "prepend"):
                raise EditError(f"Unknown change action: {action!r}")
            changes.append(
                ChangeSpecItem(
                    file=str(item.get("file", "")),
                    action=action,
                    locate=str(item.get("locate", "")),
                    instruction=str(item.get("instruction", "")),
                    content=str(item.get("content", "")),
                )
            )
        return cls(
            changes=tuple(changes),
            summary=str(data.get("summary", "")),
        )


def parse_change_spec(text: str) -> ChangeSpec:
    """Parse raw model text into a validated ChangeSpec."""
    from quetz.domain.edit import extract_json_object

    data = extract_json_object(text)
    if data is None:
        raise EditError("Analyzer response did not contain a JSON object.")
    return ChangeSpec.from_dict(data)
