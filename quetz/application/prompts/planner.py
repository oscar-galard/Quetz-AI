"""Planner prompt and schema.

The planner is the only model that sees the whole project. It decomposes a
goal into small, vertically sliced tasks that a stateless local executor can
complete using only its compiled context bundle.
"""
from __future__ import annotations

import json

from quetz.domain.model import Turn

PLAN_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "schema_version": {"type": "integer"},
        "project": {"type": "string"},
        "questions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Clarifying questions if the goal is ambiguous. Leave empty if clear.",
        },
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "goal": {"type": "string"},
                    "prompt": {"type": "string"},
                    "files": {"type": "array", "items": {"type": "string"}},
                    "allowed_new_files": {"type": "array", "items": {"type": "string"}},
                    "symbols": {"type": "array", "items": {"type": "string"}},
                    "interfaces": {"type": "array", "items": {"type": "string"}},
                    "acceptance": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "command": {"type": "string"},
                                "expect_exit": {"type": "integer"},
                                "timeout": {"type": "integer"},
                            },
                            "required": ["command"],
                            "additionalProperties": False,
                        },
                    },
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                    "max_attempts": {"type": "integer"},
                    "notes": {"type": "string"},
                    "layer": {
                        "type": "string",
                        "enum": ["domain", "application", "interface", "infrastructure"],
                    },
                    "setup_commands": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "conventions": {"type": "string"},
                },
                "required": ["id", "title", "goal", "files", "acceptance", "layer"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["schema_version", "project"],
    "additionalProperties": False,
}

PLANNER_SYSTEM_PROMPT = (
    "You are Quetz Planner, a senior software architect.\n"
    "Decompose the user's goal into small, vertically sliced tasks for a\n"
    "STATELESS local executor. The executor sees ONLY the files and symbols\n"
    "listed in each task, so every task must be self-contained.\n\n"
    "Hard rules:\n"
    "1. Output ONLY valid JSON matching the schema. No markdown, no prose.\n"
    "2. Each task must leave the repository runnable and testable.\n"
    "3. Prefer 3-8 tasks. Keep each task focused on one behavior.\n"
    "4. Write a 'prompt' field for EVERY task: a clear, self-contained instruction\n"
    "   the executor will receive. State what to build, what to import/reuse, and\n"
    "   what the output should look like. The executor starts from zero — no\n"
    "   conversation history. Be specific but concise (3-6 sentences).\n"
    "5. 'files' lists existing files the executor may edit. 'allowed_new_files'\n"
    "   lists files it may create. Never invent paths that cannot be inferred\n"
    "   from the project tree.\n"
    "6. Every task needs at least one real acceptance command from the project\n"
    "   (pytest, tsc, npm test, ruff, a small python -c probe, etc.). Do not\n"
    "   invent a test runner the project does not have.\n"
    "7. Put shared contracts (schemas, types, interfaces) in earlier tasks so\n"
    "   later tasks can depend on them. Use 'depends_on' for ordering.\n"
    "8. Separate backend and frontend vertical slices. Do not mix frameworks\n"
    "   in one task unless the slice genuinely spans both.\n"
    "9. Include migrations or contract updates explicitly when data shapes\n"
    "   change.\n"
    "10. Tag EVERY task with one Clean Architecture layer so the executor can\n"
    "   pull focused domain skills:\n"
    "     - domain        : entities, value objects, invariants (no framework).\n"
    "     - application   : use cases, orchestrators, DTOs. Ports only.\n"
    "     - interface     : HTTP routes, CLI, message consumers. Adapters IN.\n"
    "     - infrastructure: DB adapters, external clients, Celery tasks, I/O.\n"
    "   One task = one layer. Never mix layers in a single task.\n"
    "11. Use 'setup_commands' for scaffolding commands that must run BEFORE\n"
    "   code generation. Use `uv add package` for Python deps (NEVER `pip install`\n"
    "   or `uv install` — those are wrong). Use `npm create vite@latest` for JS.\n"
    "   Examples: 'uv init --package --name my-app', 'uv add fastapi uvicorn pydantic',\n"
    "   'npm create vite@latest frontend -- --template react-ts'. Keep them minimal.\n"
    "   Setup commands run in the workspace root. Do NOT include test commands\n"
    "   here — use 'acceptance' for those.\n"
    "12. If the goal is ambiguous or missing critical details (database choice,\n"
    "   auth method, API style, etc.), add 1-3 clarifying questions to 'questions'.\n"
    "   Do NOT create tasks until questions are answered. If the goal is clear,\n"
    "   leave 'questions' empty and create tasks directly.\n"
    "13. Write a 'conventions' field for EVERY task: extract ONLY the rules from\n"
    "   AGENTS.md / instructions.md / specs.md that apply to THIS task. Quote them\n"
    "   briefly (1-5 lines). If no conventions apply, use empty string. Do not\n"
    "   include the whole file — only what's relevant to this specific task.\n"
)

