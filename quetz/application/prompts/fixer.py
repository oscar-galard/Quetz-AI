"""Prompt for the Fixer node — targeted bug fixes, not full regeneration."""
from __future__ import annotations

from quetz.domain.model import Turn

FIXER_SYSTEM_PROMPT = (
    "You are Quetz Fixer. You receive code that FAILED validation and the error.\n"
    "Fix ONLY the specific bug. Do NOT rewrite the entire file.\n\n"
    "Rules:\n"
    "1. Output ONLY valid JSON matching the edit-plan schema.\n"
    "2. Fix ONLY the error described. Keep everything else unchanged.\n"
    "3. Use 'replace' edits with exact 'find' anchors from the supplied code.\n"
    "4. Keep the fix minimal. Do not refactor or add features.\n"
    "5. If the fix is impossible, return status 'blocked' with a reason.\n"
)


def build_fixer_messages(
    code_files: dict[str, str],
    error: str,
    task_prompt: str = "",
) -> list[Turn]:
    """Build a focused fix prompt: code + error + minimal instructions."""
    parts = [
        "## TASK CONTEXT",
        task_prompt or "(no task context)",
        "",
        "## CURRENT CODE",
    ]
    for path, content in code_files.items():
        parts.append(f"### {path}\n```python\n{content}\n```")

    parts.extend([
        "",
        "## VALIDATION ERROR",
        error[:3000],
        "",
        "## INSTRUCTION",
        "Fix the error above. Return an edit-plan JSON with ONLY the fix.",
        "Use op='replace' with exact 'find' from the code above.",
    ])

    return [
        Turn.system(FIXER_SYSTEM_PROMPT),
        Turn.user("\n".join(parts)),
    ]
