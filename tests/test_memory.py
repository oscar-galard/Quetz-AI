import tempfile
import unittest
from pathlib import Path

from quetz.application.ports.memory import MemoryEntry
from quetz.application.use_cases.update_memory import UpdateMemoryUseCase
from quetz.domain.edit import ExecutionResult
from quetz.domain.task_spec import TaskSpec
from quetz.infrastructure.memory.store import FileMemoryStore


class TestFileMemoryStore(unittest.TestCase):
    def test_add_and_query(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = FileMemoryStore(tmp)
            store.add(MemoryEntry(kind="decision", path="a.py", content="Keep routes thin"))
            store.add(MemoryEntry(kind="pitfall", path="b.py", content="Do not import app early"))
            self.assertEqual(len(store.recent(limit=10)), 2)
            hits = store.for_paths(["a.py"])
            self.assertEqual(len(hits), 1)
            self.assertIn("Keep routes thin", hits[0].content)
            text = (Path(tmp) / ".quetz/memory.md").read_text()
            self.assertIn("# Project memory", text)

    def test_for_paths_falls_back_to_recent(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = FileMemoryStore(tmp)
            store.add(MemoryEntry(kind="decision", content="Use Pydantic v2"))
            self.assertEqual(len(store.for_paths([])), 1)


class TestUpdateMemory(unittest.TestCase):
    def test_records_success_and_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = FileMemoryStore(tmp)
            use_case = UpdateMemoryUseCase(store)
            task = TaskSpec(id="T1", title="Add route", goal="g")
            use_case.record(
                task,
                ExecutionResult(
                    task_id="T1",
                    ok=True,
                    status="done",
                    attempts=1,
                    summary="added it",
                    changed_paths=("app.py",),
                ),
            )
            use_case.record(
                task,
                ExecutionResult(
                    task_id="T1",
                    ok=False,
                    status="blocked",
                    attempts=1,
                    error="missing interface",
                ),
            )
            entries = store.recent(limit=10)
            self.assertEqual(len(entries), 2)
            self.assertIn("task-done", entries[0].content)
            self.assertIn("task-blocked", entries[1].content)


if __name__ == "__main__":
    unittest.main()
