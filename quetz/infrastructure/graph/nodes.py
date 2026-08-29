"""LangGraph workflow state and graph nodes.

Nodes act as thin adapters: they convert the LangGraph/LangChain message state
into neutral turns, delegate to the application use cases, then translate the
results back into framework messages. All decision logic and orchestration
resides in the application layer.
"""
from __future__ import annotations

import os
import sys
from typing import Annotated, TypedDict

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    RemoveMessage,
)
from langchain_core.runnables import RunnableConfig
from langgraph.graph.message import add_messages

from quetz import config as q_config
from quetz.application.use_cases.coder import CodeUseCase
from quetz.application.use_cases.debug_report import DebugReportUseCase
from quetz.application.use_cases.debug_research import DebugResearchUseCase
from quetz.application.use_cases.decisions import build_action_log
from quetz.application.use_cases.planner import PlanUseCase
from quetz.application.use_cases.reviewer import ReviewUseCase
from quetz.application.use_cases.summarizer import SummarizeUseCase
from quetz.domain.exceptions import AgentTerminated
from quetz.domain.model import Task, ToolCall, Turn
from quetz.infrastructure.codec import langchain_to_turns, turn_to_langchain, turns_to_langchain
from quetz.infrastructure.container import Container
from quetz.infrastructure.tools.adapter import LangChainToolExecutor


class AgentState(TypedDict):
    task: str
    plan: str
    messages: Annotated[list[BaseMessage], add_messages]
    iteration: int
    review_feedback: str
    is_approved: bool
    summary: str


def _existing_workspace_files() -> list[str]:
    try:
        return [f for f in os.listdir(q_config.WORKSPACE_DIR) if not f.startswith(".")]
    except Exception:
        return []


def _new_task(state: AgentState) -> Task:
    return Task(state.get("task", ""))


# --------------------------------------------------------------------------
# Debug mode nodes
# --------------------------------------------------------------------------

def debug_research_node(state: AgentState, config: RunnableConfig, container: Container) -> dict:
    uc = DebugResearchUseCase(
        llm_binder=container.make_planner_llm(),
        tool_executor=container.executor,
        tool_specs=container.read_only_tool_specs,
        reporter=lambda text: print(text, flush=True),
    )
    turns = uc.execute(
        task=_new_task(state),
        workspace=q_config.WORKSPACE_DIR,
        existing_files=_existing_workspace_files(),
    )
    return {"messages": turns_to_langchain(turns)}


def debug_reporter_node(state: AgentState, config: RunnableConfig, container: Container) -> dict:
    research = langchain_to_turns(state.get("messages", []))
    uc = DebugReportUseCase(
        llm=container.make_llm(),
        writer=container.report_writer,
        reporter=lambda text: print(text, flush=True),
    )
    content = uc.execute(task=_new_task(state), research=research)
    return {"summary": content}


# --------------------------------------------------------------------------
# Normal coding mode nodes
# --------------------------------------------------------------------------

def planner_node(state: AgentState, config: RunnableConfig, container: Container) -> dict:
    # Already planned? Nothing to do.
    if state.get("plan"):
        return {}

    uc = PlanUseCase(
        llm_binder=container.make_planner_llm(),
        tool_executor=LangChainToolExecutor(),
        tool_specs=container.read_only_tool_specs,
        approver=container.approver,
        reporter=lambda text: print(text, flush=True),
    )
    try:
        plan = uc.execute(
            task=_new_task(state),
            workspace=q_config.WORKSPACE_DIR,
            existing_files=_existing_workspace_files(),
        )
    except AgentTerminated:
        q_config.play_alert_sound()
        print("\n❌ Task aborted by user.", flush=True)
        sys.exit(0)

    print("\n" + "=" * 80)
    print(plan)
    print("=" * 80 + "\n", flush=True)
    if not q_config.INTERACTIVE_MODE:
        print("\n🚀 Plan approved. Executing agent...")

    # Provide the research history to the coder as immediate context.
    # (Returns all turns; the coder uses the full message history.)
    return {"plan": plan, "messages": []}


