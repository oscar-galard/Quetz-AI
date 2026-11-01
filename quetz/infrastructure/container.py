"""Composition root for the stateless planner/executor pipeline."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from quetz.application.ports.git import GitPort
from quetz.application.ports.index import ProjectIndexPort
from quetz.application.ports.llm import LLMPort
from quetz.application.ports.memory import MemoryStorePort
from quetz.application.ports.skills import SkillIndexPort
from quetz.application.ports.validator import ValidationPort
from quetz.application.prompts.planner import PLAN_SCHEMA
from quetz.infrastructure.fs.editor import AtomicEditor
from quetz.infrastructure.git.repo import GitRepo
from quetz.infrastructure.index.sqlite_index import SqliteProjectIndex
from quetz.infrastructure.llm.adapter import LangChainLLMAdapter
from quetz.infrastructure.llm.factory import build_chat_model
from quetz.infrastructure.llm.tracing import TracingLLMProxy
from quetz.infrastructure.memory.store import FileMemoryStore
from quetz.infrastructure.skills.index import FileSkillIndex
from quetz.infrastructure.validation.command_validator import CommandValidator


def _tracing_enabled() -> bool:
    return os.environ.get("LANGCHAIN_TRACING_V2", "").lower() == "true"


@dataclass
class Container:
    workspace: str
    index: ProjectIndexPort
    git: GitPort
    validator: ValidationPort
    memory: MemoryStorePort
    skills: SkillIndexPort
    tracing: bool = field(default_factory=_tracing_enabled)

    @classmethod
    def build(cls, workspace: str) -> "Container":
        return cls(
            workspace=workspace,
            index=SqliteProjectIndex(workspace),
            git=GitRepo(workspace),
            validator=CommandValidator(workspace),
            memory=FileMemoryStore(workspace),
            skills=FileSkillIndex(workspace),
        )

    def make_editor(self) -> AtomicEditor:
        return AtomicEditor(self.workspace)

    def make_executor_llm(self) -> LLMPort:
        adapter = LangChainLLMAdapter(
            build_chat_model("executor", structured=True)
        )
        return TracingLLMProxy(adapter) if self.tracing else adapter

    def make_planner_llm(self) -> LLMPort:
        adapter = LangChainLLMAdapter(
            build_chat_model("planner", structured=PLAN_SCHEMA)
        )
        return TracingLLMProxy(adapter) if self.tracing else adapter
