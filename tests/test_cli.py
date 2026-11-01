import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from quetz.cli import main
from quetz.domain.task_spec import Plan, TaskSpec, TaskStatus
from quetz.infrastructure.tasks.store import ensure_quetz_dir, load_plan, save_plan


def _write_plan(root: Path) -> None:
    (_ := root / "pkg").mkdir()
    (root / "pkg/__init__.py").write_text("", encoding="utf-8")
    (root / "pkg/app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    quetz_dir = ensure_quetz_dir(root)
    save_plan(
        Plan(
            project="demo",
            tasks=(
                TaskSpec(
                    id="T1",
                    title="Change main",
                    goal="Return 2",
                    files=("pkg/app.py",),
                ),
            ),
        ),
        quetz_dir / "tasks.json",
    )


class TestCli(unittest.TestCase):
    def _run(self, argv):
        output = io.StringIO()
        code = None
        with contextlib.redirect_stdout(output):
            try:
                main(argv)
            except SystemExit as exc:
                code = exc.code
        return code, output.getvalue()

    def test_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_plan(root)
            code, output = self._run(["status", "-d", tmp])
            self.assertEqual(code, 0)
            self.assertIn("T1", output)
            self.assertIn("pending", output)

    def test_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_plan(root)
            code, output = self._run(["context", "-d", tmp, "--task", "T1"])
            self.assertEqual(code, 0)
            self.assertIn("Task: T1", output)
            self.assertIn("pkg/app.py", output)

    def test_requires_subcommand(self):
        code, output = self._run([])
        self.assertEqual(code, 2)
        self.assertIn("usage:", output.lower())


if __name__ == "__main__":
    unittest.main()
