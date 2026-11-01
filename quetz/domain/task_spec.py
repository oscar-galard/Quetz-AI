"""Task queue value objects for the stateless execution pipeline.

A :class:`TaskSpec` is a self-contained, vertically sliced unit of work. The
cloud planner produces a :class:`Plan`; the executor consumes one task at a
time and never needs any other task's conversation history.
"""
from __future__ import annotations

import posixpath
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

from quetz.domain.exceptions import TaskError


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    BLOCKED = "blocked"
    FAILED = "failed"


VALID_LAYERS = ("", "domain", "application", "interface", "infrastructure")


def normalize_rel_path(path: str) -> str:
    """Return a clean workspace-relative POSIX path or raise ``TaskError``."""
    raw = (path or "").strip().replace("\\", "/")
    if not raw:
        raise TaskError("Task path must not be empty.")
    if raw.startswith("/") or (len(raw) > 1 and raw[1] == ":"):
        raise TaskError(f"Task paths must be workspace-relative: {path!r}")
    normalized = posixpath.normpath(raw)
    if normalized == ".." or normalized.startswith("../"):
        raise TaskError(f"Task path escapes the workspace: {path!r}")
    if normalized.startswith(".git/") or normalized == ".git":
        raise TaskError(f"Task path may not target git internals: {path!r}")
    return normalized


@dataclass(frozen=True, slots=True)
class AcceptanceCriterion:
    command: str
    expect_exit: int = 0
    timeout: int = 300

    def __post_init__(self) -> None:
        command = (self.command or "").strip()
        if not command:
            raise TaskError("Acceptance command must not be empty.")
        object.__setattr__(self, "command", command)
        if self.expect_exit < 0:
            raise TaskError("expect_exit must be >= 0.")
        if self.timeout <= 0:
            raise TaskError("timeout must be > 0.")

    @classmethod
    def from_dict(cls, data: Any) -> "AcceptanceCriterion":
        if isinstance(data, str):
            return cls(command=data)
        if isinstance(data, dict):
            return cls(
                command=str(data.get("command", "")),
                expect_exit=int(data.get("expect_exit", 0)),
                timeout=int(data.get("timeout", 300)),
            )
        raise TaskError(f"Invalid acceptance criterion: {data!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "expect_exit": self.expect_exit,
            "timeout": self.timeout,
        }


