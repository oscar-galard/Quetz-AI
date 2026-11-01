"""Framework-neutral message value objects used by the LLM port and codec."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A framework-neutral tool invocation requested by a model."""

    name: str
    args: dict[str, Any]
    id: str


@dataclass(frozen=True, slots=True)
class Turn:
    """A framework-neutral conversational message.

    ``role`` is one of ``system``, ``user``, ``assistant``, or ``tool``.
    Assistant turns may carry ``tool_calls``; tool turns carry ``tool_call_id``
    and ``name``.
    """

    role: str
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    name: str | None = None

    @classmethod
    def system(cls, content: str) -> "Turn":
        return cls(role="system", content=content)

    @classmethod
    def user(cls, content: str) -> "Turn":
        return cls(role="user", content=content)

    @classmethod
    def assistant(cls, content: str = "", tool_calls: tuple[ToolCall, ...] = ()) -> "Turn":
        return cls(role="assistant", content=content, tool_calls=tool_calls)

    @classmethod
    def tool(cls, content: str, tool_call_id: str, name: str) -> "Turn":
        return cls(role="tool", content=content, tool_call_id=tool_call_id, name=name)

    @property
    def is_tool_call(self) -> bool:
        return self.role == "assistant" and bool(self.tool_calls)
