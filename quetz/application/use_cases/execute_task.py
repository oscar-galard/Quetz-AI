"""Stateless task executor: one bounded completion per attempt.

No conversation history is carried between attempts or tasks. A retry rebuilds
the prompt from the same :class:`ContextBundle` plus a compact validator error.
"""
from __future__ import annotations

from typing import Callable

from quetz.application.prompts.executor import build_executor_messages
from quetz.application.ports.llm import LLMPort
from quetz.application.ports.validator import ValidationPort
from quetz.domain.context import ContextBundle
from quetz.domain.edit import ExecutionResult, parse_edit_plan
from quetz.domain.exceptions import EditError
from quetz.domain.task_spec import TaskSpec
from quetz.infrastructure.fs.editor import AtomicEditor

Reporter = Callable[[str], None]


def _noop(_text: str) -> None:
    pass


class ExecuteTaskUseCase:
    def __init__(
        self,
        *,
        llm: LLMPort,
        editor: AtomicEditor,
        validator: ValidationPort,
        reporter: Reporter | None = None,
    ) -> None:
        self._llm = llm
        self._editor = editor
        self._validator = validator
        self._report = reporter or _noop

    def execute(self, task: TaskSpec, context: ContextBundle) -> ExecutionResult:
        prior_error = ""
        last_error = ""
        max_attempts = max(1, task.max_attempts)

        for attempt in range(1, max_attempts + 1):
            self._report(
                f"🤖 Executor attempt {attempt}/{max_attempts} for {task.id} "
                f"(~{context.approx_tokens} context tokens)"
            )
            messages = build_executor_messages(context, prior_error)
            try:
                result = self._llm.invoke(messages)
            except Exception as exc:
                last_error = f"LLM invocation failed: {exc}"
                prior_error = last_error
                continue

            try:
                plan = parse_edit_plan(result.content or "", task.id)
            except EditError as exc:
                last_error = f"Invalid edit-plan response: {exc}"
                prior_error = last_error
                self._report(f"  ⚠️  {last_error}")
                continue

            if plan.blocked:
                reason = plan.reason or plan.summary or "Executor could not complete the task."
                return ExecutionResult(
                    task_id=task.id,
                    ok=False,
                    status="blocked",
                    attempts=attempt,
                    summary=plan.summary,
                    error=reason,
                )

            applied = self._editor.apply(plan, task)
            if not applied.ok:
                last_error = applied.error
                prior_error = applied.error
                self._report(f"  ⚠️  Edit rejected: {applied.error}")
                continue

            validation = self._validator.validate(task, list(applied.changed_paths))
            if validation.ok:
                self._report(
                    f"  ✅ Validation passed; changed {len(applied.changed_paths)} file(s)."
                )
                return ExecutionResult(
                    task_id=task.id,
                    ok=True,
                    status="done",
                    attempts=attempt,
                    summary=plan.summary,
                    changed_paths=applied.changed_paths,
                    validation=validation,
                )

            last_error = validation.render()
            prior_error = last_error
            self._editor.revert(applied)
            self._report("  ❌ Validation failed; edits reverted. Retrying with the error.")

        return ExecutionResult(
            task_id=task.id,
            ok=False,
            status="blocked",
            attempts=max_attempts,
            error=last_error or "Executor failed without a diagnostic.",
        )
