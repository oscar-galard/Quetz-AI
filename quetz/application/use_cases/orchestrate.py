"""Orchestrator: coordinates the full task execution pipeline.

Routes between nodes: Executor → Validator → Debugger → Fixer → Git.
Each node has ONE job. The orchestrator decides what happens next.
"""
from __future__ import annotations

from typing import Callable

from quetz.application.ports.llm import LLMPort
from quetz.application.ports.validator import ValidationPort
from quetz.application.use_cases.debug_task import DebuggerUseCase
from quetz.application.use_cases.execute_task import ExecuteTaskUseCase
from quetz.application.use_cases.fixer import FixerUseCase
from quetz.domain.context import ContextBundle
from quetz.domain.edit import ExecutionResult
from quetz.domain.task_spec import TaskSpec
from quetz.infrastructure.fs.editor import AtomicEditor

Reporter = Callable[[str], None]


def _noop(_text: str) -> None:
    pass


class OrchestrateTaskUseCase:
    """Coordinates Executor → Validator → Debugger → Fixer → Git."""

    def __init__(
        self,
        *,
        executor: ExecuteTaskUseCase,
        debugger: DebuggerUseCase | None = None,
        fixer: FixerUseCase | None = None,
        validator: ValidationPort | None = None,
        editor: AtomicEditor | None = None,
        reporter: Reporter | None = None,
    ) -> None:
        self._executor = executor
        self._debugger = debugger
        self._fixer = fixer
        self._validator = validator
        self._editor = editor
        self._report = reporter or _noop

    def run(self, task: TaskSpec, context: ContextBundle) -> ExecutionResult:
        """Execute task with full error recovery pipeline."""
        # 1. Executor writes code
        result = self._executor.execute(task, context)
        if result.ok:
            return result

        # 2. Code is on disk (not reverted) — analyze with debugger
        if self._debugger is None or self._fixer is None:
            return result

        self._report("🔍 Orchestrator: analyzing failure...")
        hypothesis = self._debugger.analyze(
            changed_paths=list(result.changed_paths or ()),
            workspace=str(self._editor.workspace) if self._editor else "",
            error=result.error,
            task_prompt=task.prompt,
        )

        if hypothesis is None:
            self._report("  ⚠️  No hypothesis — stopping.")
            return result

        # 3. Fixer applies targeted patch
        self._report("🔧 Orchestrator: applying fix...")
        fixed_plan = self._fixer.fix(
            changed_paths=list(result.changed_paths or ()),
            workspace=str(self._editor.workspace) if self._editor else "",
            error=result.error,
            task_prompt=task.prompt,
            hypothesis=hypothesis,
        )

        if fixed_plan is None or fixed_plan.blocked:
            self._report("  ⚠️  Fixer could not fix — code stays on disk.")
            return result

        # 4. Apply fix
        if self._editor is None:
            return result

        fixed_applied = self._editor.apply(fixed_plan, task)
        if not fixed_applied.ok:
            self._report(f"  ⚠️  Fix apply failed: {fixed_applied.error}")
            return result

        # 5. Validate fix
        if self._validator is None:
            return result

        fix_validation = self._validator.validate(
            task, list(fixed_applied.changed_paths), skip_acceptance=False
        )
        if fix_validation.ok:
            self._report("  ✅ Orchestrator: fix succeeded!")
            return ExecutionResult(
                task_id=task.id,
                ok=True,
                status="done",
                attempts=result.attempts,
                summary=fixed_plan.summary or result.summary,
                changed_paths=fixed_applied.changed_paths,
                validation=fix_validation,
            )

        # 6. Fix failed — revert fix, keep executor's code on disk
        self._editor.revert(fixed_applied)
        self._report("  ❌ Fix validation failed — code kept on disk for manual editing.")
        return result
