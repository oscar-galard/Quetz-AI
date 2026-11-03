"""Prompt for the Analyzer node — produce ChangeSpec (what to improve, not how)."""
from __future__ import annotations

import json

from quetz.domain.model import Turn

CHANGE_SPEC_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "changes": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "file": {"type": "string"},
                    "action": {"type": "string", "enum": ["replace", "append", "prepend"]},
                    "locate": {"type": "string"},
                    "instruction": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["file", "action", "instruction"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "changes"],
    "additionalProperties": False,
}

ANALYZER_SYSTEM_PROMPT = (
    "You are Quetz Analyzer. You look at existing code and an improvement goal,\n"
    "then produce a CHANGE SPEC: what to change and why.\n\n"
    "You do NOT write find/replace code. You describe changes.\n"
    "The Executor will write the actual code edits based on your spec.\n\n"
    "Rules:\n"
    "1. Output ONLY valid JSON matching the schema.\n"
    "2. For each change: specify the file, action (replace/append/prepend),\n"
    "   a 'locate' description (which part of the code to find), and an\n"
    "   'instruction' (what to change and why).\n"
    "3. Be PRECISE about locations: quote the exact string or describe the\n"
    "   exact element (e.g., 'the h2 with className text-5xl font-extrabold').\n"
    "4. Keep changes MINIMAL — one logical change per item.\n"
    "5. If the goal is vague, make sensible improvements — not a redesign.\n"
    "6. NEVER include the full file content in 'instruction'.\n"
)


def build_analyzer_messages(
    code_files: dict[str, str],
    goal: str,
    conventions: str = "",
) -> list[Turn]:
    """Build an analysis prompt: code + goal → ChangeSpec."""
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
        "## OUTPUT FORMAT",
        "Return JSON:",
        json.dumps(CHANGE_SPEC_SCHEMA, indent=2),
        "",
        "## EXAMPLE",
        json.dumps(
            {
                "summary": "Add gradient heading and glow to CTA",
                "changes": [
                    {
                        "file": "src/components/Hero.tsx",
                        "action": "replace",
                        "locate": "the h2 element with text-5xl font-extrabold",
                        "instruction": "Wrap the first sentence in a gradient text span: bg-gradient-to-r from-orange-400 to-orange-600 bg-clip-text text-transparent",
                        "content": "",
                    },
                    {
                        "file": "src/index.css",
                        "action": "append",
                        "locate": "",
                        "instruction": "Add a glass card utility class",
                        "content": ".glass { background: rgba(30,41,59,0.6); backdrop-filter: blur(12px); }",
                    },
                ],
            },
            indent=2,
        ),
    ])

    return [
        Turn.system(ANALYZER_SYSTEM_PROMPT),
        Turn.user("\n".join(parts)),
    ]
