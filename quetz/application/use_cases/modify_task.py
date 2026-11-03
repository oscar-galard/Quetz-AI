"""Modifier use case: apply ChangeSpec changes file-by-file with history.

The modifier is for SMALL modifications to existing code. It groups changes
by file and applies them one file at a time, tracking what succeeded and
what failed. History is per-task — dies when the task ends.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from quetz.application.prompts.modifier import build_modifier_messages
from quetz.application.ports.llm import LLMPort
from quetz.application.ports.validator import ValidationPort
from quetz.domain.change_spec import ChangeSpec, ChangeSpecItem
from quetz.domain.edit import EditPlan, ExecutionResult, parse_edit_plan
from quetz.domain.exceptions import EditError
from quetz.domain.task_spec import TaskSpec
from quetz.infrastructure.fs.editor import AtomicEditor

Reporter = Callable[[str], None]


def _noop(_text: str) -> None:
    pass


@dataclass
class ModifierHistory:
    """Structured per-task history: what was applied, what failed."""

    entries: list[str] = field(default_factory=list)

    def add_success(self, file: str, summary: str) -> None:
        self.entries.append(f"✅ {file}: {summary}")
        if len(self.entries) > 15:
            self.entries = self.entries[-15:]

    def add_failure(self, file: str, error: str) -> None:
        self.entries.append(f"❌ {file}: {error[:120]}")
        if len(self.entries) > 15:
            self.entries = self.entries[-15:]

    def add_skip(self, file: str, reason: str) -> None:
        self.entries.append(f"⏭ {file}: {reason}")
        if len(self.entries) > 15:
            self.entries = self.entries[-15:]

    def render(self) -> str:
        if not self.entries:
            return ""
        return "\n".join(self.entries)  # already bounded to last 15

    @property
    def applied_count(self) -> int:
        return sum(1 for e in self.entries if e.startswith("✅"))

    @property
    def failed_count(self) -> int:
        return sum(1 for e in self.entries if e.startswith("❌"))


class ModifierUseCase:
    """Applies small modifications to existing code with per-task history."""

    def __init__(
        self,
        *,
        llm: LLMPort,
        editor: AtomicEditor,
        validator: ValidationPort | None = None,
        reporter: Reporter | None = None,
    ) -> None:
        self._llm = llm
        self._editor = editor
        self._validator = validator
        self._report = reporter or _noop

    def apply_spec(
        self,
        task: TaskSpec,
        spec: ChangeSpec,
        *,
        conventions: str = "",
        skills: str = "",
    ) -> ExecutionResult:
        """Apply all changes in the spec, grouped by file."""
        history = ModifierHistory()

        # Group changes by file
        by_file: dict[str, list[ChangeSpecItem]] = {}
        for change in spec.changes:
            by_file.setdefault(change.file, []).append(change)

        all_changed: set[str] = set()

        for file_path, changes in by_file.items():
            self._report(f"📝 Modifier: {file_path} ({len(changes)} change(s))")

            # Read current file state
            full = Path(self._editor.workspace) / file_path
            if not full.is_file():
                history.add_skip(file_path, "file not found")
                continue

            for i, change in enumerate(changes):
                content = full.read_text(encoding="utf-8", errors="replace")
                messages = build_modifier_messages(
                    change_instruction=change.instruction,
                    locate_hint=change.locate,
                    file_path=file_path,
                    file_content=content,
                    progress=history.render(),
                    conventions=conventions,
                    skills=skills,
                )

                try:
                    result = self._llm.invoke(messages)
                    plan = parse_edit_plan(result.content or "", task.id)
                except (EditError, Exception) as exc:
                    history.add_failure(file_path, f"parse error: {exc}")
                    continue

                if plan.blocked:
                    history.add_failure(file_path, plan.reason or "blocked")
                    continue

                # Apply the edit
                applied = self._editor.apply(plan, task)
                if not applied.ok:
                    history.add_failure(file_path, applied.error)
                    continue

                all_changed.update(applied.changed_paths)

                # Quick syntax check (skip full acceptance for speed)
                if self._validator is not None:
                    from quetz.domain.edit import ValidationResult
                    validation = self._validator.validate(
                        task, list(applied.changed_paths), skip_acceptance=True
                    )
                    if not validation.ok:
                        self._editor.revert(applied)
                        history.add_failure(file_path, f"validation: {validation.summary[:100]}")
                        continue

                summary = plan.summary or f"change {i+1}/{len(changes)}"
                history.add_success(file_path, summary)
                self._report(f"   ✅ {summary}")

        # Final result
        applied = history.applied_count
        failed = history.failed_count
        self._report(f"📊 Modifier: {applied} applied, {failed} failed")

        return ExecutionResult(
            task_id=task.id,
            ok=applied > 0 and failed == 0,
            status="done" if applied > 0 and failed == 0 else "blocked",
            attempts=1,
            summary=spec.summary or f"{applied} changes applied",
            changed_paths=tuple(sorted(all_changed)),
            error="" if failed == 0 else f"{failed} change(s) failed",
        )
