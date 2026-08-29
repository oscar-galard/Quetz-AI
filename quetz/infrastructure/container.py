"""Composition root for the infrastructure graph.

Wires concrete adapters (LangChain LLM + tracing proxy, tool executor, report
writer) together and exposes factory methods the graph nodes use. Presentation
constructs this with CLI-specific collaborators (plan approver, tool confirmer)
to keep dependency injection explicit.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable

from quetz import config as q_config
from quetz.application.ports.llm import LLMPort, ToolBinder, ToolSpec
from quetz.application.ports.output import PlanApprover, ReportWriter
from quetz.application.ports.tool_executor import ToolExecutorPort
from quetz.infrastructure.llm.adapter import LangChainLLMAdapter
from quetz.infrastructure.llm.factory import build_base_chat_model
from quetz.infrastructure.llm.tracing import TracingLLMProxy
from quetz.infrastructure.reporting.report_writer import FileReportWriter
from quetz.infrastructure.tools.adapter import LangChainToolExecutor
from quetz.infrastructure.tools.specs import ALL_TOOL_SPECS, READ_ONLY_TOOL_SPECS

#: Confirms whether a write/edit tool call may proceed (presentation-injected).
ToolConfirmer = Callable[[str, dict], bool]


def _auto_approve(_name: str, _args: dict) -> bool:
    return True


def _tracing_enabled() -> bool:
    return os.environ.get("LANGCHAIN_TRACING_V2", "").lower() == "true"


@dataclass
class Container:
    """Carries all infrastructure collaborators the graph nodes require."""

    all_tool_specs: list[ToolSpec] = field(default_factory=lambda: ALL_TOOL_SPECS)
    read_only_tool_specs: list[ToolSpec] = field(default_factory=lambda: READ_ONLY_TOOL_SPECS)
    executor: ToolExecutorPort = field(default_factory=LangChainToolExecutor)
    report_writer: ReportWriter = field(default_factory=FileReportWriter)
    approver: PlanApprover = field(default_factory=lambda: _AutoApprove())
    confirmer: ToolConfirmer = field(default_factory=lambda: _auto_approve)
    tracing: bool = field(default_factory=_tracing_enabled)

    # -- factory methods ------------------------------------------------

    def make_llm(self, tools: list[ToolSpec] | None = None) -> LLMPort:
        """Build a (possibly tool-bound) LLM adapter, wrapped in tracing."""
        adapter: LangChainLLMAdapter = LangChainLLMAdapter(build_base_chat_model())
        if tools:
            adapter = LangChainLLMAdapter(
                build_base_chat_model().bind_tools(
                    [
                        {
                            "name": t.name,
                            "description": t.description,
                            "parameters": t.schema,
                        }
                        for t in tools
                    ]
                )
            )
        if self.tracing:
            return TracingLLMProxy(adapter)
        return adapter

    def make_binder(self, tools: list[ToolSpec]) -> ToolBinder:
        """Return a ToolBinder whose bound variants are all traced LLM adapters."""
        return self.make_llm()

    def make_planner_llm(self) -> ToolBinder:
        return self.make_llm()

    def make_binder(self, tools: list[ToolSpec]) -> ToolBinder:
        """Return a ToolBinder whose bound variants are all traced LLM adapters."""
        return self.make_llm()

    def make_planner_llm(self) -> ToolBinder:
        return self.make_llm()


class _AutoApprove(PlanApprover):
    """Automatically approves plans when running without a CLI approver."""

    def decide(self, plan: str):
        from quetz.application.ports.output import Approval

        return Approval(status="approved")
