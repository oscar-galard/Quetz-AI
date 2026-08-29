"""Debug research use case: recursively locate files/symbols relevant to a query.

Mirrors the planner's research loop but is purpose-built for the debug/report
workflow, with a higher step budget.
"""
from __future__ import annotations

from typing import Callable

from quetz.application.ports.llm import ToolBinder, ToolSpec
from quetz.application.ports.tool_executor import ToolExecutorPort
from quetz.application.use_cases import prompts
from quetz.domain.model import Task, ToolCall, Turn

MAX_RESEARCH_STEPS = 10
Reporter = Callable[[str], None]


def _noop(_text: str) -> None:
    pass


class DebugResearchUseCase:
    """Gather research findings about the target system."""

    def __init__(
        self,
        llm_binder: ToolBinder,
        tool_executor: ToolExecutorPort,
        tool_specs: list[ToolSpec],
        reporter: Reporter | None = None,
    ) -> None:
        self._binder = llm_binder
        self._tools = tool_executor
        self._tool_specs = tool_specs
        self._report = reporter or _noop

    def execute(
        self,
        task: Task,
        workspace: str,
        existing_files: list[str],
    ) -> list[Turn]:
        """Return the full research conversation (system + task + turns)."""
        self._report("🔍 Debug Researching Workspace...")

        messages: list[Turn] = [
            Turn.system(prompts.build_debug_research_prompt(workspace, existing_files)),
            Turn.user(task.text),
        ]
        research_llm = self._binder.bind_tools(self._tool_specs)

        research_steps = 0
        while research_steps < MAX_RESEARCH_STEPS:
            result = research_llm.invoke(messages)
            assistant = result.message
            if assistant is not None:
                messages.append(assistant)
            if not result.tool_calls:
                break
            research_steps += 1
            for item in result.tool_calls:
                call = ToolCall(
                    name=item.get("name", ""),
                    args=item.get("args", {}) or {},
                    id=item.get("id", "") or "",
                )
                self._report(f"  🔍 Debug Research: Calling tool {call.name}({call.args})...")
                outcome = self._tools.execute(call)
                messages.append(Turn.tool(outcome.content, outcome.tool_call_id, outcome.name))

        return messages
