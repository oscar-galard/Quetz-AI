"""Planner use case: research the workspace and produce an approved plan.

This use case depends only on ports (LLM, read-only tool executor, plan
approver) and the domain. It never touches LangChain or the graph framework.
"""
from __future__ import annotations

from typing import Callable

from quetz.application.ports.llm import LLMPort, ToolBinder, ToolSpec
from quetz.application.ports.output import Approval, PlanApprover
from quetz.application.ports.tool_executor import ToolExecutorPort
from quetz.application.use_cases import prompts
from quetz.domain.exceptions import AgentTerminated
from quetz.domain.model import Task, ToolCall, Turn

MAX_RESEARCH_STEPS = 5
MAX_SELF_CORRECT_ATTEMPTS = 5
MIN_VALID_PLAN_LENGTH = 30

#: Print a status/progress line (e.g. which tool is being called).
Reporter = Callable[[str], None]


def _noop(_text: str) -> None:
    pass


class PlanUseCase:
    """Drafts and refines an action plan interactively."""

    def __init__(
        self,
        llm_binder: ToolBinder,
        tool_executor: ToolExecutorPort,
        tool_specs: list[ToolSpec],
        approver: PlanApprover,
        reporter: Reporter | None = None,
    ) -> None:
        self._binder = llm_binder
        self._tools = tool_executor
        self._tool_specs = tool_specs
        self._approver = approver
        self._report = reporter or _noop

    def execute(
        self,
        task: Task,
        workspace: str,
        existing_files: list[str],
    ) -> tuple[str, list[Turn]]:
        """Return ``(approved_plan_text, research_context_turns)``.

        The research context is the tool-call/tool-result history gathered while
        planning. It is handed to the coder so it never repeats the same reads,
        which is critical with small local context windows.
        """
        self._report("🧠 Researching workspace...")

        messages: list[Turn] = [
            Turn.system(prompts.build_planning_system_prompt(workspace, existing_files)),
            Turn.user(task.text),
        ]
        research_llm = self._binder.bind_tools(self._tool_specs)

        research_steps = 0
        while research_steps < MAX_RESEARCH_STEPS:
            result = research_llm.invoke(messages)
            assistant = result.message
            if assistant is not None:
                messages.append(assistant)
            if not result.tool_calls:
                break
            research_steps += 1
            for call in self._as_calls(result.tool_calls):
                self._report(f"  🔍 Planner Research: Calling tool {call.name}({call.args})...")
                outcome = self._tools.execute(call)
                messages.append(Turn.tool(outcome.content, outcome.tool_call_id, outcome.name))

        if research_steps >= MAX_RESEARCH_STEPS:
            self._report("🔍 Planner completed research phase. Synthesizing proposed plan...")
            messages.append(Turn.user(
                "Please synthesize your research and formulate a structured, "
                "step-by-step action plan to accomplish the user's task. Present "
                "your plan under the header '# PROPOSED PLAN'."
            ))
            plan_content = self._binder.bind_tools([]).invoke(messages).content
        else:
            plan_content = result.content

        self._report("✏️ Drafting proposed plan...")
        plan_content = self._ensure_valid_plan(messages, plan_content)

        plan = self._approval_loop(messages, plan_content, workspace)
        # Hand the coder only a compact research feed: drop the system/task
        # header turns and any trailing plain-text messages (the plan itself is
        # injected by the coder system prompt), and bound both the number of
        # turns and each tool result so we don't choke a small local window -
        # a full window prevents the model from emitting a tool call.
        research_context = self._compact_research(messages)
        return plan, research_context

    @staticmethod
    def _compact_research(messages: list[Turn], max_turns: int = 6, max_content: int = 1200) -> list[Turn]:
        feed: list[Turn] = []
        for t in messages[2:]:
            if t.role == "assistant":
                if t.tool_calls:
                    feed.append(t)
            elif t.role == "tool":
                content = t.content
                if len(content) > max_content:
                    content = content[:max_content] + "\n...[truncated]..."
                feed.append(Turn.tool(content, t.tool_call_id or "", t.name or ""))
            if len(feed) >= max_turns:
                break
        return feed

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _as_calls(raw: list[dict]) -> list[ToolCall]:
        calls: list[ToolCall] = []
        for item in raw:
            call_id = item.get("id") or ""
            calls.append(ToolCall(
                name=item.get("name", ""),
                args=item.get("args", {}) or {},
                id=call_id,
            ))
        return calls

    def _ensure_valid_plan(self, messages: list[Turn], plan_content: str) -> str:
        """Retry until the plan text is long enough (bounded self-correction)."""
        attempts = 0
        while len((plan_content or "").strip()) < MIN_VALID_PLAN_LENGTH and attempts < MAX_SELF_CORRECT_ATTEMPTS:
            attempts += 1
            self._report(
                f"⚠️  Received short/invalid plan response from LLM "
                f"(content: {plan_content!r}), retrying self-correction "
                f"(attempt {attempts}/{MAX_SELF_CORRECT_ATTEMPTS})..."
            )
            messages.append(Turn.assistant(plan_content))
            messages.append(Turn.user(
                "The plan you formulated is too short or invalid. Please formulate "
                "a complete, structured, step-by-step action plan to accomplish the "
                "user's task. Present your plan under the header '# PROPOSED PLAN'."
            ))
            plan_content = self._binder.bind_tools([]).invoke(messages).content
        return plan_content

    def _approval_loop(self, messages: list[Turn], plan_content: str, workspace: str) -> str:
        """Present the plan to the approver until approved or aborted."""
        while True:
            if len((plan_content or "").strip()) >= MIN_VALID_PLAN_LENGTH:
                decision = self._approver.decide(plan_content)
            else:
                decision = Approval(status="approved")

            if decision.status == "approved":
                return plan_content
            if decision.status == "abort":
                raise AgentTerminated("Task aborted by user.")
            # refine
            messages.append(Turn.assistant(plan_content))
            messages.append(Turn.user(
                f"Please refine the plan with this feedback: {decision.feedback}"
            ))
            plan_content = self._binder.bind_tools([]).invoke(messages).content
            self._report(f"🔄 Refining plan based on feedback...\n{plan_content}")
