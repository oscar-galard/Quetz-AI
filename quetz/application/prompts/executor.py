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
    "Rules:\n"
    "1. Output ONLY valid JSON matching the schema. No markdown, no prose.\n"
    "2. Modify ONLY files listed under ALLOWED FILES.\n"
    "3. Edit ops: 'create' (new file), 'replace' (find+replace), 'append' (add to\n"
    "   END), 'prepend' (add to START). Use 'append' to add new code — NOT 'replace'.\n"
    "4. For 'replace', 'find' must be an exact unique block from the supplied text.\n"
    "5. Files show line numbers ('  1 | code'). Copy ONLY text AFTER ' | '.\n"
    "6. If impossible, return status 'blocked' with a reason. Do not guess.\n"
    "7. Use 'create' only for files marked NEW FILE.\n"
    "8. Only import from files visible in PROJECT TREE, ALLOWED FILES, or INTERFACES.\n"
    "   NEVER invent import names or paths. NO libraries unless in the tree.\n\n"
    "Follow the PROJECT CONVENTIONS and STACK SKILLS sections for code style,\n"
    "framework patterns, and project-specific rules.\n"
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
    ]

    if bundle.improvement_spec.strip():
        sections.extend([
            "",
            "## CHANGE SPEC (follow these precisely)",
            bundle.improvement_spec.strip(),
            "",
            "For each change above: use 'replace' with an exact 'find' anchor",
            "copied from the numbered file text below. Strip the line-number",
            "prefixes (e.g., '  1 | ') before copying. Each change = one edit.",
        ])

    sections.extend([
        "",
        "## ALLOWED FILES",
        "\n\n".join(_render_file(f) for f in bundle.target_files) or "(none)",
    ])

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
