import tempfile
import unittest
from pathlib import Path

from quetz.domain.edit import EditPlan, FileEdit, EditOp
from quetz.domain.task_spec import TaskSpec
from quetz.infrastructure.fs.editor import AtomicEditor


def _task(*files, new=()):
    return TaskSpec(id="T1", title="t", goal="g", files=files, allowed_new_files=new)


class TestAtomicEditor(unittest.TestCase):
    def test_creates_and_replaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.py").write_text("app = FastAPI()\n", encoding="utf-8")
            editor = AtomicEditor(tmp)
            plan = EditPlan(
                task_id="T1",
                status="done",
                edits=(
                    FileEdit(file="new.py", op=EditOp.CREATE, content="VALUE = 1\n"),
                    FileEdit(
                        file="main.py",
                        op=EditOp.REPLACE,
                        find="app = FastAPI()\n",
                        replace="app = FastAPI()\napp.include_router(router)\n",
                    ),
                ),
            )
            result = editor.apply(plan, _task("main.py", new=("new.py",)))
            self.assertTrue(result.ok, result.error)
            self.assertEqual((root / "new.py").read_text(), "VALUE = 1\n")
            self.assertIn("include_router", (root / "main.py").read_text())

    def test_rejects_unauthorized_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            editor = AtomicEditor(tmp)
            plan = EditPlan(
                task_id="T1",
                status="done",
                edits=(FileEdit(file="other.py", op=EditOp.CREATE, content="x\n"),),
            )
            result = editor.apply(plan, _task("a.py"))
            self.assertFalse(result.ok)
            self.assertIn("not listed", result.error)

    def test_rejects_ambiguous_anchor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("x = 1\nx = 1\n", encoding="utf-8")
            editor = AtomicEditor(tmp)
            plan = EditPlan(
                task_id="T1",
                status="done",
                edits=(
                    FileEdit(file="a.py", op=EditOp.REPLACE, find="x = 1\n", replace="x = 2\n"),
                ),
            )
            result = editor.apply(plan, _task("a.py"))
            self.assertFalse(result.ok)
            self.assertIn("matches 2 times", result.error)
            self.assertEqual((root / "a.py").read_text(), "x = 1\nx = 1\n")

    def test_create_existing_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("x = 1\n", encoding="utf-8")
            editor = AtomicEditor(tmp)
            plan = EditPlan(
                task_id="T1",
                status="done",
                edits=(FileEdit(file="a.py", op=EditOp.CREATE, content="y\n"),),
            )
            result = editor.apply(plan, _task("a.py"))
            self.assertFalse(result.ok)
            self.assertIn("already exists", result.error)

    def test_revert_restores_and_removes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("old\n", encoding="utf-8")
            editor = AtomicEditor(tmp)
            plan = EditPlan(
                task_id="T1",
                status="done",
                edits=(
                    FileEdit(file="a.py", op=EditOp.REPLACE, find="old\n", replace="new\n"),
                    FileEdit(file="b.py", op=EditOp.CREATE, content="b\n"),
                ),
            )
            result = editor.apply(plan, _task("a.py", new=("b.py",)))
            self.assertTrue(result.ok, result.error)
            self.assertEqual((root / "a.py").read_text(), "new\n")
            self.assertTrue((root / "b.py").exists())
            editor.revert(result)
            self.assertEqual((root / "a.py").read_text(), "old\n")
            self.assertFalse((root / "b.py").exists())


if __name__ == "__main__":
    unittest.main()
