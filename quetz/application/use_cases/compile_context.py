"""Context Compiler: build a minimal, deterministic context bundle per task.

The compiler never calls an LLM. It combines the project index, target file
excerpts, one hop of imported interfaces, project conventions, git state and a
bounded workspace tree, then fits the result into a token budget.
"""
from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from typing import Callable

from quetz import config as q_config
from quetz.application.ports.git import GitPort
from quetz.application.ports.index import IndexedSymbol, ProjectIndexPort
from quetz.application.ports.memory import MemoryStorePort
from quetz.application.ports.skills import SkillIndexPort
from quetz.domain.context import ContextBundle, ContextFile, SymbolSnippet
from quetz.domain.task_spec import TaskSpec
from quetz.infrastructure.fs.paths import (
    count_lines,
    language_for,
    read_lines,
    read_text,
    resolve_workspace_path,
    workspace_root,
)
from quetz.infrastructure.fs.tree import build_tree

_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "into",
    "your",
    "current",
    "using",
    "add",
    "new",
    "make",
    "should",
    "must",
    "task",
    "file",
    "files",
    "code",
    "implement",
    "update",
    "create",
}


def _keywords(task: TaskSpec) -> set[str]:
    text = " ".join((task.title, task.goal, task.notes, *task.symbols, *task.interfaces))
    words = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text)
    return {word.lower() for word in words if word.lower() not in _STOPWORDS}


