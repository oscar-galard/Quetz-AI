"""Run syntax gates and explicit acceptance commands in the workspace."""
from __future__ import annotations

import subprocess

from quetz import config as q_config
from quetz.domain.edit import CommandResult, ValidationResult
from quetz.domain.task_spec import TaskSpec
from quetz.infrastructure.fs.paths import read_text, resolve_workspace_path, workspace_root
from quetz.infrastructure.validation.syntax import check_syntax

_MAX_OUTPUT = 3000


def _trim(text: str | None) -> str:
    value = (text or "").strip()
    if len(value) <= _MAX_OUTPUT:
        return value
    return value[-_MAX_OUTPUT:] + "\n...[truncated]..."


class CommandValidator:
    def __init__(self, workspace: str, *, default_timeout: int | None = None) -> None:
        self.workspace = workspace_root(workspace)
        self.default_timeout = default_timeout or q_config.VALIDATION_TIMEOUT

    def validate(self, task: TaskSpec, changed_paths: list[str]) -> ValidationResult:
        for rel_path in changed_paths:
            try:
                full_path = resolve_workspace_path(self.workspace, rel_path)
            except Exception as exc:
                return ValidationResult(ok=False, syntax_error=str(exc))
            if not full_path.is_file():
                return ValidationResult(
                    ok=False,
                    syntax_error=f"Changed file is missing after apply: {rel_path}",
                )
            error = check_syntax(full_path, read_text(full_path))
            if error:
                return ValidationResult(ok=False, syntax_error=error)

        results: list[CommandResult] = []
        for criterion in task.acceptance:
            timeout = min(criterion.timeout or self.default_timeout, self.default_timeout)
            try:
                completed = subprocess.run(
                    criterion.command,
                    shell=True,
                    cwd=self.workspace,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                results.append(
                    CommandResult(
                        command=criterion.command,
                        exit_code=completed.returncode,
                        stdout=_trim(completed.stdout),
                        stderr=_trim(completed.stderr),
                        expected_exit=criterion.expect_exit,
                    )
                )
            except subprocess.TimeoutExpired as exc:
                results.append(
                    CommandResult(
                        command=criterion.command,
                        exit_code=-1,
                        stdout=_trim(exc.stdout if isinstance(exc.stdout, str) else None),
                        stderr=_trim(exc.stderr if isinstance(exc.stderr, str) else None),
                        timed_out=True,
                        expected_exit=criterion.expect_exit,
                    )
                )

        return ValidationResult(ok=all(result.ok for result in results), results=tuple(results))
