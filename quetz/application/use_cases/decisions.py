"""Pure decision logic for the workflow graph.

These functions decide where control flows next given only neutral data
(turn state, iteration counters). Kept framework-agnostic and unit-testable.
"""
from __future__ import annotations

from quetz.domain.model import Turn


def latest_execution_step(state_messages: list[Turn]) -> str:
    """Return the next step for the last (most recent) message.

    - "tools" if the last turn requests tool calls.
    - "reviewer" if the last turn is a final text answer.
    """
    if state_messages:
        last = state_messages[-1]
        if last.is_tool_call:
            return "tools"
    return "reviewer"


def should_continue(
    state_messages: list[Turn],
    *,
    no_reviewer: bool,
    max_iterations: int,
    iteration: int,
) -> str:
    """Original routing: tools -> reviewer/finish based on last message state."""
    last = state_messages[-1] if state_messages else None
    has_tools = bool(last and last.is_tool_call)
    if has_tools and iteration <= max_iterations:
        return "tools"
    if no_reviewer:
        return "finish"
    return "reviewer"


def should_summarize(message_count: int, threshold: int = 4) -> str:
    """Decide whether to summarize before continuing (or finishing)."""
    if message_count > threshold:
        return "summarize"
    return "coder"


def should_approve(approved: bool) -> str:
    """Route after a review: finish on approval, else run the coder again."""
    return "finish" if approved else "coder"


def summarize_node_plan(
    messages: list[Turn],
    *,
    summary: str,
    keep: int = 2,
) -> tuple[str, list[Turn]]:
    """Pure logic for summarization: merged summary + turns to retain.

    Returns ``(next_summary, retained_turns)``. The infrastructure graph adapter
    is responsible for actually emitting framework ``RemoveMessage`` directives
    based on which turn ids to drop.
    """
    if len(messages) <= 4:
        return summary, messages

    import operator

    def _merged(old: str | None, new: str) -> str:
        if not old:
            return new
        return f"Recent Activity Summary: {new}"

    # The coder summarizer produces a fresh summary; keep the last two turns.
    retained = messages[-keep:] if keep > 0 else []
    return _merged(summary, ""), retained


def build_action_log(state_messages: list[Turn], snippet_len: int = 300) -> str:
    """Render neutral turns into the 'Coder Action Log' text for the reviewer."""
    lines: list[str] = []
    for msg in state_messages:
        if msg.is_tool_call:
            for tc in msg.tool_calls:
                lines.append(f"Called Tool: {tc.name} with args: {tc.args}")
        elif msg.role == "tool" and msg.content:
            snippet = msg.content[:snippet_len]
            if len(msg.content) > snippet_len:
                snippet += "..."
            lines.append(f"Tool Result ({msg.name}): {snippet}")
        elif msg.role == "assistant" and msg.content:
            lines.append(f"Agent response: {msg.content}")
    return "\n".join(lines)