@dataclass(frozen=True, slots=True)
class TaskSpec:
    id: str
    title: str
    goal: str
    prompt: str = ""
    files: tuple[str, ...] = ()
    allowed_new_files: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()
    interfaces: tuple[str, ...] = ()
    acceptance: tuple[AcceptanceCriterion, ...] = ()
    depends_on: tuple[str, ...] = ()
    max_attempts: int = 2
    status: TaskStatus = TaskStatus.PENDING
    notes: str = ""
    layer: str = ""
    setup_commands: tuple[str, ...] = ()
    conventions: str = ""

    def __post_init__(self) -> None:
        task_id = (self.id or "").strip()
        title = (self.title or "").strip()
        goal = (self.goal or "").strip()
        if not task_id:
            raise TaskError("Task id must not be empty.")
        if not title:
            raise TaskError(f"Task {task_id!r} title must not be empty.")
        if not goal:
            raise TaskError(f"Task {task_id!r} goal must not be empty.")
        if self.max_attempts <= 0:
            raise TaskError(f"Task {task_id!r} max_attempts must be > 0.")

        object.__setattr__(self, "id", task_id)
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "goal", goal)
        object.__setattr__(self, "prompt", (self.prompt or "").strip() or goal)
        object.__setattr__(self, "files", tuple(normalize_rel_path(p) for p in self.files))
        object.__setattr__(
            self, "allowed_new_files", tuple(normalize_rel_path(p) for p in self.allowed_new_files)
        )
        object.__setattr__(self, "symbols", tuple(s.strip() for s in self.symbols if s.strip()))
        object.__setattr__(self, "interfaces", tuple(s.strip() for s in self.interfaces if s.strip()))
        object.__setattr__(self, "acceptance", tuple(self.acceptance))
        object.__setattr__(self, "depends_on", tuple(d.strip() for d in self.depends_on if d.strip()))
        object.__setattr__(
            self,
            "setup_commands",
            tuple(c.strip() for c in self.setup_commands if c.strip()),
        )

        status = self.status
        if not isinstance(status, TaskStatus):
            try:
                status = TaskStatus(str(status).lower())
            except ValueError as exc:
                raise TaskError(f"Unknown task status: {self.status!r}") from exc
        object.__setattr__(self, "status", status)

        layer = (self.layer or "").strip().lower()
        if layer and layer not in VALID_LAYERS:
            raise TaskError(f"Unknown architectural layer: {self.layer!r}")
        object.__setattr__(self, "layer", layer)

    @property
    def editable_files(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*self.files, *self.allowed_new_files)))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskSpec":
        if not isinstance(data, dict):
            raise TaskError(f"Invalid task payload: {data!r}")
        raw_acceptance = data.get("acceptance", ()) or ()
        if isinstance(raw_acceptance, str):
            raw_acceptance = (raw_acceptance,)
        return cls(
            id=str(data.get("id", "")),
            title=str(data.get("title", "")),
            goal=str(data.get("goal", "")),
            prompt=str(data.get("prompt", "")),
            files=tuple(data.get("files", ()) or ()),
            allowed_new_files=tuple(data.get("allowed_new_files", ()) or ()),
            symbols=tuple(data.get("symbols", ()) or ()),
            interfaces=tuple(data.get("interfaces", ()) or ()),
            acceptance=tuple(AcceptanceCriterion.from_dict(a) for a in raw_acceptance),
            depends_on=tuple(data.get("depends_on", ()) or ()),
            max_attempts=int(data.get("max_attempts", 2)),
            status=str(data.get("status", "pending")),
            notes=str(data.get("notes", "")),
            layer=str(data.get("layer", "")),
            setup_commands=tuple(data.get("setup_commands", ()) or ()),
            conventions=str(data.get("conventions", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "goal": self.goal,
            "prompt": self.prompt,
            "files": list(self.files),
            "allowed_new_files": list(self.allowed_new_files),
            "symbols": list(self.symbols),
            "interfaces": list(self.interfaces),
            "acceptance": [a.to_dict() for a in self.acceptance],
            "depends_on": list(self.depends_on),
            "max_attempts": self.max_attempts,
            "status": self.status.value,
            "notes": self.notes,
            "layer": self.layer,
            "setup_commands": list(self.setup_commands),
            "conventions": self.conventions,
        }

    def with_status(self, status: TaskStatus) -> "TaskSpec":
        return replace(self, status=status)


@dataclass(frozen=True, slots=True)
class Plan:
    project: str
    tasks: tuple[TaskSpec, ...]
    schema_version: int = 1
    questions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        project = (self.project or "").strip()
        if not project:
            raise TaskError("Plan project name must not be empty.")
        if not self.tasks and not self.questions:
            raise TaskError("Plan must contain at least one task or question.")
        ids = [t.id for t in self.tasks]
        if len(set(ids)) != len(ids):
            raise TaskError("Plan contains duplicate task ids.")
        object.__setattr__(self, "project", project)
        object.__setattr__(self, "tasks", tuple(self.tasks))
        object.__setattr__(self, "questions", tuple(q.strip() for q in self.questions if q.strip()))

    def find_task(self, task_id: str) -> TaskSpec:
        for task in self.tasks:
            if task.id == task_id:
                return task
        raise TaskError(f"Task {task_id!r} not found in plan.")

    def next_pending(self) -> TaskSpec | None:
        for task in self.tasks:
            if task.status == TaskStatus.PENDING:
                return task
        return None

    def with_task_status(self, task_id: str, status: TaskStatus) -> "Plan":
        tasks = tuple(
            task.with_status(status) if task.id == task_id else task for task in self.tasks
        )
        return replace(self, tasks=tasks)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Plan":
        if not isinstance(data, dict):
            raise TaskError(f"Invalid plan payload: {data!r}")
        raw_tasks = data.get("tasks", ()) or ()
        if not isinstance(raw_tasks, (list, tuple)):
            raise TaskError("Plan 'tasks' must be a list.")
        raw_questions = data.get("questions", ()) or ()
        return cls(
            project=str(data.get("project", "")),
            tasks=tuple(TaskSpec.from_dict(t) for t in raw_tasks),
            schema_version=int(data.get("schema_version", 1)),
            questions=tuple(str(q) for q in raw_questions),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project": self.project,
            "tasks": [t.to_dict() for t in self.tasks],
            "questions": list(self.questions),
        }
