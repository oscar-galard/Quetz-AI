"""Presentation helpers: CLI plan approver and tool confirmer.

These implement the application output ports with real user interaction, and
are injected into the infrastructure container by the CLI composition root.
"""
from __future__ import annotations

from quetz import config as q_config
from quetz.application.ports.output import Approval
from quetz.domain.model import Plan
from quetz.infrastructure.container import Container


class CliPlanApprover:
    """Asks the user to approve, abort, or refine a proposed plan."""

    def __init__(self, interactive: bool = True) -> None:
        self._interactive = interactive

    def decide(self, plan: str) -> Approval:
        if not self._interactive:
            return Approval(status="approved")
        if len(plan.strip()) < 30:
            return Approval(status="approved")

        print("\n" + "=" * 80)
        print(plan)
        print("=" * 80 + "\n")

        print(
            "Do you approve this plan? [Y]es, [n]o (abort), or type your feedback "
            "to refine it: ",
            end="",
            flush=True,
        )
        user_input = input().strip().lower()
        if user_input in ("y", "yes", ""):
            print("\n🚀 Plan approved. Executing agent...")
            return Approval(status="approved")
        if user_input in ("n", "no"):
            q_config.play_alert_sound()
            return Approval(status="abort")
        q_config.play_alert_sound()
        print("\n🔄 Refining plan based on feedback...")
        return Approval(status="refine", feedback=user_input)


class CliToolConfirmer:
    """Interactively confirms write/edit tool calls before they run."""

    def __init__(self, interactive: bool = True) -> None:
        self._interactive = interactive

    def __call__(self, tool_name: str, args: dict) -> bool:
        if not self._interactive or tool_name not in ("write_file", "edit_file"):
            return True

        import pydoc
        import difflib
        import os

        from quetz import config as q_config

        print("\n" + "=" * 40)
        print(f"👉 Proposed Tool Call: {tool_name}")
        if tool_name == "write_file":
            print(f"📄 File: {args.get('file_path')}")
            print(f"📦 Size: {len(args.get('content', ''))} characters")
        elif tool_name == "edit_file":
            print(f"✏️  File: {args.get('file_path')}")
            print(f"🔄 Replacements: {len(args.get('replacements', []))}")
        print("=" * 40)

        while True:
            print(
                "\nOptions: [y] Apply, [n] Reject/Abort, [v] View full content in "
                "pager, [d] View diff: ",
                end="",
                flush=True,
            )
            answer = input().strip().lower()
            if answer in ("y", "yes"):
                return True
            if answer in ("n", "no", ""):
                return False
            if answer in ("v", "view"):
                if tool_name == "write_file":
                    pydoc.pager(args.get("content", ""))
                elif tool_name == "edit_file":
                    full_path = os.path.join(q_config.WORKSPACE_DIR, args.get("file_path", ""))
                    if os.path.isfile(full_path):
                        try:
                            with open(full_path, "r", encoding="utf-8") as f:
                                content = f.read()
                            modified = content
                            for rep in args.get("replacements", []):
                                modified = modified.replace(rep.get("find", ""), rep.get("replace", ""), 1)
                            pydoc.pager(modified)
                        except Exception as e:
                            print(f"Error previewing modified file: {e}")
                    else:
                        print("Original file not found.")
            elif answer in ("d", "diff"):
                full_path = os.path.join(q_config.WORKSPACE_DIR, args.get("file_path", ""))
                if tool_name == "write_file":
                    new_lines = args.get("content", "").splitlines(keepends=True)
                    diff = difflib.unified_diff(
                        [], new_lines, fromfile="/dev/null", tofile=args.get("file_path", "")
                    )
                    pydoc.pager("".join(diff))
                elif tool_name == "edit_file":
                    if os.path.isfile(full_path):
                        try:
                            with open(full_path, "r", encoding="utf-8") as f:
                                content = f.read()
                            modified = content
                            for rep in args.get("replacements", []):
                                modified = modified.replace(rep.get("find", ""), rep.get("replace", ""), 1)
                            diff = difflib.unified_diff(
                                content.splitlines(keepends=True),
                                modified.splitlines(keepends=True),
                                fromfile=args.get("file_path", "") + " (original)",
                                tofile=args.get("file_path", "") + " (modified)",
                            )
                            pydoc.pager("".join(diff))
                        except Exception as e:
                            print(f"Error generating diff: {e}")
                    else:
                        print("Original file not found.")


def make_container(interactive: bool) -> Container:
    """Compose the infrastructure container with CLI collaborators injected."""
    from quetz.infrastructure.container import Container
    from quetz.infrastructure.reporting.report_writer import FileReportWriter

    return Container(
        approver=CliPlanApprover(interactive=interactive),
        confirmer=CliToolConfirmer(interactive=interactive),
        report_writer=FileReportWriter(),
    )
