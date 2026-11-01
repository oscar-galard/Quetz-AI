"""Markdown skill-file parser.

Skill files live in ``<workspace>/skills/*.md``. Each file has an optional
frontmatter block with file-level tags and layer, then a sequence of ``##``
or ``###`` sections. A section may override the file's tags/layer with a
single ``> tags: …`` / ``> layer: …`` directive immediately below its header.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from quetz.domain.skill import SkillSection


_FM_FENCE = re.compile(r"^---\s*$")
_SECTION = re.compile(r"^(#{2,3})\s+(.+?)\s*$")
_META = re.compile(r"^\s*>\s*(tags|layer)\s*:\s*(.+?)\s*$")


@dataclass(frozen=True, slots=True)
class _Frontmatter:
    skill: str = ""
    layer: str = ""
    tags: tuple[str, ...] = ()


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Return (frontmatter_block, body). Either may be empty."""
    lines = text.splitlines()
    if not lines or not _FM_FENCE.match(lines[0]):
        return "", text
    for end in range(1, len(lines)):
        if _FM_FENCE.match(lines[end]):
            return "\n".join(lines[1:end]), "\n".join(lines[end + 1 :])
    return "", text


def _parse_list(value: str) -> tuple[str, ...]:
    value = value.strip()
    if not value:
        return ()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    items: list[str] = []
    for part in value.split(","):
        part = part.strip().strip('"').strip("'")
        if part:
            items.append(part.lower())
    return tuple(items)


def parse_frontmatter(block: str) -> _Frontmatter:
    skill = ""
    layer = ""
    tags: list[str] = []
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        if key == "skill":
            skill = value.strip().strip('"').strip("'")
        elif key == "layer":
            layer = value.strip().strip('"').strip("'").lower()
        elif key == "tags":
            tags.extend(_parse_list(value))
    return _Frontmatter(skill=skill, layer=layer, tags=tuple(tags))


def _parse_section_meta(body_lines: Iterable[str]) -> tuple[tuple[str, ...], str, list[str]]:
    """Return (section_tags, section_layer, body_lines_after_meta).

    A section's first non-empty lines may declare ``> tags:`` and/or
    ``> layer:`` directives, which override the file-level defaults.
    """
    section_tags: list[str] = []
    section_layer = ""
    rest: list[str] = []
    seen_meta = True
    for line in body_lines:
        if seen_meta:
            stripped = line.strip()
            if not stripped:
                continue
            match = _META.match(line)
            if match:
                if match.group(1) == "tags":
                    section_tags.extend(_parse_list(match.group(2)))
                else:
                    section_layer = match.group(2).lower()
                continue
            seen_meta = False
        rest.append(line)
    return tuple(section_tags), section_layer, rest


def parse_skill_file(path: str | Path, text: str) -> list[SkillSection]:
    """Parse one skill file into zero or more :class:`SkillSection` objects."""
    fm_block, body_text = _split_frontmatter(text)
    frontmatter = parse_frontmatter(fm_block) if fm_block else _Frontmatter()

    lines = body_text.splitlines()
    sections: list[SkillSection] = []
    current_title: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_title, current_lines
        if current_title is None:
            return
        section_tags, section_layer, rest = _parse_section_meta(current_lines)
        tags = section_tags if section_tags else frontmatter.tags
        layer = section_layer or frontmatter.layer
        body = "\n".join(rest).strip()
        if body:
            sections.append(
                SkillSection(
                    source=str(path),
                    title=current_title,
                    body=body,
                    tags=tags,
                    layer=layer,
                )
            )
        current_title = None
        current_lines = []

    for line in lines:
        match = _SECTION.match(line)
        if match:
            flush()
            current_title = match.group(2).strip()
            current_lines = []
        else:
            current_lines.append(line)
    flush()
    return sections
