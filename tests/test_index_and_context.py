import tempfile
import unittest
from pathlib import Path

from quetz.application.ports.memory import MemoryEntry
from quetz.application.use_cases.compile_context import CompileContextUseCase
from quetz.domain.task_spec import AcceptanceCriterion, TaskSpec
from quetz.infrastructure.index.sqlite_index import SqliteProjectIndex
from quetz.infrastructure.memory.store import FileMemoryStore


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class TestProjectIndex(unittest.TestCase):
    def test_python_symbols_and_relative_imports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "pkg/__init__.py", "")
            _write(
                root,
                "pkg/models.py",
                "class User:\n    \"\"\"A user.\"\"\"\n\n    def name(self) -> str:\n        return 'x'\n",
            )
            _write(
                root,
                "pkg/api.py",
                "from .models import User\n\n\ndef get_user() -> User:\n    return User()\n",
            )
            index = SqliteProjectIndex(tmp)
            self.assertGreaterEqual(index.build(), 3)
            self.assertEqual(index.build(), 0)

            names = {s.name for s in index.symbols(path="pkg/models.py")}
            self.assertIn("User", names)
            self.assertIn("User.name", {s.qualname for s in index.symbols(path="pkg/models.py")})
            resolved = index.resolve_import("pkg/api.py", "models", level=1, name="User")
            self.assertEqual(resolved, "pkg/models.py")

    def test_typescript_symbols(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root,
                "src/Button.tsx",
                'import React from "react";\n\n'
                "export interface ButtonProps { label: string }\n\n"
                "export function Button({ label }: ButtonProps) {\n"
                '  return <button className="x">{label}</button>;\n'
                "}\n\n"
                "export class Store {\n"
                "  fetchData() { return 1; }\n"
                "}\n",
            )
            index = SqliteProjectIndex(tmp)
            index.build()
            symbols = index.symbols(path="src/Button.tsx")
            names = {s.name for s in symbols}
            self.assertIn("ButtonProps", names)
            self.assertIn("Button", names)
            self.assertIn("Store", names)
            self.assertIn("Store.fetchData", {s.qualname for s in symbols})
            tags = {tag for s in symbols for tag in s.tags}
            self.assertIn("react", tags)
            self.assertIn("tailwind", tags)

    def test_incremental_rebuild_detects_changed_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "a.py", "x = 1\n")
            index = SqliteProjectIndex(tmp)
            self.assertEqual(index.build(), 1)
            _write(root, "a.py", "x = 2\n")
            self.assertEqual(index.build(), 1)


class TestCompileContext(unittest.TestCase):
    def test_builds_target_files_and_interfaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "pkg/__init__.py", "")
            _write(root, "pkg/models.py", "class User:\n    pass\n")
            _write(
                root,
                "pkg/api.py",
                "from .models import User\n\n\ndef get_user():\n    return User()\n",
            )
            index = SqliteProjectIndex(tmp)
            task = TaskSpec(
                id="T1",
                title="Add user endpoint",
                goal="Expose get_user through an API route",
                files=("pkg/api.py",),
                allowed_new_files=("pkg/new.py",),
                symbols=("get_user",),
                acceptance=(AcceptanceCriterion("python -c 'pass'"),),
            )
            bundle = CompileContextUseCase(index, tmp, token_budget=4000).execute(task)
            paths = {f.path: f for f in bundle.target_files}
            self.assertIn("pkg/api.py", paths)
            self.assertTrue(paths["pkg/new.py"].is_new)
            self.assertIn("class User", bundle.interfaces)
            self.assertGreater(bundle.approx_tokens, 0)
            self.assertEqual(bundle.acceptance[0].command, "python -c 'pass'")

    def test_injects_relevant_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "a.py", "x = 1\n")
            index = SqliteProjectIndex(tmp)
            store = FileMemoryStore(tmp)
            store.add(MemoryEntry(kind="decision", path="a.py", content="Keep x an int"))
            task = TaskSpec(id="T1", title="Change x", goal="Update x", files=("a.py",))
            bundle = CompileContextUseCase(index, tmp, memory=store).execute(task)
            self.assertIn("Keep x an int", bundle.memory)

    def test_small_budget_records_omissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "a.py", "x = 1\n" * 2000)
            index = SqliteProjectIndex(tmp)
            task = TaskSpec(id="T1", title="Change x", goal="Update x", files=("a.py",))
            bundle = CompileContextUseCase(index, tmp, token_budget=100).execute(task)
            self.assertTrue(bundle.omitted)
            self.assertLessEqual(bundle.approx_tokens, 400)


if __name__ == "__main__":
    unittest.main()