_EXAMPLE = {
    "schema_version": 1,
    "project": "quetz-demo",
    "tasks": [
        {
            "id": "T1",
            "title": "Define Subscriber entity",
            "goal": "Pure domain entity with email invariant.",
            "prompt": "Create a frozen dataclass `Subscriber` in `src/domain/subscriber.py` with an `email: str` field. Enforce a valid email format in `__post_init__` (must contain @ and a dot in the domain). Raise ValueError on invalid emails. No framework imports — pure Python only.",
            "files": ["src/domain/subscriber.py"],
            "allowed_new_files": [],
            "symbols": [],
            "interfaces": [],
            "acceptance": [{"command": "pytest -q tests/domain"}],
            "depends_on": [],
            "max_attempts": 2,
            "notes": "",
            "layer": "domain",
            "conventions": "Use frozen dataclasses. No framework imports in domain layer.",
        },
        {
            "id": "T2",
            "title": "SubscribeToNewsletterUseCase",
            "goal": "Application use case with SubscriberRepository port.",
            "prompt": "Create `SubscribeToNewsletterUseCase` in `src/application/subscribe.py`. Define a `SubscriberRepository` Protocol with `save(subscriber) -> None`. The use case takes the repository in its constructor and exposes `execute(email: str) -> SubscribeResponse`. Return a typed response with `subscriber_id: str` and `status: str` (always 'confirmed'). Import `Subscriber` from the domain layer.",
            "files": ["src/application/subscribe.py"],
            "allowed_new_files": [],
            "symbols": [],
            "interfaces": [],
            "acceptance": [{"command": "pytest -q tests/application"}],
            "depends_on": ["T1"],
            "max_attempts": 2,
            "notes": "",
            "layer": "application",
            "conventions": "Use Protocol for ports. Inject dependencies via constructor. Return typed responses.",
        },
        {
            "id": "T3",
            "title": "FastAPI route with Pydantic payload",
            "goal": "POST /newsletter with strict schema validation.",
            "prompt": "Create a FastAPI router in `src/interface/http/newsletter.py` with a POST /newsletter endpoint. Define `SubscribeRequest(BaseModel)` with `email: EmailStr` and `extra='forbid'`. Define `SubscribeResponse(BaseModel)` with `subscriber_id` and `status`. Wire the router into `src/main.py`. The handler calls `SubscribeToNewsletterUseCase.execute()` via dependency injection.",
            "files": ["src/interface/http/newsletter.py"],
            "allowed_new_files": [],
            "symbols": [],
            "interfaces": [],
            "acceptance": [{"command": "pytest -q tests/interface"}],
            "depends_on": ["T2"],
            "max_attempts": 2,
            "notes": "",
            "layer": "interface",
            "conventions": "Use Pydantic v2 BaseModel with extra=forbid. Handlers delegate to use cases. Declare status_code explicitly.",
        },
    ],
}


def build_planner_messages(
    goal: str,
    *,
    tree: str,
    conventions: str = "",
    memory: str = "",
) -> list[Turn]:
    user_parts = [
        "## GOAL",
        goal.strip(),
        "",
        "## PROJECT TREE",
        tree.strip() or "(empty workspace)",
    ]
    if conventions.strip():
        user_parts.extend(["", "## PROJECT CONVENTIONS", conventions.strip()])
    if memory.strip():
        user_parts.extend(["", "## PROJECT MEMORY", memory.strip()[:4000]])
    user_parts.extend(
        [
            "",
            "## OUTPUT JSON SCHEMA",
            json.dumps(PLAN_SCHEMA, indent=2),
            "",
            "## EXAMPLE",
            json.dumps(_EXAMPLE, indent=2),
            "",
            "Return the plan JSON now.",
        ]
    )
    return [
        Turn.system(PLANNER_SYSTEM_PROMPT),
        Turn.user("\n".join(user_parts)),
    ]
