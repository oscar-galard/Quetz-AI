"""Debug report use case: compile research findings into a Markdown/PlantUML report.

The report content is produced centrally, then handed to a :class:`ReportWriter`
port so persistence (filesystem, stdout, S3, ...) is fully decoupled.
"""
from __future__ import annotations

from typing import Callable

from quetz.application.ports.llm import LLMPort
from quetz.application.ports.output import ReportWriter
from quetz.application.use_cases import prompts
from quetz.domain.model import Task, Turn

REPORT_FILENAME = "quetz_report.md"

Reporter = Callable[[str], None]


def _noop(_text: str) -> None:
    pass


class DebugReportUseCase:
    """Generate and persist an architecture & flow report."""

    def __init__(self, llm: LLMPort, writer: ReportWriter, reporter: Reporter | None = None) -> None:
        self._llm = llm
        self._writer = writer
        self._report = reporter or _noop

    def execute(self, task: Task, research: list[Turn]) -> str:
        """Return the generated report text after persisting it."""
        self._report("📝 Generating Architecture & Flow Report...")

        history_text = _summarize_research(research)
        human = Turn.user(
            f"Original User Request: {task.text}\n\n"
            f"Gathered Research Findings:\n{history_text}\n\n"
            "Please generate the complete Markdown report now."
        )
        system = Turn.system(prompts.build_reporter_system_prompt())
        result = self._llm.invoke([system, human])
        content = (result.content or "").strip()

        status = self._writer.write(REPORT_FILENAME, content)
        self._report(status)

        print("\n" + "=" * 80)
        print(content)
        print("=" * 80 + "\n")

        return content


def _summarize_research(research: list[Turn]) -> str:
    """Collapse research turns into a compact text feed (last 15 entries)."""
    entries: list[str] = []
    for turn in research:
        if turn.role == "user":
            entries.append(f"Inquiry: {turn.content}")
        elif turn.content:
            entries.append(f"Content: {turn.content}")
    return "\n\n".join(entries[-15:])
