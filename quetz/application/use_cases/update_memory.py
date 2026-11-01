"""Record deterministic task outcomes in durable project memory."""
from __future__ import annotations

from quetz.application.ports.memory import MemoryEntry, MemoryStorePort
from quetz.domain.edit import ExecutionResult
from quetz.domain.task_spec import TaskSpec


class UpdateMemoryUseCase:
    def __init__(self, store: MemoryStorePort) -> None:
        self._store = store

    def record(self, task: TaskSpec, result: ExecutionResult) -> None:
        if result.ok:
            changed = ", ".join(result.changed_paths) or "no files"
            content = f"{task.title}: {result.summary or 'completed'}; changed {changed}"
            kind = "task-done"
        else:
            content = f"{task.title}: {result.error or 'blocked'}"
            kind = "task-blocked"
        self._store.add(
            MemoryEntry(
                kind=kind,
                path=result.changed_paths[0] if result.changed_paths else "",
                content=content,
            )
        )
