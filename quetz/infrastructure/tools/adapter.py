"""LangChain-backed tool executor implementing the ToolExecutorPort.

Wraps the existing ``@tool``-decorated functions from :mod:`quetz.tools` and
executes calls against their ``invoke`` method, returning neutral results.
Interactive write/edit confirmation is handled at the graph node boundary, not
here, so this executor remains a pure adapter.
"""
from __future__ import annotations

from quetz.application.ports.tool_executor import ToolExecutorPort, ToolResult
from quetz.domain.model import ToolCall
from quetz.tools import read_tool_map, tool_map


class LangChainToolExecutor(ToolExecutorPort):
    """Executes tool calls using the concrete langchain tool implementations."""

    def is_known_tool(self, name: str) -> bool:
        return name in tool_map or name in read_tool_map

    def execute(self, call: ToolCall) -> ToolResult:
        tool = tool_map.get(call.name) or read_tool_map.get(call.name)
        if tool is None:
            return ToolResult(
                content=f"Error: Tool {call.name} not found.",
                tool_call_id=call.id,
                name=call.name,
            )
        try:
            content = tool.invoke(call.args)
        except Exception as e:  # noqa: BLE001 - surface as a tool result
            content = f"Error executing {call.name}: {e}"
        return ToolResult(
            content=str(content),
            tool_call_id=call.id,
            name=call.name,
        )
