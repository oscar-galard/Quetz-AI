"""LangChain LLM adapter implementing the application's LLM port.

This adapter is the single place that talks to LangChain chat models. It
translates neutral turns to/from LangChain messages, and supports both
non-streamed and streamed completions with streaming sinks for terminal UX.
"""
from __future__ import annotations

from typing import Any, Callable

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from quetz.application.ports.llm import LLMPort, LLMResult, ToolBinder, ToolSpec
from quetz.infrastructure.codec import turn_to_langchain
from quetz.domain.model import ToolCall, Turn

ContentSink = Callable[[str], None]
ToolNameSink = Callable[[str], None]
ToolArgSink = Callable[[str], None]


class LangChainLLMAdapter(LLMPort, ToolBinder):
    """Adapts a LangChain ``BaseChatModel`` to the neutral LLM port."""

    def __init__(self, model: BaseChatModel, config: RunnableConfig | None = None) -> None:
        self._model = model
        self._config = config or {}

    def bind_tools(self, tools: list[ToolSpec]) -> LLMPort:
        specs: list[dict[str, Any]] = [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.schema,
            }
            for t in tools
        ]
        if specs:
            bound = self._model.bind_tools(specs) if hasattr(self._model, "bind_tools") else self._model
        else:
            bound = self._model
        return LangChainLLMAdapter(bound, config=self._config)

    def invoke(self, messages: list[Turn]) -> LLMResult:
        lc_messages = [turn_to_langchain(m) for m in messages]
        response = self._model.invoke(lc_messages, config=self._config)
        return _to_result(response)

    def stream(
        self,
        messages: list[Turn],
        *,
        on_content: ContentSink | None = None,
        on_tool_name: ToolNameSink | None = None,
        on_tool_args: ToolArgSink | None = None,
    ) -> LLMResult:
        lc_messages = [turn_to_langchain(m) for m in messages]
        response: AIMessage | None = None
        for chunk in self._model.stream(lc_messages, config=self._config):
            if chunk.content and on_content is not None:
                on_content(chunk.content)
            if chunk.tool_call_chunks and (on_tool_name is not None or on_tool_args is not None):
                for tc_chunk in chunk.tool_call_chunks:
                    if tc_chunk.get("name") and on_tool_name is not None:
                        on_tool_name(tc_chunk["name"])
                    if tc_chunk.get("args") and on_tool_args is not None:
                        on_tool_args(tc_chunk["args"])
            response = chunk if response is None else response + chunk
        if response is None:
            response = AIMessage(content="")
        return _to_result(response)


def _to_result(message: AIMessage) -> LLMResult:
    content = message.content if isinstance(message.content, str) else str(message.content)
    tool_calls = tuple(
        ToolCall(
            name=tc.get("name", ""),
            args=tc.get("args", {}) or {},
            id=tc.get("id", ""),
        )
        for tc in (getattr(message, "tool_calls", None) or [])
    )
    return LLMResult(
        content=content,
        message=Turn.assistant(content=content, tool_calls=tool_calls),
    )
