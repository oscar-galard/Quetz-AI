"""Read/write the task plan and render a human-readable backlog."""
from __future__ import annotations

import json
from pathlib import Path

from quetz.domain.task_spec import Plan, TaskStatus


def ensure_quetz_dir(workspace: str | Path) -> Path:
    root = Path(workspace)
    quetz_dir = root / ".quetz"
    quetz_dir.mkdir(parents=True, exist_ok=True)
    ignore = quetz_dir / ".gitignore"
    if not ignore.exists():
        ignore.write_text("index.db\n*.tmp\nlogs/\n", encoding="utf-8")
    return quetz_dir


def load_plan(path: str | Path) -> Plan:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    return Plan.from_dict(data)


def save_plan(plan: Plan, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan.to_dict(), indent=2) + "\n", encoding="utf-8")


def render_backlog(plan: Plan) -> str:
    marks = {
        TaskStatus.PENDING: "[ ]",
        TaskStatus.RUNNING: "[~]",
        TaskStatus.DONE: "[x]",
        TaskStatus.BLOCKED: "[!]",
        TaskStatus.FAILED: "[-]",
    }
    lines = [f"# {plan.project} — backlog", ""]
    for task in plan.tasks:
        lines.append(f"- {marks.get(task.status, '[ ]')} **{task.id}** {task.title}")
        lines.append(f"  - goal: {task.goal}")
        if task.files:
            lines.append(f"  - files: {', '.join(task.files)}")
        if task.allowed_new_files:
            lines.append(f"  - new files: {', '.join(task.allowed_new_files)}")
        if task.acceptance:
            lines.append("  - acceptance:")
            for criterion in task.acceptance:
                lines.append(f"    - `{criterion.command}` (exit {criterion.expect_exit})")
        if task.depends_on:
            lines.append(f"  - depends on: {', '.join(task.depends_on)}")
    return "\n".join(lines) + "\n"


def save_backlog(plan: Plan, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_backlog(plan), encoding="utf-8")