class CompileContextUseCase:
    def __init__(
        self,
        index: ProjectIndexPort,
        workspace: str,
        *,
        git: GitPort | None = None,
        memory: MemoryStorePort | None = None,
        skills: SkillIndexPort | None = None,
        token_budget: int | None = None,
        reporter: Callable[[str], None] | None = None,
    ) -> None:
        self._index = index
        self._workspace = workspace_root(workspace)
        self._git = git
        self._memory = memory
        self._skills = skills
        self._token_budget = token_budget or q_config.CONTEXT_TOKEN_BUDGET
        self._report = reporter or (lambda _text: None)

    def execute(self, task: TaskSpec) -> ContextBundle:
        self._report(f"🧩 Compiling context for {task.id}...")
        self._index.ensure_built()
        if self._skills is not None:
            self._skills.ensure_built()
        keywords = _keywords(task)
        omitted: list[str] = []

        target_files = self._target_files(task, omitted)
        related = self._related_symbols(task, target_files, keywords)
        interfaces = self._interfaces(task, related, omitted)
        conventions = self._conventions(task, target_files, related, omitted)
        skills = self._skills_context(task, target_files, related, omitted)
        memory = self._memory_context(task)
        tree = build_tree(self._workspace, max_depth=3, max_entries=180)
        git_diff = self._git_context(task, omitted)

        target_files = self._fit_targets(target_files, omitted)
        budget_chars = self._token_budget * 4
        used = sum(len(f.content) for f in target_files)
        remaining = max(0, budget_chars - used)

        interfaces = self._take(
            interfaces,
            min(q_config.CONTEXT_MAX_INTERFACE_CHARS, int(remaining * 0.45)),
            "interfaces",
            omitted,
        )
        remaining -= len(interfaces)
        conventions = self._take(
            conventions,
            min(q_config.CONTEXT_MAX_CONVENTION_CHARS, int(remaining * 0.55)),
            "conventions",
            omitted,
        )
        remaining -= len(conventions)
        skills = self._take(
            skills,
            min(q_config.CONTEXT_MAX_SKILLS_CHARS, int(remaining * 0.55)),
            "stack skills",
            omitted,
        )
        remaining -= len(skills)
        memory = self._take(
            memory,
            min(q_config.CONTEXT_MAX_MEMORY_CHARS, int(remaining * 0.35)),
            "project memory",
            omitted,
        )
        remaining -= len(memory)
        git_diff = self._take(
            git_diff,
            min(q_config.CONTEXT_MAX_DIFF_CHARS, int(remaining * 0.6)),
            "git diff",
            omitted,
        )
        remaining -= len(git_diff)
        tree = self._take(tree, max(0, min(remaining, 2500)), "workspace tree", omitted)

        bundle = ContextBundle(
            task_id=task.id,
            title=task.title,
            goal=task.goal,
            prompt=task.prompt,
            target_files=tuple(target_files),
            related_symbols=tuple(related),
            interfaces=interfaces,
            conventions=conventions,
            tree=tree,
            git_diff=git_diff,
            acceptance=task.acceptance,
            approx_tokens=1,
            omitted=tuple(omitted),
            memory=memory,
            skills=skills,
        )
        return replace(bundle, approx_tokens=max(1, bundle.text_size() // 4))

    # -- target files ------------------------------------------------------

    def _target_files(self, task: TaskSpec, omitted: list[str]) -> list[ContextFile]:
        files: list[ContextFile] = []
        for rel_path in task.editable_files:
            full = resolve_workspace_path(self._workspace, rel_path)
            if not full.is_file():
                files.append(
                    ContextFile(
                        path=rel_path,
                        language=language_for(rel_path),
                        content="",
                        start_line=0,
                        end_line=0,
                        is_new=True,
                    )
                )
                continue

            text = read_text(full, max_chars=q_config.CONTEXT_MAX_FILE_CHARS * 4)
            lines = count_lines(text)
            if len(text) > q_config.CONTEXT_MAX_FILE_CHARS or lines > q_config.CONTEXT_MAX_FILE_LINES:
                excerpt = self._outline_excerpt(rel_path, task)
                files.append(
                    ContextFile(
                        path=rel_path,
                        language=language_for(rel_path),
                        content=excerpt,
                        start_line=1,
                        end_line=count_lines(excerpt),
                        truncated=True,
                    )
                )
                omitted.append(f"{rel_path}: full file replaced by targeted excerpt")
            else:
                files.append(
                    ContextFile(
                        path=rel_path,
                        language=language_for(rel_path),
                        content=text,
                        start_line=1,
                        end_line=lines,
                    )
                )
        return files

    def _outline_excerpt(self, rel_path: str, task: TaskSpec) -> str:
        full = resolve_workspace_path(self._workspace, rel_path)
        header = read_lines(full, 1, q_config.CONTEXT_HEADER_LINES).rstrip()
        blocks: list[str] = [header] if header else []
        symbols = self._index.symbols(path=rel_path)
        wanted = {s.lower() for s in task.symbols}
        keywords = _keywords(task)
        selected: list[IndexedSymbol] = []

        for symbol in symbols:
            haystack = " ".join(
                (symbol.name, symbol.qualname, symbol.signature, symbol.docstring, *symbol.tags)
            ).lower()
            if symbol.name.lower() in wanted or any(k in haystack for k in keywords):
                selected.append(symbol)
        if not selected:
            selected = [s for s in symbols if s.kind not in ("method", "function")][:4]
        if not selected:
            selected = symbols[:4]

        seen: set[tuple[str, int, int]] = set()
        for symbol in selected[:8]:
            key = (symbol.path, symbol.start_line, symbol.end_line)
            if key in seen or symbol.start_line <= 0:
                continue
            seen.add(key)
            body = read_lines(full, symbol.start_line, symbol.end_line).rstrip()
            blocks.append(
                f"\n# --- {symbol.kind} {symbol.qualname} "
                f"(lines {symbol.start_line}-{symbol.end_line}) ---\n{body}"
            )
        return "\n".join(blocks).strip()

    def _fit_targets(self, files: list[ContextFile], omitted: list[str]) -> list[ContextFile]:
        budget_chars = int(self._token_budget * 4 * 0.68)
        total = sum(len(f.content) for f in files)
        if total <= budget_chars or not files:
            return files

        per_file = max(600, budget_chars // max(1, len(files)))
        fitted: list[ContextFile] = []
        for context_file in files:
            content = context_file.content
            if len(content) > per_file:
                head = content[: int(per_file * 0.75)]
                tail_size = int(per_file * 0.15)
                tail = content[-tail_size:] if tail_size > 0 else ""
                content = (
                    head
                    + "\n...# [middle truncated by context budget] ...#\n"
                    + tail
                )
                omitted.append(f"{context_file.path}: truncated to fit context budget")
            fitted.append(
                ContextFile(
                    path=context_file.path,
                    language=context_file.language,
                    content=content,
                    start_line=context_file.start_line,
                    end_line=context_file.end_line,
                    is_new=context_file.is_new,
                    truncated=context_file.truncated or content != context_file.content,
                )
            )
        return fitted

    # -- related symbols / interfaces -------------------------------------

    def _related_symbols(
        self,
        task: TaskSpec,
        target_files: list[ContextFile],
        keywords: set[str],
    ) -> list[SymbolSnippet]:
        target_paths = {f.path for f in target_files}
        seen: set[tuple[str, str, str]] = set()
        related: list[SymbolSnippet] = []

        def add(symbol: IndexedSymbol, *, include_body: bool = False) -> None:
            key = (symbol.path, symbol.qualname, symbol.kind)
            if key in seen or symbol.path in target_paths:
                return
            seen.add(key)
            doc_lines = (symbol.docstring or "").strip().splitlines()
            related.append(
                SymbolSnippet(
                    path=symbol.path,
                    name=symbol.name,
                    kind=symbol.kind,
                    signature=symbol.signature,
                    docstring=doc_lines[0][:200] if doc_lines else "",
                    start_line=symbol.start_line,
                    end_line=symbol.end_line,
                )
            )

        for rel_path in sorted(target_paths):
            for ref in self._index.imports_of(rel_path):
                resolved = self._index.resolve_import(
                    rel_path,
                    ref.module,
                    level=ref.level,
                    name=ref.name,
                )
                if not resolved:
                    continue
                for symbol in self._index.symbols(path=resolved):
                    if symbol.kind in ("method", "function"):
                        continue
                    add(symbol)

        for name in task.symbols:
            for symbol in self._index.symbols(name=name):
                add(symbol)

        for keyword in sorted(keywords):
            for symbol in self._index.symbols(query=keyword):
                add(symbol)

        return related[:30]

    def _interfaces(
        self,
        task: TaskSpec,
        related: list[SymbolSnippet],
        omitted: list[str],
    ) -> str:
        lines: list[str] = []
        for item in task.interfaces:
            lines.append(f"- {item}")
        for symbol in related:
            location = f"{symbol.path}:{symbol.start_line}"
            lines.append(f"- {symbol.signature}  [{location}]")
            if symbol.docstring:
                lines.append(f"    {symbol.docstring}")
        return "\n".join(lines)

    # -- conventions -------------------------------------------------------

    def _conventions(
        self,
        task: TaskSpec,
        target_files: list[ContextFile],
        related: list[SymbolSnippet],
        omitted: list[str],
    ) -> str:
        blocks: list[str] = []

        # Always include raw convention files (AGENTS.md, specs.md, etc.)
        # These contain critical rules like "use uv, not pip"
        for name in ("AGENTS.md", "instructions.md", "specs.md"):
            path = self._workspace / name
            if path.is_file():
                text = read_text(path, max_chars=q_config.CONTEXT_MAX_CONVENTION_CHARS)
                blocks.append(f"### {name}\n{text.strip()}")

        # Also include AI-extracted task-specific conventions from the planner
        if task.conventions.strip():
            blocks.append(f"### Task conventions\n{task.conventions.strip()}")

        tags: set[str] = set()
        for context_file in target_files:
            for symbol in self._index.symbols(path=context_file.path):
                tags.update(symbol.tags)
        for symbol in related:
            for indexed in self._index.symbols(path=symbol.path, name=symbol.name):
                tags.update(indexed.tags)

        hints: list[str] = []
        if "fastapi" in tags or "fastapi.route" in tags:
            hints.append("Backend: FastAPI routes; keep request/response Pydantic schemas explicit.")
        if "pydantic" in tags or "pydantic.model" in tags:
            hints.append("Backend: use Pydantic v2 models (`model_dump`, `model_validate`, `ConfigDict`).")
        if "sqlalchemy" in tags or "sqlalchemy.model" in tags:
            hints.append("Database: SQLAlchemy with PostgreSQL; respect model/table naming and migrations.")
        if "celery" in tags or "celery.task" in tags:
            hints.append("Async work: Celery tasks must be idempotent and serializable.")
        if "langgraph" in tags or "langgraph.node" in tags or "langgraph.state" in tags:
            hints.append("Graph code: LangGraph state updates must be explicit and serializable.")
        if "react" in tags or "react.component" in tags:
            hints.append("Frontend: React + TypeScript; prefer function components and typed props.")
        if "react.hook" in tags:
            hints.append("Frontend: hooks are named `useX` and must preserve hook call order.")
        if "tailwind" in tags or "shadcn.ui" in tags:
            hints.append("Frontend UI: use Tailwind utilities and existing shadcn/ui primitives.")
        if "route" in tags:
            hints.append("Routing: keep route definitions and API clients consistent.")
        if "api.client" in tags:
            hints.append("API client: preserve existing request/response types and error handling.")
        if "vite" in tags:
            hints.append("Frontend build: Vite; reuse configured path aliases instead of deep relative paths.")
        if (self._workspace / "alembic.ini").exists() or (self._workspace / "alembic").is_dir():
            hints.append("Migrations: add an Alembic revision when database schema changes.")
        if not hints:
            hints.append("No stack-specific conventions detected; follow the surrounding code style.")

        blocks.append("### Detected stack\n" + "\n".join(f"- {hint}" for hint in hints))
        return "\n\n".join(blocks)

    # -- memory / git / budget helpers ------------------------------------

    def _memory_context(self, task: TaskSpec) -> str:
        if self._memory is None:
            return ""
        try:
            entries = self._memory.for_paths(list(task.editable_files), limit=8)
        except Exception:
            return ""
        if not entries:
            return ""
        return "\n".join(f"- {entry.content}" for entry in entries)

    def _skills_context(
        self,
        task: TaskSpec,
        target_files: list[ContextFile],
        related: list[SymbolSnippet],
        omitted: list[str],
    ) -> str:
        if self._skills is None:
            return ""
        stack_tags: set[str] = set()
        for symbol in related:
            for indexed in self._index.symbols(path=symbol.path, name=symbol.name):
                stack_tags.update(indexed.tags)
        for context_file in target_files:
            for indexed in self._index.symbols(path=context_file.path):
                stack_tags.update(indexed.tags)

        primary_language = ""
        if target_files:
            primary_language = target_files[0].language

        try:
            sections = self._skills.retrieve(
                task,
                stack_tags=stack_tags,
                language=primary_language,
                limit_chars=q_config.CONTEXT_MAX_SKILLS_CHARS * 2,
            )
        except Exception:
            omitted.append("skills index unavailable")
            return ""

        if not sections:
            return ""

        blocks: list[str] = []
        for section in sections:
            source = Path(section.source).name
            tags = ", ".join(section.tags) if section.tags else ""
            header = f"### {source}: {section.title}"
            if tags:
                header += f"  [tags: {tags}]"
            if section.layer:
                header += f"  [layer: {section.layer}]"
            blocks.append(f"{header}\n{section.body}")
        return "\n\n".join(blocks)


    def _git_context(self, task: TaskSpec, omitted: list[str]) -> str:
        if self._git is None or not self._git.is_repo():
            return ""
        try:
            stat = self._git.diff_stat().strip()
            diff = self._git.diff(list(task.files)).strip()
        except Exception:
            omitted.append("git state unavailable")
            return ""
        parts: list[str] = []
        if stat:
            parts.append("### diff --stat\n" + stat)
        if diff:
            parts.append("### working-tree diff (target files)\n" + diff)
        return "\n\n".join(parts)

    @staticmethod
    def _take(text: str, cap: int, label: str, omitted: list[str]) -> str:
        if not text:
            return ""
        if cap <= 0:
            omitted.append(f"{label} omitted (budget exhausted)")
            return ""
        if len(text) <= cap:
            return text
        omitted.append(f"{label} truncated to {cap} chars")
        return text[:cap] + "\n...[truncated]..."
