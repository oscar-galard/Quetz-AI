"""Prompt templates for the stateless local executor.

The executor gets exactly one task and one context bundle. It never receives a
conversation transcript: retries rebuild the same prompt with only a compact
validator error appended.
"""
from __future__ import annotations

import json

from quetz.domain.context import ContextBundle, ContextFile
from quetz.domain.model import Turn

EDIT_PLAN_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "task_id": {"type": "string"},
        "status": {"type": "string", "enum": ["done", "blocked"]},
        "summary": {"type": "string"},
        "reason": {"type": "string"},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "edits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "file": {"type": "string"},
                    "op": {"type": "string", "enum": ["create", "replace", "append", "prepend"]},
                    "content": {"type": "string"},
                    "find": {"type": "string"},
                    "replace": {"type": "string"},
                },
                "required": ["file", "op"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["task_id", "status", "edits"],
    "additionalProperties": False,
}

EXECUTOR_SYSTEM_PROMPT = (
    "You are Quetz Executor, a deterministic code-editing engine.\n"
    "You receive ONE self-contained task and return ONE JSON object.\n\n"
    "Hard rules:\n"
    "1. Output ONLY valid JSON matching the schema. No markdown, no prose, no code fences.\n"
    "2. Modify ONLY files listed under ALLOWED FILES.\n"
    "3. Edit operations: 'create' (new file), 'replace' (find+replace existing text),\n"
    "   'append' (add content to END of existing file), 'prepend' (add to START).\n"
    "   Use 'append' when adding new CSS rules, functions, or imports — NOT 'replace'.\n"
    "4. For 'replace', 'find' must be an exact, unique block copied from the\n"
    "   supplied file text. Preserve indentation and surrounding lines exactly.\n"
    "5. Files are shown with line numbers (e.g., '  1 | code'). For 'find', copy\n"
    "   ONLY the code text AFTER the line number marker (the ' | ' part). Never\n"
    "   include line numbers in 'find'. Preserve EXACT whitespace and line breaks.\n"
    "5. Do not refactor unrelated code, add dependencies, or invent APIs.\n"
    "6. If the task is impossible with the supplied context, return status 'blocked'\n"
    "   with a specific reason. Do not guess.\n"
    "7. Use 'create' only for files marked NEW FILE.\n"
    "8. CRITICAL: Before ANY import, check the INTERFACES section to see what\n"
    "   names are ACTUALLY exported. NEVER invent import names. If you need a\n"
    "   class/function and it's not shown in INTERFACES, define it in the same\n"
    "   file or create the file explicitly in this edit plan.\n"
    "   WRONG: from app.usecases import ProductRepo  (if not in INTERFACES)\n"
    "   RIGHT: from app.usecases import <exact name from INTERFACES>\n\n"
    "Code style — minimal, not perfect:\n"
    "8. Write the smallest change that works. No abstraction, no boilerplate,\n"
    "   no 'for later' code. The user will improve it manually.\n"
    "9. No tests, no docstrings, no type annotations beyond what's required.\n"
    "   No error handling unless the task explicitly asks for it.\n"
    "10. Keep it simple enough to read in Emacs. Plain code, not framework magic.\n"
    "11. Comment only if the 'why' is non-obvious. One line max.\n"
    "12. React 17+ does NOT need 'import React from \"react\"' unless you use\n"
    "   React.something explicitly. In .tsx files, just import hooks: 'import { useState } from \"react\"'.\n"
    "   An unused import causes a build error. NEVER import React if you don't use it.\n"
)

_EXAMPLE = {
    "task_id": "T1",
    "status": "done",
    "summary": "Added a typed health endpoint.",
    "assumptions": [],
    "edits": [
        {
            "file": "backend/app/api/health.py",
            "op": "create",
            "content": "from fastapi import APIRouter\n\nrouter = APIRouter()\n\n\n@router.get('/health')\ndef health() -> dict[str, str]:\n    return {'status': 'ok'}\n",
        },
        {
            "file": "backend/app/main.py",
            "op": "replace",
            "find": "app = FastAPI()\n",
            "replace": "app = FastAPI()\napp.include_router(health.router)\n",
        },
    ],
}


def _fence_language(language: str) -> str:
    return {
        "python": "python",
        "typescript": "ts",
        "tsx": "tsx",
        "javascript": "js",
        "jsx": "jsx",
        "json": "json",
        "sql": "sql",
    }.get(language, "")


def _render_file(context_file: ContextFile) -> str:
    if context_file.is_new:
        return f"### {context_file.path} (NEW FILE - use op=create)"
    label = f"### {context_file.path} (existing — use op=append or op=replace"
    if context_file.end_line:
        label += f", lines {context_file.start_line}-{context_file.end_line}"
    if context_file.truncated:
        label += ", excerpt"
    label += ")"
    language = _fence_language(context_file.language)

    # Add line numbers so the executor can copy exact text for find anchors
    lines = context_file.content.rstrip().split("\n")
    numbered = []
    for i, line in enumerate(lines):
        numbered.append(f"{context_file.start_line + i:4d} | {line}")

    return f"{label}\n```{language}\n" + "\n".join(numbered) + "\n```"


def render_context_bundle(bundle: ContextBundle) -> str:
    instruction = bundle.prompt or bundle.goal
    sections: list[str] = [
        "## INSTRUCTION",
        instruction,
        "",
        f"task: {bundle.task_id} — {bundle.title}",
        "",
        "## ALLOWED FILES",
        "\n\n".join(_render_file(f) for f in bundle.target_files) or "(none)",
    ]

    if bundle.interfaces.strip():
        sections.extend(["", "## INTERFACES YOU MAY RELY ON", bundle.interfaces.strip()])
    if bundle.conventions.strip():
        sections.extend(["", "## PROJECT CONVENTIONS", bundle.conventions.strip()])
    if bundle.skills.strip():
        sections.extend(["", "## STACK SKILLS", bundle.skills.strip()])
    if bundle.memory.strip():
        sections.extend(["", "## PROJECT MEMORY", bundle.memory.strip()])
    if bundle.git_diff.strip():
        sections.extend(["", "## CURRENT GIT STATE", bundle.git_diff.strip()])
    if bundle.acceptance:
        lines = ["", "## ACCEPTANCE"]
        for criterion in bundle.acceptance:
            lines.append(
                f"- command: {criterion.command} (expect exit {criterion.expect_exit})"
            )
        sections.extend(lines)
    if bundle.omitted:
        sections.extend(
            [
                "",
                "## CONTEXT NOTES",
                *[f"- {note}" for note in bundle.omitted],
            ]
        )
    if bundle.tree.strip():
        sections.extend(["", "## WORKSPACE TREE", bundle.tree.strip()])
    return "\n".join(sections).rstrip()


def build_executor_messages(bundle: ContextBundle, prior_error: str = "") -> list[Turn]:
    user_parts = [render_context_bundle(bundle)]
    if prior_error.strip():
        user_parts.extend(
            [
                "",
                "## PREVIOUS ATTEMPT FAILED",
                prior_error.strip()[:4000],
                "Return a corrected JSON object. Do not repeat the same failed edit.",
            ]
        )
    user_parts.extend(
        [
            "",
            "## OUTPUT JSON SCHEMA",
            json.dumps(EDIT_PLAN_SCHEMA, indent=2),
            "",
            "## EXAMPLE",
            json.dumps(_EXAMPLE, indent=2),
        ]
    )
    return [
        Turn.system(EXECUTOR_SYSTEM_PROMPT),
        Turn.user("\n".join(user_parts)),
    ]
