"""Tool executor ports: how the application runs filesystem / workspace tools.

The application declares the tool surface via :class:`ToolSpec` and executes
calls through a :class:`ToolExecutorPort`. Adapters in infrastructure back
these with concrete implementations (langchain tools, subprocess, etc.).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from quetz.domain.model import ToolCall


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Outcome of executing a single tool call (neutral form)."""

    content: str
    tool_call_id: str
    name: str


@runtime_checkable
class ToolExecutorPort(Protocol):
    """Executes a tool call and returns its result."""

    def execute(self, call: ToolCall) -> ToolResult:
        """Run ``call`` and return a neutral result."""
        ...

    def is_known_tool(self, name: str) -> bool:
        """Return True if a tool with ``name`` is available for execution."""
        ...
