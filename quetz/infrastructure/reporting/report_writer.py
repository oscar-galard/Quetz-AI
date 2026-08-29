"""Filesystem adapter for the ReportWriter port."""
from __future__ import annotations

import os

from quetz import config as q_config
from quetz.application.ports.output import ReportWriter


class FileReportWriter(ReportWriter):
    """Writes reports to the configured workspace directory."""

    def __init__(self, workspace: str | None = None, dry_run: bool = False) -> None:
        self._workspace = os.path.abspath(workspace or q_config.WORKSPACE_DIR)
        self._dry_run = dry_run

    def write(self, filename: str, content: str) -> str:
        report_path = os.path.join(self._workspace, filename)
        if not self._dry_run:
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"✅ Successfully saved report to: {report_path}"
        return f"✅ (dry-run) Report ready for: {report_path}"
