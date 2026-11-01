"""Dynamic skill index: file-backed, task-aware section retrieval."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from quetz.domain.skill import SkillSection
from quetz.domain.task_spec import TaskSpec
from quetz.infrastructure.fs.paths import workspace_root
from quetz.infrastructure.skills.parser import parse_skill_file


_KEYWORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def _keywords_from(task: TaskSpec) -> set[str]:
    sources = (task.title, task.goal, task.notes, *task.symbols, *task.interfaces)
    return {word.lower() for word in _KEYWORD_RE.findall(" ".join(sources))}


def _score(
    section: SkillSection,
    *,
    task_keywords: set[str],
    stack_tags: set[str],
    language_tag: str,
    task_layer: str,
) -> float:
    section_tags = {tag.lower() for tag in section.tags}
    candidate_tags = stack_tags | ({language_tag} if language_tag else set())

    overlap = len(section_tags & candidate_tags)
    score = overlap * 10.0

    body_lower = section.body.lower()
    hits = 0
    for keyword in task_keywords:
        count = body_lower.count(keyword)
        if count:
            hits += min(count, 5)
    score += hits

    if task_layer:
        if section.layer == task_layer:
            score += 25
        elif section.layer and section.layer != task_layer:
            score -= 10

    if section.title:
        title_lower = section.title.lower()
        for keyword in task_keywords:
            if keyword in title_lower:
                score += 6
    return score


class FileSkillIndex:
    """Walks ``<workspace>/skills/*.md`` and exposes task-aware retrieval."""

    def __init__(self, workspace: str, *, skills_dir: str = "skills") -> None:
        self._root = workspace_root(workspace)
        self._skills_dir = self._root / skills_dir
        self._sections: list[SkillSection] = []
        self._built = False

    @property
    def sections(self) -> list[SkillSection]:
        return list(self._sections)

    def ensure_built(self) -> None:
        if not self._built:
            self.build()

    def build(self) -> int:
        self._sections = []
        self._built = True
        if not self._skills_dir.is_dir():
            return 0
        for markdown in sorted(self._skills_dir.rglob("*.md")):
            try:
                text = markdown.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for section in parse_skill_file(markdown, text):
                self._sections.append(section)
        return len(self._sections)

    def retrieve(
        self,
        task: TaskSpec,
        *,
        stack_tags: Iterable[str],
        language: str = "",
        limit_chars: int,
    ) -> list[SkillSection]:
        if not self._sections or limit_chars <= 0:
            return []

        keywords = _keywords_from(task)
        stack_tag_set = {tag.lower() for tag in stack_tags}
        language_tag = language.lower()

        scored = [
            (
                _score(
                    section,
                    task_keywords=keywords,
                    stack_tags=stack_tag_set,
                    language_tag=language_tag,
                    task_layer=(task.layer or ""),
                ),
                index,
                section,
            )
            for index, section in enumerate(self._sections)
        ]
        scored.sort(key=lambda item: (item[0], -item[1]), reverse=True)

        chosen: list[SkillSection] = []
        used = 0
        for score, _index, section in scored:
            if score <= 0:
                break
            size = section.size
            if used + size > limit_chars and chosen:
                break
            chosen.append(section)
            used += size
        return chosen
