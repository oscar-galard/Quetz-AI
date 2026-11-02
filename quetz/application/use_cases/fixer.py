"""Fixer use case: patch validation errors without full regeneration.

The fixer gets the failing code + the error and produces a minimal fix.
It uses a separate LLM (typically the local model) to keep costs low.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from quetz.application.prompts.fixer import build_fixer_messages
from quetz.application.ports.llm import LLMPort
from quetz.domain.edit import EditPlan, parse_edit_plan
from quetz.domain.exceptions import EditError

Reporter = Callable[[str], None]


def _noop(_text: str) -> None:
    pass


class FixerUseCase:
    def __init__(
        self,
        *,
        llm: LLMPort,
        reporter: Reporter | None = None,
    ) -> None:
        self._llm = llm
        self._report = reporter or _noop

    def fix(
        self,
        *,
        changed_paths: list[str],
        workspace: str,
        error: str,
        task_prompt: str = "",
    ) -> EditPlan | None:
        """Try to fix the error. Returns a corrected EditPlan or None."""
        # Read the current (reverted) code
        code_files: dict[str, str] = {}
        for path in changed_paths:
            full = Path(workspace) / path
            if full.is_file():
                code_files[path] = full.read_text(encoding="utf-8", errors="replace")

        if not code_files:
            return None

        messages = build_fixer_messages(code_files, error, task_prompt)
        self._report(f"🔧 Fixer: analyzing {len(code_files)} file(s) for bug...")

        try:
            result = self._llm.invoke(messages)
            plan = parse_edit_plan(result.content or "", "fix")
            if plan.blocked:
                self._report(f"   ❌ Fixer: {plan.reason}")
                return None
            self._report(f"   ✅ Fixer: {len(plan.edits)} edit(s) proposed")
            return plan
        except (EditError, Exception) as exc:
            self._report(f"   ⚠️  Fixer failed: {exc}")
            return None
