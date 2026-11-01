import unittest

from quetz.domain.exceptions import TaskError
from quetz.domain.task_spec import Plan, TaskSpec, TaskStatus, normalize_rel_path


class TestTaskSpec(unittest.TestCase):
    def test_roundtrip(self):
        task = TaskSpec.from_dict(
            {
                "id": "T1",
                "title": "Add health route",
                "goal": "Expose GET /health",
                "files": ["backend/app/main.py"],
                "allowed_new_files": ["backend/app/api/health.py"],
                "acceptance": ["pytest -q"],
            }
        )
        self.assertEqual(task.id, "T1")
        self.assertEqual(task.acceptance[0].command, "pytest -q")
        self.assertEqual(TaskSpec.from_dict(task.to_dict()), task)

    def test_status_is_coerced(self):
        task = TaskSpec(id="T1", title="x", goal="y", status="DONE")
        self.assertIs(task.status, TaskStatus.DONE)

    def test_plan_rejects_duplicate_ids(self):
        with self.assertRaises(TaskError):
            Plan(
                project="demo",
                tasks=(
                    TaskSpec(id="T1", title="a", goal="a"),
                    TaskSpec(id="T1", title="b", goal="b"),
                ),
            )

    def test_next_pending_and_status_update(self):
        plan = Plan(
            project="demo",
            tasks=(
                TaskSpec(id="T1", title="a", goal="a"),
                TaskSpec(id="T2", title="b", goal="b"),
            ),
        )
        self.assertEqual(plan.next_pending().id, "T1")
        updated = plan.with_task_status("T1", TaskStatus.DONE)
        self.assertEqual(updated.next_pending().id, "T2")
        self.assertEqual(plan.tasks[0].status, TaskStatus.PENDING)

    def test_normalize_rel_path(self):
        self.assertEqual(normalize_rel_path("./a//b.py"), "a/b.py")
        for bad in ("/abs.py", "../escape.py", ".git/config", ""):
            with self.subTest(bad=bad), self.assertRaises(TaskError):
                normalize_rel_path(bad)

    def test_editable_files_merges_and_deduplicates(self):
        task = TaskSpec(
            id="T1",
            title="x",
            goal="y",
            files=("a.py",),
            allowed_new_files=("a.py", "b.py"),
        )
        self.assertEqual(task.editable_files, ("a.py", "b.py"))

    def test_layer_validation(self):
        valid = TaskSpec(id="T1", title="t", goal="g", layer="domain")
        self.assertEqual(valid.layer, "domain")
        empty = TaskSpec(id="T1", title="t", goal="g", layer="")
        self.assertEqual(empty.layer, "")
        coerced = TaskSpec(id="T1", title="t", goal="g", layer="INTERFACE")
        self.assertEqual(coerced.layer, "interface")
        with self.assertRaises(TaskError):
            TaskSpec(id="T1", title="t", goal="g", layer="weird")


if __name__ == "__main__":
    unittest.main()
