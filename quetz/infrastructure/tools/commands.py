"""Shell command execution for scaffolding and verification."""
from __future__ import annotations

import subprocess

from quetz.domain.edit import CommandResult
from quetz.infrastructure.fs.paths import workspace_root


def _trim(text: str | None, limit: int = 3000) -> str:
    value = (text or "").strip()
    if len(value) <= limit:
        return value
    return value[-limit:] + "\n...[truncated]..."


class CommandRunner:
    """Runs shell commands in the workspace with captured output."""

    def __init__(self, workspace: str, *, default_timeout: int = 300) -> None:
        self.workspace = workspace_root(workspace)
        self.default_timeout = default_timeout

    def _ensure_project_init(self, command: str) -> None:
        """Auto-create pyproject.toml if uv add is called without one."""
        if not command.strip().startswith("uv add"):
            return
        if (self.workspace / "pyproject.toml").is_file():
            return
        # Auto-init project
        subprocess.run(
            "uv init --package --name app",
            shell=True,
            cwd=self.workspace,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def run(self, command: str, *, timeout: int | None = None) -> CommandResult:
        self._ensure_project_init(command)
        effective_timeout = timeout or self.default_timeout
        try:
            completed = subprocess.run(
                command,
                shell=True,
                cwd=self.workspace,
                capture_output=True,
                text=True,
                timeout=effective_timeout,
            )
            return CommandResult(
                command=command,
                exit_code=completed.returncode,
                stdout=_trim(completed.stdout),
                stderr=_trim(completed.stderr),
            )
        except subprocess.TimeoutExpired as exc:
            return CommandResult(
                command=command,
                exit_code=-1,
                stdout=_trim(exc.stdout if isinstance(exc.stdout, str) else None),
                stderr=_trim(exc.stderr if isinstance(exc.stderr, str) else None),
                timed_out=True,
            )
