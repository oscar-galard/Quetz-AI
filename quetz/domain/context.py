"""Value objects produced by the Context Compiler.

The compiler deliberately returns structured data rather than a prompt string:
the data can be inspected, tested, and re-rendered by any prompt template.
"""
from __future__ import annotations

from dataclasses import dataclass

from quetz.domain.task_spec import AcceptanceCriterion


@dataclass(frozen=True, slots=True)
class ContextFile:
    path: str
    language: str
    content: str
    start_line: int = 1
    end_line: int = 0
    is_new: bool = False
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class SymbolSnippet:
    path: str
    name: str
    kind: str
    signature: str
    docstring: str = ""
    start_line: int = 0
    end_line: int = 0


@dataclass(frozen=True, slots=True)
class ContextBundle:
    task_id: str
    title: str
    goal: str
    prompt: str = ""
    target_files: tuple[ContextFile, ...] = ()
    related_symbols: tuple[SymbolSnippet, ...] = ()
    interfaces: str = ""
    conventions: str = ""
    tree: str = ""
    git_diff: str = ""
    acceptance: tuple[AcceptanceCriterion, ...] = ()
    approx_tokens: int = 0
    omitted: tuple[str, ...] = ()
    memory: str = ""
    skills: str = ""

    def text_size(self) -> int:
        parts = [
            self.interfaces,
            self.conventions,
            self.tree,
            self.git_diff,
            self.memory,
            self.skills,
            *(f.content for f in self.target_files),
            *(f"{s.signature}\n{s.docstring}" for s in self.related_symbols),
        ]
        return sum(len(p) for p in parts)
