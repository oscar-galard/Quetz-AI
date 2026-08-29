"""LangGraph workflow builder.

Adapts the application routing/decision functions and the node adapters into a
compiled LangGraph state machine. Only this module imports ``langgraph``.
"""
from __future__ import annotations

import functools

from quetz import config as q_config
from quetz.infrastructure.container import Container
from quetz.infrastructure.graph import nodes

#: The active dependency container used by the graph builder (composition root).
container: Container = Container()


def set_container(c: Container) -> None:
    """Set the active dependency container used by the graph builder."""
    global container
    container = c


def _bind(fn):
    """Bind a node adapter to the current container at graph-build time."""
    return functools.partial(fn, container=container)


def build_graph():
    """Compile the LangGraph workflow (debug or coding mode)."""
    from langgraph.graph import END, START, StateGraph

    from quetz.application.use_cases.decisions import should_approve as _approve_logic
    from quetz.application.use_cases.decisions import should_continue as _continue_logic
    from quetz.application.use_cases.decisions import should_summarize as _summarize_logic
    from quetz.infrastructure.codec import langchain_to_turns

    builder = StateGraph(nodes.AgentState)

    if q_config.DEBUG_MODE:
        builder.add_node("debug_researcher", _bind(nodes.debug_research_node))
        builder.add_node("debug_reporter", _bind(nodes.debug_reporter_node))
        builder.add_edge(START, "debug_researcher")
        builder.add_edge("debug_researcher", "debug_reporter")
        builder.add_edge("debug_reporter", END)
        return builder.compile()

    builder.add_node("planner", _bind(nodes.planner_node))
    builder.add_node("coder", _bind(nodes.coder_node))
    builder.add_node("tools", _bind(nodes.tools_node))
    builder.add_node("reviewer", _bind(nodes.reviewer_node))
    builder.add_node("summarize", _bind(nodes.summarize_node))

    builder.add_edge(START, "planner")
    builder.add_edge("planner", "coder")

    def _continue_route(state):
        turns = langchain_to_turns(state.get("messages", []))
        return _continue_logic(
            turns,
            no_reviewer=q_config.NO_REVIEWER,
            max_iterations=q_config.MAX_ITERATIONS,
            iteration=state.get("iteration", 0),
        )

    builder.add_conditional_edges(
        "coder",
        _continue_route,
        {"tools": "tools", "reviewer": "reviewer", "finish": END},
    )

    def _summarize_route(state):
        return _summarize_logic(len(state.get("messages", [])))

    builder.add_conditional_edges(
        "tools",
        _summarize_route,
        {"summarize": "summarize", "coder": "coder"},
    )
    builder.add_edge("summarize", "coder")

    def _reviewer_route(state):
        return _approve_logic(state.get("is_approved", False))

    builder.add_conditional_edges(
        "reviewer",
        _reviewer_route,
        {"coder": "coder", "finish": END},
    )

    return builder.compile()
