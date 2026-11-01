import tempfile
import unittest
from pathlib import Path

from quetz.application.use_cases.compile_context import CompileContextUseCase
from quetz.domain.task_spec import TaskSpec
from quetz.infrastructure.index.sqlite_index import SqliteProjectIndex
from quetz.infrastructure.skills.index import FileSkillIndex


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


SKILL_TEXT = """---
skill: fastapi
layer: interface
tags: [python, fastapi, http, api]
---

## Route handler pattern

FastAPI routes delegate to use cases via Depends.

## Error handling

Map domain errors to HTTP at the interface layer.
"""


class TestSkillsIntegration(unittest.TestCase):
    def test_skills_appear_in_bundle_and_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "src/interface/http/newsletter.py", "x = 1\n")
            _write(root, "skills/fastapi.md", SKILL_TEXT)

            index = SqliteProjectIndex(tmp)
            skills = FileSkillIndex(tmp)

            task = TaskSpec(
                id="T1",
                title="Add newsletter route",
                goal="Create a FastAPI route",
                files=("src/interface/http/newsletter.py",),
                layer="interface",
            )
            bundle = CompileContextUseCase(
                index, tmp, skills=skills, token_budget=4000
            ).execute(task)

            self.assertIn("Route handler pattern", bundle.skills)
            self.assertIn("## STACK SKILLS", self._render(bundle))

    @staticmethod
    def _render(bundle) -> str:
        from quetz.application.prompts.executor import render_context_bundle
        return render_context_bundle(bundle)


if __name__ == "__main__":
    unittest.main()
