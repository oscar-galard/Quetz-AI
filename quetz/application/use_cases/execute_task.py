"""Stateless task executor: one bounded completion per attempt.

No conversation history is carried between attempts or tasks. A retry rebuilds
the prompt from the same :class:`ContextBundle` plus a compact validator error.
"""
from __future__ import annotations

import re
from typing import Callable

from quetz import config as q_config
from quetz.application.prompts.executor import build_executor_messages
from quetz.application.ports.llm import LLMPort
from quetz.application.ports.validator import ValidationPort
from quetz.application.use_cases.debug_task import DebuggerUseCase
from quetz.application.use_cases.fixer import FixerUseCase
from quetz.domain.context import ContextBundle
from quetz.domain.edit import ExecutionResult, parse_edit_plan
from quetz.domain.exceptions import EditError
from quetz.domain.task_spec import TaskSpec
from quetz.infrastructure.fs.editor import AtomicEditor

Reporter = Callable[[str], None]

# Patterns that indicate a degenerate/invalid LLM response (local models)
_INVALID_PATTERNS = [
    re.compile(r"^\s*$", re.DOTALL),  # empty
    re.compile(r'^\s*["\u201c\u201d]\s*$'),  # just a quote
    re.compile(r"^\s*A\s*:", re.IGNORECASE),  # "A: ..." answer format
    re.compile(r"^\s*Answer\s*:", re.IGNORECASE),
    re.compile(r"^\s*Q\s*:", re.IGNORECASE),  # "Q: ..." question format
    re.compile(r"^\s*Sure[,!]", re.IGNORECASE),  # "Sure, here's..."
    re.compile(r"^\s*I\s+(can't|cannot|am\s+unable)", re.IGNORECASE),
    re.compile(r"^\s*Sorry", re.IGNORECASE),
    re.compile(r"^\s*As\s+an\s+AI", re.IGNORECASE),
]


def _is_invalid_response(text: str) -> bool:
    """Detect degenerate LLM output that should be retried without penalty."""
    if not text or not text.strip():
        return True
    stripped = text.strip()
    for pattern in _INVALID_PATTERNS:
        if pattern.match(stripped):
            return True
    # If it contains no JSON object at all, it's invalid
    if "{" not in stripped:
        return True
    return False


def _noop(_text: str) -> None:
    pass


class ExecuteTaskUseCase:
    def __init__(
        self,
        *,
        llm: LLMPort,
        editor: AtomicEditor,
        validator: ValidationPort,
        fixer: FixerUseCase | None = None,
        debugger: DebuggerUseCase | None = None,
        reporter: Reporter | None = None,
        skip_acceptance: bool = False,
    ) -> None:
        self._llm = llm
        self._editor = editor
        self._validator = validator
        self._fixer = fixer
        self._debugger = debugger
        self._report = reporter or _noop
        self._skip_acceptance = skip_acceptance

    def execute(self, task: TaskSpec, context: ContextBundle) -> ExecutionResult:
        prior_error = ""
        last_error = ""
        max_attempts = max(q_config.DEFAULT_MAX_ATTEMPTS, task.max_attempts)
        degenerate_count = 0  # invalid responses don't count toward limit

        for attempt in range(1, max_attempts + 1):
            self._report(
                f"🦜 Executor attempt {attempt}/{max_attempts} for {task.id} "
                f"(~{context.approx_tokens} context tokens)"
            )
            messages = build_executor_messages(context, prior_error)
            try:
                result = self._llm.invoke(messages)
            except Exception as exc:
                last_error = f"LLM invocation failed: {exc}"
                prior_error = last_error
                continue

            content = result.content or ""

            # Intercept degenerate responses (empty, "A: ...", no JSON, etc.)
            if _is_invalid_response(content):
                degenerate_count += 1
                self._report(
                    f"  ⚠️  Degenerate response #{degenerate_count} "
                    f"({len(content.strip())} chars) — retrying without penalty..."
                )
                prior_error = "Your last response was empty or not valid JSON. Return ONLY the edit-plan JSON."
                continue

            try:
                plan = parse_edit_plan(content, task.id)
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

            validation = self._validator.validate(
                task, list(applied.changed_paths), skip_acceptance=self._skip_acceptance
            )
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

            # Show verbose validation error — code STAYS on disk for manual editing
            self._report(f"  ❌ Validation failed: {last_error[:200]}")
            self._report(f"     (debugger: {'on' if self._debugger else 'off'}, fixer: {'on' if self._fixer else 'off'})")
            self._report("     Code kept on disk — you can fix manually or let the fixer try.")

            # Debugger analyzes root cause, then Fixer applies targeted fix
            hypothesis = None
            if self._debugger is not None:
                try:
                    hypothesis = self._debugger.analyze(
                        changed_paths=list(applied.changed_paths),
                        workspace=str(self._editor.workspace),
                        error=last_error,
                        task_prompt=task.prompt,
                    )
                except Exception as exc:
                    self._report(f"  ⚠️  Debugger crashed: {exc}")

            if self._fixer is not None:
                try:
                    fixed_plan = self._fixer.fix(
                        changed_paths=list(applied.changed_paths),
                        workspace=str(self._editor.workspace),
                        error=last_error,
                        task_prompt=task.prompt,
                        hypothesis=hypothesis,
                    )
                    if fixed_plan and not fixed_plan.blocked:
                        fixed_applied = self._editor.apply(fixed_plan, task)
                        if fixed_applied.ok:
                            self._report("  🔧 Fixer patch:")
                            for edit in fixed_plan.edits:
                                if edit.op.value == "replace" and edit.find:
                                    self._report(f"    📝 {edit.file}")
                                    self._report(f"    - {edit.find.strip()[:120]}")
                                    self._report(f"    + {edit.replace.strip()[:120]}")
                                else:
                                    self._report(f"    🆕 {edit.file}")

                            fix_validation = self._validator.validate(
                                task, list(fixed_applied.changed_paths),
                                skip_acceptance=self._skip_acceptance,
                            )
                            if fix_validation.ok:
                                self._report(
                                    f"  ✅ Fixer succeeded; changed "
                                    f"{len(fixed_applied.changed_paths)} file(s)."
                                )
                                return ExecutionResult(
                                    task_id=task.id,
                                    ok=True,
                                    status="done",
                                    attempts=attempt,
                                    summary=fixed_plan.summary or plan.summary,
                                    changed_paths=fixed_applied.changed_paths,
                                    validation=fix_validation,
                                )
                            self._editor.revert(fixed_applied)
                except Exception as exc:
                    self._report(f"  ⚠️  Fixer crashed: {exc}")

            self._report("  ❌ Validation failed. Retrying with the error. Code kept on disk.")

        return ExecutionResult(
            task_id=task.id,
            ok=False,
            status="blocked",
            attempts=max_attempts,
            error=last_error or "Executor failed without a diagnostic.",
        )
