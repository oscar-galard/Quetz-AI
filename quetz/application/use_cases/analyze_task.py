"""Analyzer use case: produce ChangeSpec (what to improve, not how).

The analyzer uses a cloud model to look at existing code and produce
targeted change instructions. The executor turns those into actual edits.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from quetz.application.prompts.analyzer import build_analyzer_messages
from quetz.application.ports.llm import LLMPort
from quetz.domain.change_spec import ChangeSpec, parse_change_spec
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
        skills: str = "",
    ) -> ChangeSpec | None:
        """Analyze code and return a ChangeSpec."""
        code_files: dict[str, str] = {}
        for path in changed_paths:
            full = Path(workspace) / path
            if full.is_file():
                code_files[path] = full.read_text(encoding="utf-8", errors="replace")

        if not code_files:
            return None

        messages = build_analyzer_messages(code_files, goal, conventions, skills)
        self._report("🔍 Analyzer: producing change spec...")

        try:
            result = self._llm.invoke(messages)
            spec = parse_change_spec(result.content or "")
            self._report(f"   📝 Analyzer: {len(spec.changes)} change(s)")
            for c in spec.changes:
                if c.action == "replace":
                    self._report(f"      {c.file}: replace — {c.locate or c.instruction[:60]}")
                else:
                    self._report(f"      {c.file}: {c.action} — {c.instruction[:60]}")
            return spec
        except (EditError, Exception) as exc:
            self._report(f"   ⚠️  Analyzer failed: {exc}")
            return None
