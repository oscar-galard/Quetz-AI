import sys
import tempfile
import unittest
from pathlib import Path

from quetz.domain.task_spec import AcceptanceCriterion, TaskSpec
from quetz.infrastructure.validation.command_validator import CommandValidator
from quetz.infrastructure.validation.syntax import check_syntax


class TestSyntax(unittest.TestCase):
    def test_python(self):
        self.assertIsNone(check_syntax("a.py", "x = 1\n"))
        self.assertIn("a.py", check_syntax("a.py", "def broken(:\n"))

    def test_typescript_and_tsx(self):
        self.assertIsNone(check_syntax("a.ts", "export const x: number = 1;\n"))
        self.assertIsNone(check_syntax("a.tsx", "export const A = () => <div />;\n"))
        self.assertIsNotNone(check_syntax("a.ts", "function broken( {\n"))

    def test_json(self):
        self.assertIsNone(check_syntax("a.json", '{"a": 1}'))
        self.assertIsNotNone(check_syntax("a.json", '{"a": }'))


class TestCommandValidator(unittest.TestCase):
    def test_expected_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = TaskSpec(
                id="T1",
                title="t",
                goal="g",
                acceptance=(
                    AcceptanceCriterion(f"{sys.executable} -c \"raise SystemExit(1)\"", expect_exit=1),
                ),
            )
            result = CommandValidator(tmp).validate(task, [])
            self.assertTrue(result.ok, result.render())

    def test_nonzero_exit_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = TaskSpec(
                id="T1",
                title="t",
                goal="g",
                acceptance=(AcceptanceCriterion(f"{sys.executable} -c \"raise SystemExit(3)\""),),
            )
            result = CommandValidator(tmp).validate(task, [])
            self.assertFalse(result.ok)
            self.assertIn("exit code: 3", result.render())

    def test_syntax_error_blocks_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("def broken(:\n", encoding="utf-8")
            task = TaskSpec(
                id="T1",
                title="t",
                goal="g",
                acceptance=(AcceptanceCriterion(f"{sys.executable} -c \"pass\""),),
            )
            result = CommandValidator(tmp).validate(task, ["a.py"])
            self.assertFalse(result.ok)
            self.assertIn("Syntax check failed", result.render())

    def test_missing_changed_file_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = TaskSpec(id="T1", title="t", goal="g")
            result = CommandValidator(tmp).validate(task, ["missing.py"])
            self.assertFalse(result.ok)
            self.assertIn("missing after apply", result.render())


if __name__ == "__main__":
    unittest.main()
