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
        code_summary = self._code_summary()
        messages = build_planner_messages(
            goal,
            tree=tree,
            conventions=conventions,
            memory=memory,
            code_summary=code_summary,
        )

        # Stream the response so user can see which model is running
        chunks: list[str] = []

        def _on_content(text: str) -> None:
            chunks.append(text)
            print(text, end="", flush=True)

        try:
            result = self._llm.stream(messages, on_content=_on_content)
        except Exception:
            # Fallback to invoke if stream fails
            result = self._llm.invoke(messages)
            chunks.append(result.content or "")

        print()  # newline after streaming

        raw = "".join(chunks) if chunks else (result.content or "")
        data = extract_json_object(raw)
        if data is None:
            raise PlanError("Planner response did not contain a JSON plan object.")

        # Fix empty project name
        if not data.get("project", "").strip():
            data["project"] = self._workspace.name or "project"

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

    def _code_summary(self) -> str:
        """Read source files and show class/function signatures (the old read_file)."""
        import ast
        from quetz.infrastructure.fs.paths import iter_workspace_files

        lines: list[str] = []
        for rel_path in iter_workspace_files(self._workspace):
            full = self._workspace / rel_path
            try:
                text = full.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            if rel_path.endswith(".py"):
                try:
                    tree = ast.parse(text)
                except SyntaxError:
                    continue
                exports = []
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        bases = [ast.unparse(b) for b in node.bases] if node.bases else []
                        base_str = f"({', '.join(bases)})" if bases else ""
                        exports.append(f"class {node.name}{base_str}")
                    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if node.col_offset == 0:  # top-level only
                            exports.append(f"def {node.name}()")
                if exports:
                    lines.append(f"{rel_path}:")
                    for e in exports[:15]:
                        lines.append(f"  {e}")
            elif rel_path.endswith((".ts", ".tsx")):
                import re
                classes = re.findall(r"(?:export\s+)?(?:class|interface|type)\s+(\w+)", text)
                funcs = re.findall(r"(?:export\s+)?(?:async\s+)?function\s+(\w+)", text)
                hooks = re.findall(r"(?:export\s+)?function\s+(use\w+)", text)
                exports = [f"class {c}" for c in classes[:5]] + \
                         [f"function {f}" for f in funcs[:5]] + \
                         [f"hook {h}" for h in hooks[:3]]
                if exports:
                    lines.append(f"{rel_path}:")
                    for e in exports[:10]:
                        lines.append(f"  {e}")

        return "\n".join(lines) if lines else "(no source files found)"
