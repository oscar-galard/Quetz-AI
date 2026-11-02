"""Debugger use case: analyze errors before fixing.

The debugger uses a cloud model to understand the root cause of a failure,
then passes the hypothesis to the fixer for a targeted fix.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from quetz.application.prompts.debugger import build_debugger_messages
from quetz.application.ports.llm import LLMPort

Reporter = Callable[[str], None]


def _noop(_text: str) -> None:
    pass


@dataclass(frozen=True, slots=True)
class DebugHypothesis:
    root_cause: str
    fix_strategy: str
    files_to_fix: tuple[str, ...] = ()
    change_type: str = "replace"
    confidence: str = "medium"

    @property
    def summary(self) -> str:
        return f"{self.root_cause} → {self.fix_strategy}"


class DebuggerUseCase:
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
        error: str,
        task_prompt: str = "",
    ) -> DebugHypothesis | None:
        """Analyze the error and return a hypothesis, or None if analysis fails."""
        code_files: dict[str, str] = {}
        for path in changed_paths:
            full = Path(workspace) / path
            if full.is_file():
                code_files[path] = full.read_text(encoding="utf-8", errors="replace")

        if not code_files:
            return None

        messages = build_debugger_messages(code_files, error, task_prompt)
        self._report("🔍 Debugger: analyzing root cause...")

        try:
            result = self._llm.invoke(messages)
            data = json.loads(result.content or "{}")
            hypothesis = DebugHypothesis(
                root_cause=data.get("root_cause", "unknown"),
                fix_strategy=data.get("fix_strategy", "unknown"),
                files_to_fix=tuple(data.get("files_to_fix", [])),
                change_type=data.get("change_type", "replace"),
                confidence=data.get("confidence", "medium"),
            )
            self._report(f"   💡 Root cause: {hypothesis.root_cause}")
            self._report(f"   🔧 Strategy: {hypothesis.fix_strategy}")
            self._report(f"   📊 Confidence: {hypothesis.confidence}")
            return hypothesis
        except Exception as exc:
            self._report(f"   ⚠️  Debugger failed: {exc}")
            return None
