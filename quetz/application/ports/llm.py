"""LLM port: the contract the application uses to talk to any language model.

The port operates on framework-neutral :class:`Turn` objects and returns a
framework-neutral :class:`LLMResult`. Concrete adapters (Ollama, OpenAI, ...)
translate to and from their native SDK. Tracing/observability is applied by
wrapper adapters in the infrastructure layer, so the application never knows
about LangSmith or similar.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable

from quetz.domain.model import Turn


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Metadata describing a tool made available to the model."""

    name: str
    description: str
    schema: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LLMResult:
    """A single model completion in neutral form."""

    content: str
    message: Turn | None = None

    @property
    def tool_calls(self) -> list[dict]:
        if self.message and self.message.tool_calls:
            return [
                {"name": tc.name, "args": tc.args, "id": tc.id, "type": "tool_call"}
                for tc in self.message.tool_calls
            ]
        return []


#: Callback receiving streamed text chunks.
ContentSink = Callable[[str], None]
#: Callback receiving the name of a tool being called during streaming.
ToolNameSink = Callable[[str], None]
#: Callback receiving raw argument JSON fragments during streaming.
ToolArgSink = Callable[[str], None]


@runtime_checkable
class LLMPort(Protocol):
    """Bound/unbound chat model capable of invoke and stream completions."""

    def invoke(self, messages: list[Turn]) -> LLMResult:
        """Run a single non-streamed completion over the given turns."""
        ...

    def stream(
        self,
        messages: list[Turn],
        *,
        on_content: ContentSink | None = None,
        on_tool_name: ToolNameSink | None = None,
        on_tool_args: ToolArgSink | None = None,
    ) -> LLMResult:
        """Stream a completion, forwarding chunks to the provided sinks."""
        ...


@runtime_checkable
class ToolBinder(Protocol):
    """Adapters that can expose a tool-bound variant of the LLM."""

    def bind_tools(self, tools: list[ToolSpec]) -> LLMPort:
        """Return an LLMPort bound so it may invoke the given tools."""
        ...
