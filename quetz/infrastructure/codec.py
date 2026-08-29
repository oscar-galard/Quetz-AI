"""Codec translating between neutral :class:`Turn` objects and LangChain messages.

The application layer never sees LangChain types; the graph nodes and the LLM
adapter use this codec at the boundaries.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from quetz.domain.model import ToolCall, Turn

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage


def turn_to_langchain(turn: Turn) -> "BaseMessage":
    """Convert a neutral turn into the matching LangChain message class."""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

    if turn.role == "system":
        return SystemMessage(content=turn.content)
    if turn.role == "user":
        return HumanMessage(content=turn.content)
    if turn.role == "tool":
        return ToolMessage(
            content=turn.content,
            tool_call_id=turn.tool_call_id or "",
            name=turn.name,
        )
    # assistant
    tool_calls = [
        {"name": tc.name, "args": tc.args, "id": tc.id, "type": "tool_call"}
        for tc in turn.tool_calls
    ]
    return AIMessage(content=turn.content, tool_calls=tool_calls)


def langchain_to_turn(message: "BaseMessage") -> Turn:
    """Convert a LangChain message into a neutral turn."""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

    content = message.content if isinstance(message.content, str) else str(message.content)

    if isinstance(message, SystemMessage):
        return Turn.system(content)
    if isinstance(message, HumanMessage):
        return Turn.user(content)
    if isinstance(message, ToolMessage):
        return Turn.tool(
            content=content,
            tool_call_id=getattr(message, "tool_call_id", "") or "",
            name=getattr(message, "name", None),
        )
    if isinstance(message, AIMessage):
        tool_calls = tuple(
            ToolCall(
                name=tc.get("name", ""),
                args=tc.get("args", {}) or {},
                id=tc.get("id", ""),
            )
            for tc in (getattr(message, "tool_calls", None) or [])
        )
        return Turn.assistant(content=content, tool_calls=tool_calls)

    # Unknown type: fall back to an assistant turn carrying the content.
    return Turn.assistant(content=content)


def turns_to_langchain(turns: list[Turn]) -> list["BaseMessage"]:
    return [turn_to_langchain(t) for t in turns]


def langchain_to_turns(messages: list["BaseMessage"]) -> list[Turn]:
    return [langchain_to_turn(m) for m in messages]
