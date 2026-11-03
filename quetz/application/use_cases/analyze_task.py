"""Analyzer use case: produce precise edit instructions for improvements.

The analyzer uses a cloud model to look at existing code and produce targeted
edits (find/replace pairs), not full file rewrites.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from quetz.application.prompts.analyzer import build_analyzer_messages
from quetz.application.ports.llm import LLMPort
from quetz.domain.edit import EditPlan, parse_edit_plan
from quetz.domain.exceptions import EditError

Reporter = Callable[[str], None]


def _noop(_text: str) -> None:
    pass


class AnalyzerUseCase:
    def __init__(
        self,
        *,
        llm: LLMPort,
        reporter: Reporter | None = None,
    ) -> None:
        self._llm = llm
        self._report = reporter or _noop

    def analyze(
        self,
        *,
        changed_paths: list[str],
        workspace: str,
        goal: str,
        conventions: str = "",
    ) -> EditPlan | None:
        """Analyze code and return precise edit instructions."""
        code_files: dict[str, str] = {}
        for path in changed_paths:
            full = Path(workspace) / path
            if full.is_file():
                code_files[path] = full.read_text(encoding="utf-8", errors="replace")

        if not code_files:
            return None

        messages = build_analyzer_messages(code_files, goal, conventions)
        self._report("🔍 Analyzer: producing precise edit instructions...")

        try:
            result = self._llm.invoke(messages)
            plan = parse_edit_plan(result.content or "", "analyze")
            if plan.blocked:
                self._report(f"   ⚠️  Analyzer: {plan.reason}")
                return None
            self._report(f"   📝 Analyzer: {len(plan.edits)} precise edit(s)")
            for edit in plan.edits:
                if edit.op.value == "replace":
                    self._report(f"      {edit.file}: replace {repr(edit.find[:60])}")
                else:
                    self._report(f"      {edit.file}: {edit.op.value}")
            return plan
        except (EditError, Exception) as exc:
            self._report(f"   ⚠️  Analyzer failed: {exc}")
            return None
