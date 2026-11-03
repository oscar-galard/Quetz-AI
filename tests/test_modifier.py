import tempfile
import unittest
from pathlib import Path

from quetz.application.ports.llm import LLMResult
from quetz.application.use_cases.modify_task import ModifierHistory, ModifierUseCase
from quetz.domain.change_spec import ChangeSpec, ChangeSpecItem
from quetz.domain.edit import ValidationResult
from quetz.domain.task_spec import TaskSpec
from quetz.infrastructure.fs.editor import AtomicEditor


def _edit_plan_json(edit_file: str, find: str, replace: str):
    import json
    return json.dumps({
        "task_id": "T1",
        "status": "done",
        "summary": "changed",
        "edits": [{"file": edit_file, "op": "replace", "find": find, "replace": replace}],
    })


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
    def validate(self, task, changed_paths, **kwargs):
        return ValidationResult(ok=True)


class TestModifierHistory(unittest.TestCase):
    def test_tracks_applied_and_failed(self):
        h = ModifierHistory()
        h.add_success("a.py", "added gradient")
        h.add_failure("b.py", "anchor not found")
        self.assertEqual(h.applied_count, 1)
        self.assertEqual(h.failed_count, 1)
        self.assertIn("✅ a.py", h.render())
        self.assertIn("❌ b.py", h.render())

    def test_history_is_bounded(self):
        h = ModifierHistory()
        for i in range(20):
            h.add_success(f"f{i}.py", f"change {i}")
        self.assertLessEqual(len(h.entries), 15)


class TestModifier(unittest.TestCase):
    def test_applies_changes_sequentially(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("x = 1\ny = 2\n")

            llm = FakeLLM([
                _edit_plan_json("a.py", "x = 1\n", "x = 10\n"),
                _edit_plan_json("a.py", "y = 2\n", "y = 20\n"),
            ])
            modifier = ModifierUseCase(
                llm=llm, editor=AtomicEditor(tmp), validator=FakeValidator()
            )
            task = TaskSpec(id="T1", title="t", goal="g", files=("a.py",))
            spec = ChangeSpec(
                changes=(
                    ChangeSpecItem(file="a.py", action="replace",
                                   instruction="change x to 10"),
                    ChangeSpecItem(file="a.py", action="replace",
                                   instruction="change y to 20"),
                ),
                summary="update values",
            )
            result = modifier.apply_spec(task, spec)
            self.assertTrue(result.ok)
            self.assertEqual(llm.calls, 2)
            content = (root / "a.py").read_text()
            self.assertIn("x = 10", content)
            self.assertIn("y = 20", content)

    def test_failed_change_does_not_block_others(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("x = 1\n")

            # First edit succeeds, second returns invalid JSON
            llm = FakeLLM([
                _edit_plan_json("a.py", "x = 1\n", "x = 10\n"),
                "not json",
            ])
            modifier = ModifierUseCase(
                llm=llm, editor=AtomicEditor(tmp), validator=FakeValidator()
            )
            task = TaskSpec(id="T1", title="t", goal="g", files=("a.py",))
            spec = ChangeSpec(
                changes=(
                    ChangeSpecItem(file="a.py", action="replace",
                                   instruction="change x to 10"),
                    ChangeSpecItem(file="a.py", action="replace",
                                   instruction="change x to 99"),
                ),
                summary="update",
            )
            result = modifier.apply_spec(task, spec)
            # Partial success: 1 applied, 1 failed
            self.assertFalse(result.ok)
            self.assertIn("1 change(s) failed", result.error)
            # First change is on disk
            content = (root / "a.py").read_text()
            self.assertIn("x = 10", content)

    def test_per_task_history_resets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("x = 1\n")
            llm = FakeLLM([_edit_plan_json("a.py", "x = 1\n", "x = 2\n")])
            modifier = ModifierUseCase(
                llm=llm, editor=AtomicEditor(tmp), validator=FakeValidator()
            )
            task = TaskSpec(id="T1", title="t", goal="g", files=("a.py",))
            spec = ChangeSpec(
                changes=(ChangeSpecItem(file="a.py", action="replace",
                                        instruction="change x"),),
                summary="s",
            )
            modifier.apply_spec(task, spec)
            # Second call should have fresh history
            (root / "b.py").write_text("z = 0\n")
            llm2 = FakeLLM([_edit_plan_json("b.py", "z = 0\n", "z = 1\n")])
            modifier2 = ModifierUseCase(
                llm=llm2, editor=AtomicEditor(tmp), validator=FakeValidator()
            )
            task2 = TaskSpec(id="T2", title="t2", goal="g2", files=("b.py",))
            spec2 = ChangeSpec(
                changes=(ChangeSpecItem(file="b.py", action="replace",
                                        instruction="change z"),),
                summary="s2",
            )
            result = modifier2.apply_spec(task2, spec2)
            self.assertTrue(result.ok)


if __name__ == "__main__":
    unittest.main()
