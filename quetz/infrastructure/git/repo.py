"""Small subprocess-based Git adapter scoped to a workspace."""
from __future__ import annotations

import subprocess
from pathlib import Path

from quetz.infrastructure.fs.paths import workspace_root


class GitRepo:
    def __init__(self, workspace: str) -> None:
        self.workspace = workspace_root(workspace)

    def _run(self, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=self.workspace,
            capture_output=True,
            text=True,
            check=check,
        )

    def is_repo(self) -> bool:
        try:
            result = self._run(["rev-parse", "--is-inside-work-tree"], check=False)
        except (OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0 and result.stdout.strip() == "true"

    def current_branch(self) -> str:
        if not self.is_repo():
            return ""
        return self._run(["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()

    def changed_paths(self) -> list[str]:
        if not self.is_repo():
            return []
        output = self._run(["status", "--porcelain"], check=False).stdout
        paths: list[str] = []
        for line in output.splitlines():
            if len(line) < 4:
                continue
            path = line[3:].strip()
            if " -> " in path:
                path = path.split(" -> ", 1)[1].strip()
            path = path.strip('"')
            if path.startswith(".quetz/"):
                continue
            if path:
                paths.append(path)
        return paths

    def is_clean(self) -> bool:
        return not self.changed_paths()

    def diff(self, paths: list[str] | None = None) -> str:
        if not self.is_repo():
            return ""
        args = ["diff", "--no-color"]
        if paths:
            args.extend(["--", *paths])
        return self._run(args, check=False).stdout

    def diff_stat(self) -> str:
        if not self.is_repo():
            return ""
        return self._run(["diff", "--stat", "--no-color"], check=False).stdout

    def prepare_branch(self, prefix: str = "quetz/") -> str:
        """Return a quetz work branch, creating/checking it out when needed."""
        if not self.is_repo():
            raise RuntimeError("Not a git repository.")
        branch = f"{prefix.rstrip('/')}/work"
        current = self.current_branch()
        if current == branch:
            return branch
        exists = self._run(["rev-parse", "--verify", branch], check=False).returncode == 0
        if exists:
            self._run(["checkout", branch])
        else:
            self._run(["checkout", "-b", branch])
        return branch

    def stage(self, paths: list[str]) -> None:
        filtered = [
            p
            for p in paths
            if not p.startswith(".quetz/index.db")
            and not p.startswith(".quetz/logs/")
            and not p.endswith(".tmp")
        ]
        if filtered:
            self._run(["add", "--", *filtered])

    def commit(self, message: str) -> str:
        result = self._run(["commit", "-m", message], check=False)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "git commit failed")
        return result.stdout.strip()
