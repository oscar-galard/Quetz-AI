import json
import tempfile
import unittest
from pathlib import Path

from quetz.application.ports.llm import LLMResult
from quetz.application.prompts.planner import build_planner_messages
from quetz.application.use_cases.plan_project import PlanProjectUseCase
from quetz.domain.exceptions import PlanError


class FakeLLM:
    def __init__(self, content):
        self.content = content
        self.messages = None

    def invoke(self, messages):
        self.messages = messages
        return LLMResult(content=self.content)

    def stream(self, messages, **kwargs):
        raise NotImplementedError


def _plan_json():
    return json.dumps(
        {
            "schema_version": 1,
            "project": "demo",
            "tasks": [
                {
                    "id": "T1",
                    "title": "Add health route",
                    "goal": "Return ok.",
                    "files": ["app.py"],
                    "acceptance": [{"command": "python -c 'pass'"}],
                    "layer": "interface",
                },
                {
                    "id": "T2",
                    "title": "Add test",
                    "goal": "Cover the route.",
                    "files": ["test_app.py"],
                    "acceptance": [{"command": "python -m pytest -q"}],
                    "depends_on": ["T1"],
                    "layer": "application",
                },
            ],
        }
    )


class TestPlanProject(unittest.TestCase):
    def test_builds_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text("x = 1\n", encoding="utf-8")
            (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
            llm = FakeLLM(_plan_json())
            plan = PlanProjectUseCase(llm=llm, workspace=tmp).execute("add health")
            self.assertEqual(plan.project, "demo")
            self.assertEqual(len(plan.tasks), 2)
            self.assertEqual(plan.tasks[1].depends_on, ("T1",))
            user_prompt = llm.messages[1].content
            self.assertIn("add health", user_prompt)
            self.assertIn("app.py", user_prompt)
            self.assertIn("pyproject.toml", user_prompt)

    def test_rejects_empty_goal(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(PlanError):
                PlanProjectUseCase(llm=FakeLLM(_plan_json()), workspace=tmp).execute("  ")

    def test_rejects_invalid_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(PlanError):
                PlanProjectUseCase(
                    llm=FakeLLM('{"project": "demo", "tasks": []}'),
                    workspace=tmp,
                ).execute("goal")

    def test_prompt_contains_schema(self):
        messages = build_planner_messages("goal", tree="app.py")
        self.assertIn("OUTPUT JSON SCHEMA", messages[1].content)
        self.assertIn("Quetz Planner", messages[0].content)


if __name__ == "__main__":
    unittest.main()
