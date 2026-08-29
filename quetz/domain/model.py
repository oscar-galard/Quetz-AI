"""Value objects for the agent domain.

Contains the immutable value objects representing the user's request and the
approved plan. These are framework-agnostic and unit-testable in isolation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from quetz.domain.exceptions import PlanError, TaskError

#: Minimum number of non-whitespace characters a plan must contain to be valid.
MIN_PLAN_CHARS = 30

#: Context files that are automatically loaded into the planning prompt.
CONTEXT_FILES = ("specs.md", "skills.md", "agents.md", "instructions.md")


@dataclass(frozen=True, slots=True)
class Task:
    """The user's request, normalized for the agent workflow.

    ``text`` is the original free-form instruction.
    """

    text: str

    def __post_init__(self) -> None:
        if not self.text or not self.text.strip():
            raise TaskError("Task text must not be empty.")
        # Ensure text is immutable-friendly and trimmed.
        object.__setattr__(self, "text", self.text.strip())


@dataclass(frozen=True, slots=True)
class Plan:
    """An approved, step-by-step action plan produced by the planner."""

    content: str

    def __post_init__(self) -> None:
        text = (self.content or "").strip()
        object.__setattr__(self, "content", text)
        if len(text) < MIN_PLAN_CHARS:
            raise PlanError(
                f"Plan is too short ({len(text)} chars < {MIN_PLAN_CHARS})."
            )

    @property
    def is_valid(self) -> bool:
        return len(self.content.strip()) >= MIN_PLAN_CHARS


@dataclass(frozen=True, slots=True)
class ReviewFeedback:
    """Feedback produced by the reviewer that the coder must address."""

    text: str
    approved: bool = False

    @property
    def reasons(self) -> str:
        """Return the human readable rejection reasons (empty if approved)."""
        if self.approved:
            return ""
        return self.text


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A framework-neutral tool invocation requested by the model."""

    name: str
    args: dict[str, Any]
    id: str


@dataclass(frozen=True, slots=True)
class Turn:
    """A framework-neutral conversational message used by the application layer.

    ``role`` is one of ``system``, ``user``, ``assistant``, or ``tool``.
    Assistant turns may carry ``tool_calls``; tool turns carry ``tool_call_id``
    and ``name``. The application layer and use cases only ever see turns,
    never framework-specific message objects.
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


def parse_tool_call_from_text(content: str) -> list[dict] | None:
    """Extract a structured tool call from free-form LLM text (pure function).

    Tries, in order: explicit ``<tool_call>`` tags, markdown JSON code fences,
    direct JSON, and embedding JSON inside surrounding prose. Returns ``None``
    when no usable call is found. Used as a fallback when a model does not emit
    a native tool call.
    """
    if not content:
        return None

    content_str = content.strip()

    tag_match = re.search(r"<tool_call>(.*?)</tool_call>", content_str, re.DOTALL)
    if tag_match:
        content_str = tag_match.group(1).strip()
    else:
        code_block_match = re.search(r"```(?:json)?\s*(.*?)\s*```", content_str, re.DOTALL)
        if code_block_match:
            content_str = code_block_match.group(1).strip()

    def _build(node: dict) -> list[dict] | None:
        if isinstance(node, dict) and "name" in node:
            args = node.get("arguments") or node.get("parameters") or node.get("args") or {}
            if isinstance(args, str):
                import json

                try:
                    args = json.loads(args)
                except Exception:
                    pass
            return [{
                "name": node["name"],
                "args": args,
                "id": None,
                "type": "tool_call",
            }]
        return None

    imported_json = __import__("json")

    try:
        data = imported_json.loads(content_str)
        built = _build(data)
        if built:
            return built
    except Exception:
        pass

    try:
        start_idx = content_str.find("{")
        end_idx = content_str.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            json_part = content_str[start_idx:end_idx + 1]
            data = imported_json.loads(json_part)
            built = _build(data)
            if built:
                return built
    except Exception:
        pass

    return None
