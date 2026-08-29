"""Reviewer use case: evaluate whether the coder satisfied the plan.

Builds the reviewer prompt from plain strings and an action log, calls the
LLM through the port, and parses the verdict.
"""
from __future__ import annotations

import re

from quetz.application.ports.llm import LLMPort
from quetz.application.use_cases import prompts
from quetz.domain.model import ReviewFeedback, Turn


class ReviewUseCase:
    """Determine approval status and feedback for a coder run."""

    def __init__(self, llm: LLMPort) -> None:
        self._llm = llm

    def execute(self, *, task: str, plan: str, action_log: str, summary: str = "") -> ReviewFeedback:
        """Return structured feedback from the reviewer verdict text."""
        system = Turn.system(prompts.build_reviewer_system_prompt())
        summary_note = (
            f"\n\nCommitted Work Summary (from prior summarization, if any):\n{summary}\n"
            if summary
            else ""
        )
        human = Turn.user(
            f"Original Task: {task}\n\n"
            f"Approved Action Plan:\n{plan}\n\n"
            f"Coder Action Log:\n{action_log}\n"
            f"{summary_note}\n"
            "Review the implementation now."
        )
        result = self._llm.invoke([system, human])
        text = (result.content or "").strip()

        if self._is_approved(text):
            return ReviewFeedback(text=text, approved=True)

        feedback = text
        if "REJECTED:" in text.upper():
            idx = text.upper().find("REJECTED:")
            feedback = text[idx + len("REJECTED:"):].strip()
        return ReviewFeedback(text=feedback, approved=False)

    @staticmethod
    def _is_approved(text: str) -> bool:
        """Robustly detect an approval verdict.

        Small/local models often answer in free-form prose that ends in
        'APPROVED' (e.g. a closing sentence) rather than beginning with it. We
        therefore recognize the word 'APPROVED' anywhere in the response, but
        only as a standalone word so 'NOT APPROVED' is not misunderstood: if the
        text explicitly says 'NOT APPROVED' we treat it as a rejection.
        """
        if not text:
            return False
        upper = text.upper()
        # A verdict word used as an explicit rejection marker wins.
        rejected = bool(re.search(r"\bNOT\s+APPROVED\b", upper))
        # Only treat the line that declares the verdict (not the echoed plan
        # header 'APPROVED ACTION PLAN') as an approval.
        approved = bool(re.search(r"\b(?:VERDICT|STATUS)\s*[:=]?\s*APPROVED\b", upper)) \
            or bool(re.search(r"(?m)^\s*(?:APPROVED|✅ APPROVED)\s*[:.\-]?[ \t]*$", upper)) \
            or upper.startswith("APPROVED")
        if rejected:
            return False
        return approved
