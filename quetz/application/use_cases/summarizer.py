"""Summarizer use case: condense recent activity into a short working summary."""
from __future__ import annotations

from quetz.application.ports.llm import LLMPort
from quetz.application.use_cases import prompts
from quetz.domain.model import Turn


class SummarizeUseCase:
    """Produce a concise summary of recent coding activity."""

    def __init__(self, llm: LLMPort) -> None:
        self._llm = llm

    def execute(self, history: list[Turn]) -> str:
        system = Turn.system(prompts.build_summary_prompt())
        recent = history[-6:]
        result = self._llm.invoke([system, *recent])
        return result.content or ""
