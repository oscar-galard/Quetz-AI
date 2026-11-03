"""Prompt for the Modifier node — apply one change at a time with history.

The modifier receives a ChangeSpec and applies changes file-by-file.
Each call produces exactly ONE edit. History tracks what's done and what failed.
"""
from __future__ import annotations

import json

from quetz.domain.model import Turn

MODIFIER_SYSTEM_PROMPT = (
    "You are Quetz Modifier. You apply ONE targeted change to existing code.\n"
    "You receive a change instruction and the current file content.\n"
    "Return ONE edit operation (replace/append/prepend).\n\n"
    "Rules:\n"
    "1. Output ONLY valid JSON matching the edit-plan schema.\n"
    "2. Return EXACTLY ONE edit — not multiple.\n"
    "3. For 'replace': copy the 'find' anchor EXACTLY from the numbered lines below.\n"
    "   Strip the line-number prefixes ('  1 | ') before copying.\n"
    "   Preserve ALL whitespace and line breaks exactly.\n"
    "4. For 'append'/'prepend': use 'content' to add new code.\n"
    "5. Keep the change MINIMAL — do not refactor or add extra.\n"
    "6. If the change is impossible, return status='blocked' with a reason.\n"
    "7. Check the PROGRESS section — do not repeat a change that already succeeded.\n"
)


def build_modifier_messages(
    *,
    change_instruction: str,
    locate_hint: str,
    file_path: str,
    file_content: str,
    progress: str = "",
    conventions: str = "",
) -> list[Turn]:
    """Build a modifier prompt: one change + current file + progress."""
    lines = file_content.split("\n")
    numbered = [f"{i+1:4d} | {line}" for i, line in enumerate(lines)]

    parts = [
        "## CHANGE TO APPLY",
        f"File: {file_path}",
        f"Where: {locate_hint or 'the relevant block'}",
        f"What: {change_instruction}",
        "",
        "## CURRENT FILE (numbered)",
        f"### {file_path}\n```\n" + "\n".join(numbered) + "\n```",
    ]

    if progress.strip():
        parts.extend(["", "## PROGRESS (already applied / failed)", progress.strip()])

    if conventions.strip():
        parts.extend(["", "## CONVENTIONS", conventions])

    parts.extend([
        "",
        "## OUTPUT",
        "Return ONE edit as JSON: {task_id, status, summary, edits: [one edit]}",
        "For replace: strip line numbers from 'find'. Example:",
        json.dumps(
            {
                "task_id": "T1",
                "status": "done",
                "summary": "Added gradient to heading",
                "edits": [
                    {
                        "file": "src/components/Hero.tsx",
                        "op": "replace",
                        "find": "className=\"text-5xl font-extrabold\"",
                        "replace": "className=\"text-5xl font-extrabold bg-gradient-to-r from-orange-400 to-orange-600 bg-clip-text text-transparent\"",
                    }
                ],
            },
            indent=2,
        ),
    ])

    return [
        Turn.system(MODIFIER_SYSTEM_PROMPT),
        Turn.user("\n".join(parts)),
    ]
