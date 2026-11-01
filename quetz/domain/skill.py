"""Dynamic-skill value objects.

A :class:`SkillSection` is one bounded fragment from a skill Markdown file:
a header, a body, and a tag set. The Context Compiler pulls only the
task-relevant sections into the prompt — the rest stays on disk.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SkillSection:
    """A single skill fragment: file source + header + body + tags + layer."""

    source: str
    title: str
    body: str
    tags: tuple[str, ...] = ()
    layer: str = ""

    @property
    def size(self) -> int:
        return len(self.body)
