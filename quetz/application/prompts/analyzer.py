"""Prompt for the Analyzer node — produce precise edit instructions."""
from __future__ import annotations

from quetz.domain.model import Turn

ANALYZER_SYSTEM_PROMPT = (
    "You are Quetz Analyzer. You receive existing code and an improvement goal.\n"
    "Produce PRECISE, MINIMAL edit instructions — not full file rewrites.\n\n"
    "Rules:\n"
    "1. Output ONLY valid JSON matching the edit-plan schema.\n"
    "2. For existing files: use 'replace' with EXACT 'find' anchors from the code.\n"
    "3. For new content: use 'append' or 'prepend'.\n"
    "4. NEVER rewrite an entire file. Only change what the goal requires.\n"
    "5. Each edit should be ONE logical change (e.g., change a className, add a style).\n"
    "6. Keep find anchors SMALL (2-5 lines) but UNIQUE in the file.\n"
    "7. If the goal is vague, make minimal sensible improvements — not a redesign.\n"
)


def build_analyzer_messages(
    code_files: dict[str, str],
    goal: str,
    conventions: str = "",
) -> list[Turn]:
    """Build an analysis prompt: code + goal + conventions → precise edits."""
    parts = [
        "## IMPROVEMENT GOAL",
        goal,
        "",
        "## CURRENT CODE",
    ]
    for path, content in code_files.items():
        lines = content.split("\n")
        numbered = [f"{i+1:4d} | {line}" for i, line in enumerate(lines)]
        parts.append(f"### {path}\n```\n" + "\n".join(numbered) + "\n```")

    if conventions.strip():
        parts.extend(["", "## CONVENTIONS", conventions])

    parts.extend([
        "",
        "## INSTRUCTION",
        "Analyze the code above and produce PRECISE edit instructions.",
        "Use op='replace' with exact 'find' anchors (copy from the numbered lines,",
        "strip the line numbers). Use op='append' for new content at end of file.",
        "Each edit = one logical change. Do NOT rewrite entire files.",
    ])

    return [
        Turn.system(ANALYZER_SYSTEM_PROMPT),
        Turn.user("\n".join(parts)),
    ]
