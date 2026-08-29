"""Reviewer use case: evaluate whether the coder satisfied the plan.

Builds the reviewer prompt from plain strings and an action log, calls the
LLM through the port, and parses the verdict.
"""
from __future__ import annotations

from quetz.application.ports.llm import LLMPort
from quetz.application.use_cases import prompts
from quetz.domain.model import ReviewFeedback, Turn


class ReviewUseCase:
    """Determine approval status and feedback for a coder run."""

    def __init__(self, llm: LLMPort) -> None:
        self._llm = llm

    def execute(self, *, task: str, plan: str, action_log: str) -> ReviewFeedback:
        """Return structured feedback from the reviewer verdict text."""
        system = Turn.system(prompts.build_reviewer_system_prompt())
        human = Turn.user(
            f"Original Task: {task}\n\n"
            f"Approved Action Plan:\n{plan}\n\n"
            f"Coder Action Log:\n{action_log}\n\n"
            "Review the implementation now."
        )
        result = self._llm.invoke([system, human])
        text = (result.content or "").strip()

        first_word = text.split()[0].upper().strip(":,.-") if text.split() else ""
        if first_word == "APPROVED":
            return ReviewFeedback(text=text, approved=True)

        feedback = text
        if "REJECTED:" in text.upper():
            idx = text.upper().find("REJECTED:")
            feedback = text[idx + len("REJECTED:"):].strip()
        return ReviewFeedback(text=feedback, approved=False)
