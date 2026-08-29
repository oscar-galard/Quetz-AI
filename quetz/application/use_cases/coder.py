"""Coder use case: stream an LLM completion that may invoke workspace tools.

Pure orchestration over ports. Streaming output is forwarded to sink callbacks
(mirroring the original terminal UX) while the adapter handles the actual
streaming. Tool calls emitted by the model are carried back on the produced
assistant turn; the graph's tools node executes them.
"""
from __future__ import annotations

from typing import Callable

from quetz.application.ports.llm import LLMPort, ToolBinder, ToolSpec
from quetz.application.use_cases import prompts
from quetz.domain.model import Turn, parse_tool_call_from_text

ContentSink = Callable[[str], None]


class CodeUseCase:
    """Produce the next assistant turn for a given coder step."""

    def __init__(self, llm_binder: ToolBinder, tool_specs: list[ToolSpec]) -> None:
        self._binder = llm_binder
        self._tool_specs = tool_specs

    def execute(
        self,
        *,
        workspace: str,
        plan: str,
        review_feedback: str,
        summary: str,
        history: list[Turn],
        on_content: ContentSink,
        max_iterations: int,
        iteration: int,
    ) -> list[Turn]:
        """Stream a completion and return the new turns to append to state.

        Raises nothing; returns an assistant turn (with possible tool calls)
        even when the model only emits text.
        """
        sys_prompt = prompts.build_system_prompt(workspace, plan, review_feedback)
        messages: list[Turn] = [Turn.system(sys_prompt)]
        if summary:
            messages.append(Turn.system(f"Recent Activity Summary:\n{summary}"))
        messages.extend(history)

        bound: LLMPort = self._binder.bind_tools(self._tool_specs)

        streamed_tool = {"flag": False}
        on_tool_name = None
        on_tool_args = None
        if on_content is not None:

            def _on_tool_name(name: str) -> None:
                streamed_tool["flag"] = True
                on_content(f"\n  ⚙️  Calling tool: {name}(")

            def _on_tool_args(args: str) -> None:
                on_content(args)

            on_tool_name = _on_tool_name
            on_tool_args = _on_tool_args

        result = bound.stream(
            messages,
            on_content=on_content,
            on_tool_name=on_tool_name,
            on_tool_args=on_tool_args,
        )
        if streamed_tool["flag"] and on_content is not None:
            on_content(")")
        if on_content is not None:
            on_content("\n")

        assistant = result.message or Turn.assistant(content=result.content)

        if not assistant.tool_calls and assistant.content:
            fallback = parse_tool_call_from_text(assistant.content)
            if fallback:
                first = fallback[0]
                from quetz.domain.model import ToolCall

                assistant = Turn.assistant(
                    content=assistant.content,
                    tool_calls=(ToolCall(
                        name=first["name"],
                        args=first["args"] or {},
                        id=first.get("id") or "",
                    ),),
                )
                if on_content is not None:
                    on_content(f"\n🔄 Detected tool. Normalizing to native format: {first['name']}")

        return [assistant]
