"""LangSmith observability wrappers (infrastructure only).

Tracing is confined to this layer via the Proxy and Decorator patterns. The
application use cases and domain are completely unaware of LangSmith: they talk
to the plain LLM port, and the composition root wraps them with tracing.

Two mechanisms are provided:

1. :class:`TracingLLMProxy` — a Proxy that decorates every model call with
   ``@traceable`` (LangSmith), forwarding to an inner LLM port.
2. :func:`trace_use_case` — a thin Decorator that wraps an entire use-case
   execution method in a ``traceable`` span.

Both are optional: if LangSmith is not available or tracing is disabled, the
unwrapped path is used transparently.
"""
from __future__ import annotations

import functools
from typing import Any, Callable, TypeVar

from quetz.application.ports.llm import LLMPort, LLMResult, ToolSpec
from quetz.domain.model import Turn

T = TypeVar("T")

_AVAILABLE: bool | None = None


def _traceable_available() -> bool:
    global _AVAILABLE
    if _AVAILABLE is None:
        try:
            from langsmith import traceable  # noqa: F401

            _AVAILABLE = True
        except Exception:
            _AVAILABLE = False
    return bool(_AVAILABLE)


def trace_use_case(name: str) -> Callable[[T], T]:
    """Decorate a use-case method with a LangSmith span (no-op if unavailable)."""

    def decorator(fn: T) -> T:
        if not _traceable_available():
            return fn
        from langsmith import traceable

        return traceable(fn, name=name)  # type: ignore[return-value]

    return decorator


class TracingLLMProxy(LLMPort):
    """A Proxy that adds LangSmith tracing around an inner LLM port.

    It re-binds to a traced inner adapter, so every ``invoke``/``stream`` call
    (including tool-bound variants) becomes a traced LangSmith run.
    """

    def __init__(self, inner: LLMPort, run_prefix: str = "quetz.llm") -> None:
        self._inner = inner
        self._run_prefix = run_prefix

    def bind_tools(self, tools: list[ToolSpec]) -> LLMPort:
        if hasattr(self._inner, "bind_tools"):
            bound = self._inner.bind_tools(tools)  # type: ignore[attr-defined]
            return TracingLLMProxy(bound, run_prefix=self._run_prefix)
        return self

    def invoke(self, messages: list[Turn]) -> LLMResult:
        if not _traceable_available():
            return self._inner.invoke(messages)
        from langsmith import traceable

        return traceable(
            self._inner.invoke,
            name=f"{self._run_prefix}.invoke",
        )(messages)

    def stream(
        self,
        messages: list[Turn],
        *,
        on_content: Callable[[str], None] | None = None,
        on_tool_name: Callable[[str], None] | None = None,
        on_tool_args: Callable[[str], None] | None = None,
    ) -> LLMResult:
        if not _traceable_available():
            return self._inner.stream(
                messages,
                on_content=on_content,
                on_tool_name=on_tool_name,
                on_tool_args=on_tool_args,
            )
        from langsmith import traceable

        return traceable(
            self._inner.stream,
            name=f"{self._run_prefix}.stream",
        )(messages, on_content=on_content, on_tool_name=on_tool_name, on_tool_args=on_tool_args)
