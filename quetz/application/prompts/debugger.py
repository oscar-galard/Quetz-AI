"""Prompt for the Debugger node — analyze errors before fixing."""
from __future__ import annotations

from quetz.domain.model import Turn

DEBUGGER_SYSTEM_PROMPT = (
    "You are Quetz Debugger. You receive code that FAILED validation and the error.\n"
    "Analyze the root cause and produce a clear hypothesis + fix strategy.\n\n"
    "Rules:\n"
    "1. Output ONLY valid JSON. No markdown, no prose.\n"
    "2. Analyze the error trace/log carefully.\n"
    "3. Identify the ROOT CAUSE (not just the symptom).\n"
    "4. Suggest the MINIMAL fix strategy.\n"
    "5. Specify exactly which file(s) need changes and what type of change.\n"
)


def build_debugger_messages(
    code_files: dict[str, str],
    error: str,
    task_prompt: str = "",
) -> list[Turn]:
    """Build a debug prompt: code + error + task context."""
    parts = [
        "## TASK CONTEXT",
        task_prompt or "(no task context)",
        "",
        "## CURRENT CODE",
    ]
    for path, content in code_files.items():
        parts.append(f"### {path}\n```\n{content}\n```")

    parts.extend([
        "",
        "## VALIDATION ERROR",
        error[:3000],
        "",
        "## OUTPUT FORMAT",
        "Return JSON: {",
        '  "root_cause": "one sentence explaining the real problem",',
        '  "fix_strategy": "what needs to change and why",',
        '  "files_to_fix": ["path/to/file.py"],',
        '  "change_type": "append|replace|create|prepend",',
        '  "confidence": "high|medium|low"',
        "}",
    ])

    return [
        Turn.system(DEBUGGER_SYSTEM_PROMPT),
        Turn.user("\n".join(parts)),
    ]
