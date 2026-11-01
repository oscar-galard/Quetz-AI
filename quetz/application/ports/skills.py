"""Application-layer port for the dynamic skills index."""
from __future__ import annotations

from typing import Iterable, Protocol, runtime_checkable

from quetz.domain.skill import SkillSection
from quetz.domain.task_spec import TaskSpec


@runtime_checkable
class SkillIndexPort(Protocol):
    """Index the ``skills/`` directory and retrieve task-relevant sections."""

    def build(self) -> int:
        """Parse every skill file. Return the number of sections indexed."""

    def ensure_built(self) -> None:
        """Build the index lazily if not yet loaded."""

    def retrieve(
        self,
        task: TaskSpec,
        *,
        stack_tags: Iterable[str],
        language: str,
        limit_chars: int,
    ) -> list[SkillSection]:
        """Return the top sections that fit within ``limit_chars``."""
