"""Prove the executor is stateless: no history accumulates between calls."""
import json
import tempfile
import unittest
from pathlib import Path

from quetz.application.ports.llm import LLMResult
from quetz.application.use_cases.execute_task import ExecuteTaskUseCase
from quetz.domain.context import ContextBundle
from quetz.domain.edit import ValidationResult
from quetz.domain.task_spec import TaskSpec
from quetz.infrastructure.fs.editor import AtomicEditor


class RecordingLLM:
    """Records every call's message count to prove no history accumulates."""

    def __init__(self):
        self.calls = []
        self.responses = []

    def invoke(self, messages):
        self.calls.append(len(messages))
        return LLMResult(content=self.responses.pop(0))

    def stream(self, messages, **kwargs):
        raise NotImplementedError


class StaticValidator:
    def validate(self, task, changed_paths):
        return ValidationResult(ok=True)


def _bundle(task: TaskSpec) -> ContextBundle:
    return ContextBundle(
        task_id=task.id,
        title=task.title,
        goal=task.goal,
        prompt=task.prompt,
        target_files=(),
        related_symbols=(),
        interfaces="",
        conventions="",
        tree="",
        git_diff="",
        acceptance=task.acceptance,
        approx_tokens=10,
    )


def _plan(content="x = 1\n", filename="a.py"):
    return json.dumps({
        "task_id": "T1",
        "status": "done",
        "summary": "created",
        "edits": [{"file": filename, "op": "create", "content": content}],
    })


class TestStateless(unittest.TestCase):
    def test_no_history_accumulates_between_tasks(self):
        """Two sequential tasks must each see exactly 2 messages (system + user)."""
        with tempfile.TemporaryDirectory() as tmp:
            llm = RecordingLLM()
            llm.responses = [_plan("x = 1\n", "a.py"), _plan("y = 2\n", "b.py")]
            uc = ExecuteTaskUseCase(
                llm=llm,
                editor=AtomicEditor(tmp),
                validator=StaticValidator(),
            )

            task1 = TaskSpec(id="T1", title="Create a.py", goal="Create a.py", allowed_new_files=("a.py",))
            task2 = TaskSpec(id="T2", title="Create b.py", goal="Create b.py", allowed_new_files=("b.py",))

            r1 = uc.execute(task1, _bundle(task1))
            r2 = uc.execute(task2, _bundle(task2))

            self.assertTrue(r1.ok)
            self.assertTrue(r2.ok)
            # Each call must see exactly 2 messages: system + user
            self.assertEqual(llm.calls, [2, 2], f"History leaked! Message counts: {llm.calls}")

    def test_retry_does_not_accumulate_history(self):
        """Retries within a task also see exactly 2 messages each."""
        with tempfile.TemporaryDirectory() as tmp:
            llm = RecordingLLM()
            llm.responses = ["not json", _plan("x = 1\n")]
            uc = ExecuteTaskUseCase(
                llm=llm,
                editor=AtomicEditor(tmp),
                validator=StaticValidator(),
            )

            task = TaskSpec(id="T1", title="Create a.py", goal="Create a.py", allowed_new_files=("a.py",))
            result = uc.execute(task, _bundle(task))

            self.assertTrue(result.ok)
            self.assertEqual(llm.calls, [2, 2], f"Retry leaked history! Counts: {llm.calls}")


if __name__ == "__main__":
    unittest.main()