def coder_node(state: AgentState, config: RunnableConfig, container: Container) -> dict:
    current_iter = state.get("iteration", 0)
    if current_iter >= q_config.MAX_ITERATIONS:
        return {
            "messages": [AIMessage(content="TASK COMPLETED: max iterations reached, task may be incomplete.")],
            "iteration": current_iter,
        }

    print("\n🦜 Quetz-AI Coder Thinking...", flush=True)

    history_turns = langchain_to_turns(state.get("messages", []))

    has_printed_tool = {"flag": False}

    def _on_content(text: str) -> None:
        sys.stdout.write(text)
        sys.stdout.flush()
        if text and "Calling tool" in text:
            has_printed_tool["flag"] = True

    uc = CodeUseCase(
        llm_binder=container.make_binder(container.all_tool_specs),
        tool_specs=container.all_tool_specs,
    )
    new_turns = uc.execute(
        workspace=q_config.WORKSPACE_DIR,
        plan=state.get("plan", ""),
        review_feedback=state.get("review_feedback", ""),
        summary=state.get("summary", ""),
        history=history_turns,
        on_content=_on_content,
        max_iterations=q_config.MAX_ITERATIONS,
        iteration=current_iter,
    )
    if has_printed_tool["flag"]:
        sys.stdout.write(")")
    print(flush=True)

    new_messages = [turn_to_langchain(t) for t in new_turns]
    return {"messages": new_messages, "iteration": current_iter + 1}


def tools_node(state: AgentState, config: RunnableConfig, container: Container) -> dict:
    last_msg: BaseMessage | None = state["messages"][-1] if state.get("messages") else None
    tool_calls = getattr(last_msg, "tool_calls", None) or []
    if not tool_calls:
        return {"messages": []}

    executor = LangChainToolExecutor()
    tool_messages = []
    for tc in tool_calls:
        tool_name = tc["name"]
        tool_args = tc["args"]
        call = ToolCall(name=tool_name, args=tool_args, id=tc.get("id") or "")

        if q_config.INTERACTIVE_MODE and tool_name in ("write_file", "edit_file") \
                and not container.confirmer(tool_name, tool_args):
            q_config.play_alert_sound()
            result_content = "OPERATION REJECTED BY USER. Do not retry the same edit without asking."
            print(f"  ❌ {result_content}\n")
        else:
            outcome = executor.execute(call)
            result_content = outcome.content
            print(f"  ✅ Tool Result: {result_content}\n")

        from langchain_core.messages import ToolMessage

        tool_messages.append(ToolMessage(
            content=str(result_content),
            tool_call_id=call.id,
            name=tool_name,
        ))

    return {"messages": tool_messages}


def reviewer_node(state: AgentState, config: RunnableConfig, container: Container) -> dict:
    print("\n🔍 Quetz-AI Reviewer evaluating implementation...", flush=True)

    action_log = build_action_log(langchain_to_turns(state.get("messages", [])))
    uc = ReviewUseCase(llm=container.make_llm())
    feedback = uc.execute(
        task=state.get("task", ""),
        plan=state.get("plan", ""),
        action_log=action_log,
    )
    print(f"\n📢 Review Result:\n{feedback.text}\n", flush=True)

    if feedback.approved:
        return {"is_approved": True, "review_feedback": ""}
    q_config.play_alert_sound()
    return {"is_approved": False, "review_feedback": feedback.reasons}


def summarize_node(state: AgentState, config: RunnableConfig, container: Container) -> dict:
    messages: list[BaseMessage] = state.get("messages", [])
    if len(messages) <= 4:
        return {}

    uc = SummarizeUseCase(llm=container.make_llm())
    summary = uc.execute(history=langchain_to_turns(messages))

    delete_messages: list[RemoveMessage] = []
    if len(messages) > 2:
        for msg in messages[:-2]:
            if msg.id:
                delete_messages.append(RemoveMessage(id=msg.id))

    return {"summary": summary, "messages": delete_messages}
