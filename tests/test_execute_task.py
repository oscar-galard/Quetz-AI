import json
import tempfile
import unittest
from pathlib import Path

from quetz.application.ports.llm import LLMResult
from quetz.application.use_cases.execute_task import ExecuteTaskUseCase
from quetz.domain.context import ContextBundle
from quetz.domain.edit import CommandResult, ValidationResult
from quetz.domain.task_spec import TaskSpec
from quetz.infrastructure.fs.editor import AtomicEditor


def _bundle(task: TaskSpec) -> ContextBundle:
    return ContextBundle(
        task_id=task.id,
        title=task.title,
        goal=task.goal,
        target_files=(),
        related_symbols=(),
        interfaces="",
        conventions="",
        tree="",
        git_diff="",
        acceptance=task.acceptance,
        approx_tokens=10,
    )


def _plan(status="done", edits=None, reason=""):
    return json.dumps(
        {
            "task_id": "T1",
            "status": status,
            "summary": "did it",
            "reason": reason,
            "edits": edits or [],
        }
    )


class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        return LLMResult(content=self.responses.pop(0))

    def stream(self, messages, **kwargs):
        raise NotImplementedError


class FakeValidator:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def validate(self, task, changed_paths, **kwargs):
        self.calls += 1
        return self.results.pop(0)


class TestExecuteTask(unittest.TestCase):
    def test_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = TaskSpec(id="T1", title="t", goal="g", allowed_new_files=("a.py",))
            llm = FakeLLM([_plan(edits=[{"file": "a.py", "op": "create", "content": "x = 1\n"}])])
            validator = FakeValidator([ValidationResult(ok=True)])
            uc = ExecuteTaskUseCase(
                llm=llm,
                editor=AtomicEditor(tmp),
                validator=validator,
            )
            result = uc.execute(task, _bundle(task))
            self.assertTrue(result.ok, result.error)
            self.assertEqual(result.status, "done")
            self.assertEqual(result.attempts, 1)
            self.assertEqual((root / "a.py").read_text(), "x = 1\n")

    def test_retries_after_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = TaskSpec(id="T1", title="t", goal="g", allowed_new_files=("a.py",))
            llm = FakeLLM(
                [
                    "not json",
                    _plan(edits=[{"file": "a.py", "op": "create", "content": "x\n"}]),
                ]
            )
            uc = ExecuteTaskUseCase(
                llm=llm,
                editor=AtomicEditor(tmp),
                validator=FakeValidator([ValidationResult(ok=True)]),
            )
            result = uc.execute(task, _bundle(task))
            self.assertTrue(result.ok, result.error)
            self.assertEqual(result.attempts, 2)

    def test_blocked_returns_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = TaskSpec(id="T1", title="t", goal="g", allowed_new_files=("a.py",))
            llm = FakeLLM([_plan(status="blocked", reason="missing interface")])
            uc = ExecuteTaskUseCase(
                llm=llm,
                editor=AtomicEditor(tmp),
                validator=FakeValidator([]),
            )
            result = uc.execute(task, _bundle(task))
            self.assertFalse(result.ok)
            self.assertEqual(result.status, "blocked")
            self.assertIn("missing interface", result.error)
            self.assertFalse((Path(tmp) / "a.py").exists())

    def test_validation_failure_reverts_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = TaskSpec(id="T1", title="t", goal="g", allowed_new_files=("a.py",))

            class RecordingValidator:
                def __init__(self):
                    self.calls = 0
                    self.saw_file = False

                def validate(self, task, changed_paths, **kwargs):
                    self.calls += 1
                    self.saw_file = (root / "a.py").exists()
                    if self.calls == 1:
                        return ValidationResult(
                            ok=False,
                            results=(CommandResult("pytest", 1, stderr="boom"),),
                        )
                    return ValidationResult(ok=True)

            validator = RecordingValidator()
            llm = FakeLLM(
                [
                    _plan(edits=[{"file": "a.py", "op": "create", "content": "x\n"}]),
                    _plan(status="blocked", reason="gave up"),
                ]
            )
            uc = ExecuteTaskUseCase(
                llm=llm,
                editor=AtomicEditor(tmp),
                validator=validator,
            )
            result = uc.execute(task, _bundle(task))
            self.assertFalse(result.ok)
            self.assertEqual(result.status, "blocked")
            self.assertEqual(validator.calls, 1)
            self.assertTrue(validator.saw_file)
            # Code STAYS on disk for manual editing (no auto-revert)
            self.assertTrue((root / "a.py").exists())


if __name__ == "__main__":
    unittest.main()
