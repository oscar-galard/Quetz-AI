import subprocess
import tempfile
import unittest
from pathlib import Path

from quetz.infrastructure.git.repo import GitRepo


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )


class TestGitRepo(unittest.TestCase):
    def _repo(self, root: Path) -> GitRepo:
        _git(root, "init", "-q")
        _git(root, "config", "user.email", "test@example.com")
        _git(root, "config", "user.name", "Test")
        (root / "a.py").write_text("x = 1\n", encoding="utf-8")
        _git(root, "add", "a.py")
        _git(root, "commit", "-q", "-m", "initial")
        return GitRepo(str(root))

    def test_branch_stage_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self._repo(root)
            self.assertTrue(repo.is_repo())
            self.assertTrue(repo.is_clean())

            branch = repo.prepare_branch("quetz/")
            self.assertEqual(branch, "quetz/work")
            self.assertEqual(repo.current_branch(), branch)

            (root / "a.py").write_text("x = 2\n", encoding="utf-8")
            (root / ".quetz").mkdir()
            (root / ".quetz/tasks.json").write_text("{}\n", encoding="utf-8")
            (root / ".quetz/index.db").write_text("ignored\n", encoding="utf-8")

            self.assertFalse(repo.is_clean())
            repo.stage(["a.py", ".quetz/tasks.json", ".quetz/index.db"])
            repo.commit("quetz(T1): change x")
            self.assertTrue(repo.is_clean())
            log = subprocess.run(
                ["git", "log", "-1", "--pretty=%s"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            self.assertEqual(log.strip(), "quetz(T1): change x")
            tracked = subprocess.run(
                ["git", "ls-files", ".quetz/index.db"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            self.assertEqual(tracked.strip(), "")

    def test_non_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = GitRepo(tmp)
            self.assertFalse(repo.is_repo())
            self.assertEqual(repo.diff(), "")
            self.assertEqual(repo.changed_paths(), [])


if __name__ == "__main__":
    unittest.main()
