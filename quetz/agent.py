"""Compatibility facade for the Quetz-AI agent.

This module exists to keep the previous public API stable while the actual
implementation lives in the layered architecture:

    domain/ ............ pure business logic (no framework imports)
    application/ ....... ports + use cases (framework-agnostic)
    infrastructure/ .... adapters, LangGraph graph, LangSmith tracing
    quetz/cli.py ....... presentation (CLI + composition root)

Most symbols below are thin re-exports / thin wrappers around the new modules.
New code should depend on the layered modules directly rather than this facade.
"""
from __future__ import annotations

from quetz import config as q_config
from quetz.domain.exceptions import AgentTerminated, PlanError, QuetzError, TaskError
from quetz.domain.model import (
    Plan,
    ReviewFeedback,
    Task,
    ToolCall,
    Turn,
    parse_tool_call_from_text,
)
from quetz.infrastructure.container import Container
from quetz.infrastructure.graph import nodes as _nodes
from quetz.infrastructure.graph.builder import container as default_container, set_container
from quetz.infrastructure.llm.adapter import LangChainLLMAdapter
from quetz.infrastructure.llm.factory import build_base_chat_model
from quetz.infrastructure.llm.tracing import TracingLLMProxy

__all__ = [
    "build_graph",
    "get_llm",
    "get_llm_base",
    "parse_tool_call_from_text",
    "planner_node",
    "coder_node",
    "tools_node",
    "reviewer_node",
    "summarize_node",
    "debug_research_node",
    "debug_reporter_node",
    "should_continue",
    "should_summarize",
    "should_approve",
    "q_config",
    "Container",
    "Task",
    "Plan",
    "Turn",
    "ToolCall",
    "ReviewFeedback",
]


def get_llm_base(bind_tools=None) -> LangChainLLMAdapter:
    """Build a traced LangChain LLM adapter, optionally tool-bound.

    Kept for backward compatibility with callers that previously received a raw
    LangChain model. ``bind_tools`` accepts langchain tool objects or nothing.
    """
    model = build_base_chat_model()

    if bind_tools:
        specs = [
            {"name": t.name, "description": t.description, "parameters": getattr(t, "args", {})}
            for t in bind_tools
        ]
        model = model.bind_tools(specs)
    adapter = LangChainLLMAdapter(model)
    return TracingLLMProxy(adapter) if _tracing() else adapter


def get_llm() -> LangChainLLMAdapter:
    """Build a traced LLM adapter bound to the full tool set (backward compat)."""
    from quetz.application.ports.llm import ToolSpec
    from quetz.infrastructure.tools.specs import ALL_TOOL_SPECS

    proxy = get_llm_base()
    if isinstance(proxy, TracingLLMProxy) or hasattr(proxy, "bind_tools"):
        return proxy.bind_tools(ALL_TOOL_SPECS)
    return proxy


def _tracing() -> bool:
    import os

    return os.environ.get("LANGCHAIN_TRACING_V2", "").lower() == "true"


# --------------------------------------------------------------------------
# Node wrappers (preserve original signatures; delegate to infrastructure).
# --------------------------------------------------------------------------

def planner_node(state, config=None, container=None):
    return _nodes.planner_node(state, config, container or default_container)


def coder_node(state, config=None, container=None):
    return _nodes.coder_node(state, config, container or default_container)


def tools_node(state, config=None, container=None):
    return _nodes.tools_node(state, config, container or default_container)


def reviewer_node(state, config=None, container=None):
    return _nodes.reviewer_node(state, config, container or default_container)


def summarize_node(state, config=None, container=None):
    return _nodes.summarize_node(state, config, container or default_container)


def debug_research_node(state, config=None, container=None):
    return _nodes.debug_research_node(state, config, container or default_container)


def debug_reporter_node(state, config=None, container=None):
    return _nodes.debug_reporter_node(state, config, container or default_container)


# --------------------------------------------------------------------------
# Pure routing decisions (re-exported from the application layer).
# --------------------------------------------------------------------------

def should_continue(state, *args, **kwargs):
    from quetz.application.use_cases.decisions import should_continue as _fn

    return _fn(
        _state_turns(state),
        no_reviewer=kwargs.get("no_reviewer", q_config.NO_REVIEWER),
        max_iterations=kwargs.get("max_iterations", q_config.MAX_ITERATIONS),
        iteration=state.get("iteration", 0),
    )


def should_summarize(state):
    from quetz.application.use_cases.decisions import should_summarize as _fn

    return _fn(len(state.get("messages", [])) if isinstance(state, dict) else state)


def should_approve(state):
    from quetz.application.use_cases.decisions import should_approve as _fn

    return _fn(state.get("is_approved", False))


def _state_turns(state):
    from quetz.infrastructure.codec import langchain_to_turns

    return langchain_to_turns(state.get("messages", []))


def build_graph():
    """Compile the LangGraph workflow (debug or coding mode)."""
    from quetz.infrastructure.graph.builder import build_graph as _build

    return _build()
