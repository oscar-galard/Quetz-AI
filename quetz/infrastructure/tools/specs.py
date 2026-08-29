"""Build neutral :class:`ToolSpec` metadata from the concrete langchain tools.

Keeps the list of available tools (and the read-only subset) defined in one
place so both the planner/debug research and the coder use the same surface.
"""
from __future__ import annotations

from typing import Any

from quetz.application.ports.llm import ToolSpec
from quetz.tools import tools as ALL_TOOLS
from quetz.tools import read_only_tools as ALL_READ_ONLY_TOOLS


def _args_schema_dict(tool) -> dict[str, Any]:
    args_schema = getattr(tool, "args_schema", None)
    if args_schema is not None:
        try:
            schema = args_schema.model_json_schema()
            if isinstance(schema, dict):
                return schema
        except Exception:
            pass
    # Fall back to the coarse args dict if no pydantic schema is available.
    args = getattr(tool, "args", None)
    return args if isinstance(args, dict) else {}


def _to_spec(tool) -> ToolSpec:
    return ToolSpec(
        name=getattr(tool, "name", "") or tool.__name__,
        description=getattr(tool, "description", "") or "",
        schema=_args_schema_dict(tool),
    )


ALL_TOOL_SPECS: list[ToolSpec] = [_to_spec(t) for t in ALL_TOOLS]
READ_ONLY_TOOL_SPECS: list[ToolSpec] = [_to_spec(t) for t in ALL_READ_ONLY_TOOLS]
