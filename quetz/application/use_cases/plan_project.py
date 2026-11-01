"""Cloud-planner use case: turn a natural-language goal into a task plan."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from quetz import config as q_config
from quetz.application.ports.llm import LLMPort
from quetz.application.prompts.planner import build_planner_messages
from quetz.domain.edit import extract_json_object
from quetz.domain.exceptions import PlanError
from quetz.domain.task_spec import Plan
from quetz.infrastructure.fs.paths import read_text, workspace_root
from quetz.infrastructure.fs.tree import build_tree

Reporter = Callable[[str], None]


def _noop(_text: str) -> None:
    pass


class PlanProjectUseCase:
    def __init__(
        self,
        *,
        llm: LLMPort,
        workspace: str,
        reporter: Reporter | None = None,
    ) -> None:
        self._llm = llm
        self._workspace = workspace_root(workspace)
        self._report = reporter or _noop

    def execute(self, goal: str) -> Plan:
        goal = (goal or "").strip()
        if not goal:
            raise PlanError("Planner goal must not be empty.")

        self._report("🧠 Planner is decomposing the goal...")
        tree = build_tree(self._workspace, max_depth=4, max_entries=260)
        conventions = self._conventions()
        memory = self._memory()
        messages = build_planner_messages(
            goal,
            tree=tree,
            conventions=conventions,
            memory=memory,
        )
        result = self._llm.invoke(messages)
        data = extract_json_object(result.content or "")
        if data is None:
            raise PlanError("Planner response did not contain a JSON plan object.")

        try:
            plan = Plan.from_dict(data)
        except Exception as exc:  # TaskError/ValueError from domain validation
            raise PlanError(f"Planner returned an invalid plan: {exc}") from exc

        self._report(f"🗂  Planner produced {len(plan.tasks)} task(s).")
        return plan

    def _conventions(self) -> str:
        blocks: list[str] = []
        for name in ("AGENTS.md", "instructions.md", "specs.md"):
            path = self._workspace / name
            if path.is_file():
                blocks.append(f"### {name}\n{read_text(path, max_chars=8000).strip()}")

        markers = [
            "pyproject.toml",
            "uv.lock",
            "package.json",
            "pnpm-lock.yaml",
            "yarn.lock",
            "package-lock.json",
            "alembic.ini",
            "Makefile",
            "docker-compose.yml",
            "compose.yaml",
        ]
        present = [marker for marker in markers if (self._workspace / marker).exists()]
        if present:
            blocks.append("### Detected tooling\n" + "\n".join(f"- {m}" for m in present))
        return "\n\n".join(blocks)

    def _memory(self) -> str:
        path = self._workspace / q_config.QUETZ_DIR / q_config.MEMORY_FILE
        if not path.is_file():
            return ""
        return read_text(path, max_chars=8000)
