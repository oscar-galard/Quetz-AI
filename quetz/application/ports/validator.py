"""Validation port: deterministic acceptance checks for an executed task."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from quetz.domain.edit import ValidationResult
from quetz.domain.task_spec import TaskSpec


@runtime_checkable
class ValidationPort(Protocol):
    def validate(self, task: TaskSpec, changed_paths: list[str]) -> ValidationResult:
        """Run syntax checks and acceptance commands for the task."""
