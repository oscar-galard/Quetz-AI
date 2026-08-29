"""Output ports for the application.

- :class:`ReportWriter`: persists generated artifacts (e.g. architecture
  reports) to a destination. Implemented by a filesystem adapter in infra.
- :class:`PlanApprover`: decides whether to approve, abort, or refine a
  proposed plan. Implemented by a CLI/interactive adapter in presentation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable


@runtime_checkable
class ReportWriter(Protocol):
    """Persists a generated report and returns a summary description."""

    def write(self, filename: str, content: str) -> str:
        """Write ``content`` to ``filename`` and return a status summary."""
        ...


@dataclass(frozen=True, slots=True)
class Approval:
    """User's decision about a proposed plan."""

    status: Literal["approved", "abort", "refine"]
    feedback: str = ""


@runtime_checkable
class PlanApprover(Protocol):
    """Asks the user how to proceed with a proposed plan."""

    def decide(self, plan: str) -> Approval:
        """Return the user's decision for the given proposed plan."""
        ...
