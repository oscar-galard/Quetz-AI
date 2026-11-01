"""Command-line interface for the stateless planner/executor pipeline."""
from __future__ import annotations

import argparse
import os
import sys

from quetz import config
from quetz.application.prompts.executor import build_executor_messages
from quetz.application.use_cases.compile_context import CompileContextUseCase
from quetz.application.use_cases.execute_task import ExecuteTaskUseCase
from quetz.application.use_cases.plan_project import PlanProjectUseCase
from quetz.application.use_cases.update_memory import UpdateMemoryUseCase
from quetz.domain.edit import ExecutionResult
from quetz.domain.task_spec import Plan, TaskSpec, TaskStatus
from quetz.infrastructure.container import Container
from quetz.infrastructure.tasks.store import (
    ensure_quetz_dir,
    load_plan,
    save_backlog,
    save_plan,
)
from quetz.infrastructure.tools.commands import CommandRunner

GREEN = "\033[38;5;46m"
CYAN = "\033[38;5;51m"
BOLD = "\033[1m"
RESET = "\033[0m"

_BANNER_QUETZ = [
    " ███  █   █ █████ █████ █████ ",
    "█   █ █   █ █       █      █  ",
    "█   █ █   █ ████    █     █   ",
    "█  █  █   █ █       █    █    ",
    " ██ █  ███  █████   █   █████ ",
]
_BANNER_AI = [
    "      ███  ███ ",
    "     █   █  █  ",
    "     █████  █  ",
    "     █   █  █  ",
    "     █   █ ███ ",
]

_GREENS = (
    "\033[38;5;46m",
    "\033[38;5;46m",
    "\033[38;5;82m",
    "\033[38;5;82m",
    "\033[38;5;40m",
    "\033[38;5;34m",
    "\033[38;5;28m",
    "\033[38;5;22m",
)


def _gradient_green(row: int, col: int) -> str:
    p = (row + col) / 35.0
    index = int(round(6.5 * p * p))
    return _GREENS[min(index, len(_GREENS) - 1)]


def build_banner() -> str:
    rows = []
    for r in range(len(_BANNER_QUETZ)):
        left = "".join(
            _gradient_green(r, c) + ch for c, ch in enumerate(_BANNER_QUETZ[r])
        )
        right = "".join(CYAN + ch for ch in _BANNER_AI[r])
        rows.append(BOLD + left + BOLD + right + RESET)
    return "\n".join(rows)


BANNER = build_banner()


def print_banner() -> None:
    print(BANNER)


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-d", "--dir", default=".", help="Working directory (default: current).")
    parser.add_argument(
        "--tasks-file",
        default=None,
        help="Path to tasks.json (default: <workspace>/.quetz/tasks.json).",
    )
    parser.add_argument("--budget", type=int, default=None, help="Token budget.")
    parser.add_argument(
        "--executor",
        choices=("local", "cloud"),
        default=None,
        help="Executor backend (cloud is faster).",
    )


def _workspace(args) -> str:
    workspace = os.path.abspath(os.path.expanduser(args.dir))
    os.makedirs(workspace, exist_ok=True)
    config.WORKSPACE_DIR = workspace
    return workspace


def _tasks_path(workspace: str, args) -> str:
    if args.tasks_file:
        return os.path.abspath(os.path.expanduser(args.tasks_file))
    return os.path.join(workspace, config.QUETZ_DIR, config.TASKS_FILE)


def _load_plan(workspace: str, args) -> tuple[Plan, str]:
    path = _tasks_path(workspace, args)
    if not os.path.isfile(path):
        raise SystemExit(
            f"No task plan found at {path}. Create one with the planner or write tasks.json manually."
        )
    return load_plan(path), path


def _select_task(plan: Plan, task_id: str | None) -> TaskSpec:
    if task_id:
        return plan.find_task(task_id)
    task = plan.next_pending()
    if task is None:
        raise SystemExit("No pending tasks in the plan.")
    return task


def _persist_plan(plan: Plan, path: str) -> None:
    save_plan(plan, path)
    save_backlog(plan, os.path.join(os.path.dirname(path), config.BACKLOG_FILE))


def _artifact_paths(workspace: str, plan_path: str) -> list[str]:
    candidates = (
        plan_path,
        os.path.join(os.path.dirname(plan_path), config.BACKLOG_FILE),
        os.path.join(workspace, config.QUETZ_DIR, config.MEMORY_FILE),
    )
    paths: list[str] = []
    for candidate in candidates:
        if not os.path.isfile(candidate):
            continue
        relative = os.path.relpath(candidate, workspace)
        if relative.startswith(".."):
            continue
        paths.append(relative.replace(os.sep, "/"))
    return paths


def _build_container(workspace: str, *, verbose: bool = False) -> Container:
    container = Container.build(workspace)
    if verbose:
        print(f"🔧 Index: {container.index.db_path}")  # type: ignore[attr-defined]
    ensure_quetz_dir(workspace)
    return container


def _show_diff(workspace: str, paths: list[str]) -> None:
    """Show git diff for the given paths."""
    import subprocess
    if not paths:
        print("   No files changed.")
        return
    for p in paths:
        full = os.path.join(workspace, p)
        if not os.path.isfile(full):
            continue
        print(f"\n   --- {p} ---")
        try:
            result = subprocess.run(
                ["git", "diff", "--no-color", "--", p],
                cwd=workspace, capture_output=True, text=True, timeout=10,
            )
            if result.stdout.strip():
                for line in result.stdout.splitlines():
                    if line.startswith("+") and not line.startswith("+++"):
                        print(f"   \033[32m{line}\033[0m")
                    elif line.startswith("-") and not line.startswith("---"):
                        print(f"   \033[31m{line}\033[0m")
                    elif line.startswith("@@"):
                        print(f"   \033[36m{line}\033[0m")
                    else:
                        print(f"   {line}")
            else:
                # New untracked file — show content
                with open(full) as f:
                    for line in f.readlines()[:40]:
                        print(f"   \033[32m+{line.rstrip()}\033[0m")
        except Exception:
            print(f"   (cannot show diff)")


def _show_file_pager(path: str) -> None:
    """Open a file in the system pager."""
    import subprocess
    pager = os.environ.get("PAGER", "less -R")
    try:
        subprocess.run(f"{pager} {path}", shell=True, timeout=60)
    except Exception:
        print(f"   (pager failed)")


def _edit_task_prompt(task: TaskSpec) -> str | None:
    """Let the user rewrite the task prompt. Returns new prompt or None to cancel."""
    import tempfile
    print(f"\n   Current prompt for {task.id}:")
    print(f"   {'─' * 40}")
    for line in task.prompt.splitlines():
        print(f"   {line}")
    print(f"   {'─' * 40}")

    print(f"\n   Type new prompt (or press Enter to keep current, 'cancel' to abort):")
    try:
        new_prompt = input("   › ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if not new_prompt or new_prompt.lower() == "cancel":
        return None
    return new_prompt


def _cmd_index(args) -> int:
    workspace = _workspace(args)
    container = _build_container(workspace)
    changed = container.index.build(force=args.force)
    print(f"✅ Indexed {changed} changed file(s) in {workspace}")
    return 0


def _cmd_context(args) -> int:
    workspace = _workspace(args)
    plan, plan_path = _load_plan(workspace, args)
    task = _select_task(plan, args.task)
    container = _build_container(workspace)
    compiler = CompileContextUseCase(
        container.index,
        workspace,
        git=container.git,
        memory=container.memory,
        skills=container.skills,
        token_budget=args.budget,
        reporter=print,
    )
    bundle = compiler.execute(task)

    print(f"\n📋 Task: {task.id} — {task.title}")
    print(f"🎯 Goal: {task.goal}")
    print(f"📦 Approx context: {bundle.approx_tokens} tokens")
    print(f"📄 Target files: {', '.join(f.path for f in bundle.target_files) or '(none)'}")
    if bundle.related_symbols:
        print(f"🔗 Related symbols: {len(bundle.related_symbols)}")
    if bundle.omitted:
        print("✂️  Trimmed sections:")
        for note in bundle.omitted:
            print(f"   - {note}")
    if args.show:
        print("\n" + "=" * 80)
        for message in build_executor_messages(bundle):
            print(f"[{message.role.upper()}]\n{message.content}\n")
        print("=" * 80)
    return 0


def _commit_if_possible(
    container: Container,
    task: TaskSpec,
    changed: list[str],
    branch: str,
    extra_paths: list[str] | None = None,
) -> None:
    container.git.stage([*changed, *(extra_paths or [])])
    message = f"quetz({task.id}): {task.title}"
    try:
        container.git.commit(message)
    except RuntimeError as exc:
        print(f"⚠️  Auto-commit skipped: {exc}")
        return
    print(f"✅ Committed on {branch}: {message}")


def _cmd_execute(args) -> int:
    workspace = _workspace(args)
    _configure_executor(args)
    plan, plan_path = _load_plan(workspace, args)
    task = _select_task(plan, args.task)
    container = _build_container(workspace)

    commit_enabled = config.AUTO_COMMIT and container.git.is_repo()
    branch = ""
    if commit_enabled and not args.no_commit:
        if not container.git.is_clean():
            print(
                "⚠️  Working tree is dirty; auto-commit will be skipped. "
                "Commit or stash changes first."
            )
            commit_enabled = False
        else:
            branch = container.git.prepare_branch(config.GIT_BRANCH_PREFIX)

    result = _execute_one(container, workspace, task, budget=args.budget)
    UpdateMemoryUseCase(container.memory).record(task, result)

    if result.ok:
        print(f"\n✅ {task.id} completed in {result.attempts} attempt(s).")
        if result.summary:
            print(f"   {result.summary}")
        if result.changed_paths:
            print("   Changed files:")
            for path in result.changed_paths:
                print(f"   - {path}")
        _persist_plan(plan.with_task_status(task.id, TaskStatus.DONE), plan_path)
        if commit_enabled:
            _commit_if_possible(
                container,
                task,
                list(result.changed_paths),
                branch,
                extra_paths=_artifact_paths(workspace, plan_path),
            )
        return 0

    print(f"\n❌ {task.id} failed after {result.attempts} attempt(s): {result.error}")
    _persist_plan(plan.with_task_status(task.id, TaskStatus.BLOCKED), plan_path)
    return 2


def _cmd_status(args) -> int:
    workspace = _workspace(args)
    plan, _ = _load_plan(workspace, args)
    print(f"Project: {plan.project}")
    for task in plan.tasks:
        marker = {
            TaskStatus.PENDING: "·",
            TaskStatus.RUNNING: "~",
            TaskStatus.DONE: "✓",
            TaskStatus.BLOCKED: "!",
            TaskStatus.FAILED: "✗",
        }.get(task.status, "?")
        print(f"  [{marker}] {task.id}: {task.title} ({task.status.value})")
    return 0


def _configure_planner(args) -> None:
    if not getattr(args, "planner", None):
        return
    if args.planner == "local":
        config.PLANNER_MODE = "local"
        config.PLANNER_MODEL = config.LOCAL_MODEL
    else:
        config.PLANNER_MODE = "cloud"
        config.PLANNER_MODEL = config.CLOUD_MODEL


def _configure_executor(args) -> None:
    if not getattr(args, "executor", None):
        return
    if args.executor == "cloud":
        config.EXECUTOR_MODE = "cloud"
        config.EXECUTOR_MODEL = config.CLOUD_MODEL
    else:
        config.EXECUTOR_MODE = "local"
        config.EXECUTOR_MODEL = config.LOCAL_MODEL


def _cmd_plan(args) -> int:
    workspace = _workspace(args)
    goal = args.goal
    if args.goal_file:
        with open(args.goal_file, "r", encoding="utf-8") as handle:
            goal = handle.read()
    if not goal or not goal.strip():
        raise SystemExit("Provide a goal string or --goal-file.")

    _configure_planner(args)
    container = _build_container(workspace)
    use_case = PlanProjectUseCase(
        llm=container.make_planner_llm(),
        workspace=workspace,
        reporter=print,
    )
    plan = use_case.execute(goal)
    path = _tasks_path(workspace, args)
    _persist_plan(plan, path)
    print(f"\n✅ Saved {len(plan.tasks)} task(s) to {path}")
    for task in plan.tasks:
        deps = f" (after {', '.join(task.depends_on)})" if task.depends_on else ""
        print(f"   - {task.id}: {task.title}{deps}")
    return 0


def _ready_task(plan: Plan) -> TaskSpec | None:
    done = {task.id for task in plan.tasks if task.status == TaskStatus.DONE}
    for task in plan.tasks:
        if task.status != TaskStatus.PENDING:
            continue
        if all(dep in done for dep in task.depends_on):
            return task
    return None


def _execute_one(
    container: Container,
    workspace: str,
    task: TaskSpec,
    *,
    budget: int | None,
) -> ExecutionResult:
    if task.setup_commands:
        runner = CommandRunner(workspace)
        for cmd in task.setup_commands:
            tool_emoji = "🔧"
            if "uv " in cmd:
                tool_emoji = "🐍"
            elif "npm " in cmd or "npx " in cmd:
                tool_emoji = "📦"
            elif "git " in cmd:
                tool_emoji = "🔀"
            elif "curl " in cmd or "wget " in cmd:
                tool_emoji = "🌐"
            print(f"  {tool_emoji} {cmd}")
            result = runner.run(cmd)
            if not result.ok:
                print(f"  ❌ Setup failed (exit {result.exit_code}): {result.stderr or result.stdout}")
                return ExecutionResult(
                    task_id=task.id,
                    ok=False,
                    status="blocked",
                    attempts=0,
                    error=f"Setup command failed: {cmd}\n{result.stderr or result.stdout}",
                )
            if result.stdout:
                print(f"  ✅ {result.stdout[:200]}")

    compiler = CompileContextUseCase(
        container.index,
        workspace,
        git=container.git,
        memory=container.memory,
        skills=container.skills,
        token_budget=budget,
        reporter=print,
    )
    bundle = compiler.execute(task)
    use_case = ExecuteTaskUseCase(
        llm=container.make_executor_llm(),
        editor=container.make_editor(),
        validator=container.validator,
        reporter=print,
    )
    return use_case.execute(task, bundle)


def _cmd_run(args) -> int:
    workspace = _workspace(args)
    _configure_executor(args)
    plan, plan_path = _load_plan(workspace, args)
    container = _build_container(workspace)
    commit_enabled = config.AUTO_COMMIT and container.git.is_repo() and not args.no_commit

    executed = 0
    while True:
        if args.max_tasks is not None and executed >= args.max_tasks:
            print(f"Reached --max-tasks={args.max_tasks}.")
            break
        task = _ready_task(plan)
        if task is None:
            pending = [t.id for t in plan.tasks if t.status == TaskStatus.PENDING]
            if pending:
                print(f"No runnable task; unresolved dependencies for: {', '.join(pending)}")
                return 2
            break

        branch = ""
        task_commit = commit_enabled
        if task_commit:
            if not container.git.is_clean():
                print(
                    "⚠️  Working tree is dirty; auto-commit disabled for this run. "
                    "Commit or stash changes first."
                )
                commit_enabled = False
                task_commit = False
            else:
                branch = container.git.prepare_branch(config.GIT_BRANCH_PREFIX)

        print(f"\n▶️  Running {task.id}: {task.title}")
        container.index.ensure_built()
        result = _execute_one(container, workspace, task, budget=args.budget)
        UpdateMemoryUseCase(container.memory).record(task, result)
        executed += 1

        if result.ok:
            print(f"✅ {task.id} completed in {result.attempts} attempt(s).")
            plan = plan.with_task_status(task.id, TaskStatus.DONE)
            _persist_plan(plan, plan_path)
            if task_commit:
                _commit_if_possible(
                    container,
                    task,
                    list(result.changed_paths),
                    branch,
                    extra_paths=_artifact_paths(workspace, plan_path),
                )
            continue

        print(f"❌ {task.id} blocked: {result.error}")
        plan = plan.with_task_status(task.id, TaskStatus.BLOCKED)
        _persist_plan(plan, plan_path)
        return 2

    print(f"\n🏁 Run finished; {executed} task(s) executed.")
    return 0


def _run_goal(
    container: Container,
    workspace: str,
    plan_path: str,
    goal: str,
    *,
    budget: int | None = None,
    step_mode: bool = False,
) -> tuple[int, int]:
    """Plan + execute a single goal. Returns (completed, total)."""
    from quetz import config as cfg
    planner_tag = "☁️  gpt-5-mini (cloud)" if cfg.PLANNER_MODE == "cloud" else f"🦙 {cfg.PLANNER_MODEL} (local)"
    executor_tag = "☁️  gpt-5-mini (cloud)" if cfg.EXECUTOR_MODE == "cloud" else f"🦙 {cfg.EXECUTOR_MODEL} (local)"
    print(f"🧠 Planning with {planner_tag}...")
    try:
        plan = PlanProjectUseCase(
            llm=container.make_planner_llm(),
            workspace=workspace,
            reporter=print,
        ).execute(goal)
    except Exception as exc:
        print(f"❌ Planning failed: {exc}")
        return 0, 0

    # Handle clarifying questions
    if plan.questions:
        print("\n❓ Questions before I proceed:")
        for i, q in enumerate(plan.questions, 1):
            print(f"   {i}. {q}")

        answers = []
        for q in plan.questions:
            try:
                answer = input("   › ").strip()
            except (EOFError, KeyboardInterrupt):
                answer = ""
            answers.append(answer)

        # Re-plan with answers
        answered_goal = goal + "\n\nAnswers:\n" + "\n".join(
            f"- {q}: {a}" for q, a in zip(plan.questions, answers)
        )
        print("\n🧠 Re-planning with answers...")
        try:
            plan = PlanProjectUseCase(
                llm=container.make_planner_llm(),
                workspace=workspace,
                reporter=print,
            ).execute(answered_goal)
        except Exception as exc:
            print(f"❌ Planning failed: {exc}")
            return 0, 0

        if plan.questions:
            print("⚠️  Still ambiguous. Proceeding with best guess.")

    _persist_plan(plan, plan_path)
    print(f"\n📋 {len(plan.tasks)} task(s):")
    for task in plan.tasks:
        deps = f" (after {', '.join(task.depends_on)})" if task.depends_on else ""
        print(f"   {task.id}: {task.title}{deps}")

    completed = 0
    for idx, task in enumerate(plan.tasks):
        if not all(
            t.status == TaskStatus.DONE
            for t in plan.tasks
            if t.id in task.depends_on
        ):
            print(f"\n⏭  Skipping {task.id} — dependencies not met.")
            continue

        print(f"\n▶️  {task.id}: {task.title}")
        result = _execute_one(container, workspace, task, budget=budget)
        UpdateMemoryUseCase(container.memory).record(task, result)

        if result.ok:
            completed += 1
            plan = plan.with_task_status(task.id, TaskStatus.DONE)
            print(f"   ✅ Done ({result.attempts} attempt(s))")
            if result.changed_paths:
                for p in result.changed_paths:
                    print(f"      {p}")
        else:
            plan = plan.with_task_status(task.id, TaskStatus.BLOCKED)
            print(f"   ❌ Blocked: {result.error}")

        _persist_plan(plan, plan_path)

        # Step mode: pause before next task with review options
        if step_mode and idx < len(plan.tasks) - 1:
            remaining = [t.id for t in plan.tasks[idx + 1:] if t.status == TaskStatus.PENDING]
            if not remaining:
                continue

            while True:
                try:
                    choice = input(
                        f"\n   [{remaining[0]}] [Y]ontinue [n]stop [d]iff [v]iew [e]dit prompt: "
                    ).strip().lower()
                except (EOFError, KeyboardInterrupt):
                    choice = "n"

                if choice in ("", "y", "yes", "continue", "next"):
                    break
                elif choice in ("n", "no", "q", "quit", "stop"):
                    print(f"   Stopped. Remaining: {', '.join(remaining)}")
                    print(f"   Resume with: quetz-ai run")
                    return completed, len(plan.tasks)
                elif choice == "d":
                    _show_diff(workspace, list(result.changed_paths) if result.ok else [])
                elif choice == "v":
                    paths = list(result.changed_paths) if result.ok else []
                    if paths:
                        _show_file_pager(os.path.join(workspace, paths[0]))
                    else:
                        print("   No files to view.")
                elif choice == "e":
                    # Rewrite prompt and retry current task
                    new_prompt = _edit_task_prompt(task)
                    if new_prompt:
                        task = TaskSpec(
                            id=task.id,
                            title=task.title,
                            goal=task.goal,
                            prompt=new_prompt,
                            files=task.files,
                            allowed_new_files=task.allowed_new_files,
                            symbols=task.symbols,
                            interfaces=task.interfaces,
                            acceptance=task.acceptance,
                            depends_on=task.depends_on,
                            max_attempts=task.max_attempts,
                            status=task.status,
                            notes=task.notes,
                            layer=task.layer,
                            setup_commands=task.setup_commands,
                            conventions=task.conventions,
                        )
                        print(f"\n   🔄 Retrying {task.id} with updated prompt...")
                        result = _execute_one(container, workspace, task, budget=budget)
                        UpdateMemoryUseCase(container.memory).record(task, result)
                        if result.ok:
                            completed += 1
                            plan = plan.with_task_status(task.id, TaskStatus.DONE)
                            print(f"   ✅ Done ({result.attempts} attempt(s))")
                        else:
                            plan = plan.with_task_status(task.id, TaskStatus.BLOCKED)
                            print(f"   ❌ Blocked: {result.error}")
                        _persist_plan(plan, plan_path)
                        # Show new diff
                        if result.ok:
                            _show_diff(workspace, list(result.changed_paths))
                    else:
                        print("   Prompt unchanged.")
                else:
                    print("   [Y]=continue  [n]=stop  [d]=diff  [v]=view file  [e]=edit prompt")

    return completed, len(plan.tasks)


def _cmd_oneshot(args) -> int:
    """One-shot mode: plan + execute a single prompt, then exit."""
    workspace = _workspace(args)
    _configure_executor(args)
    _configure_planner(args)
    container = _build_container(workspace)
    plan_path = _tasks_path(workspace, args)

    goal = args.prompt
    if not goal or not goal.strip():
        raise SystemExit("Provide a prompt, e.g.: quetz-ai \"create a FastAPI endpoint\"")

    completed, total = _run_goal(container, workspace, plan_path, goal, budget=args.budget)
    print(f"\n{'─'*50}")
    print(f"  {completed}/{total} task(s) completed.")
    print(f"{'─'*50}")
    return 0 if completed == total else 2


def _cmd_interactive(args) -> int:
    """Interactive mode: REPL session until user quits."""
    workspace = _workspace(args)
    _configure_executor(args)
    _configure_planner(args)
    container = _build_container(workspace)
    plan_path = _tasks_path(workspace, args)

    initial_goal = getattr(args, "prompt", None)
    if initial_goal and initial_goal.strip():
        print(f"\n{'='*50}")
        print("  Quetz-ai — interactive session")
        print("  Type your goal. 'quit' to exit.")
        print("  'stop' between tasks to review.")
        print(f"{'='*50}\n")
        completed, total = _run_goal(
            container, workspace, plan_path, initial_goal,
            budget=args.budget, step_mode=True,
        )
        print(f"\n  {completed}/{total} task(s) completed.\n")

    while True:
        try:
            user_input = input("› ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("Goodbye.")
            break

        # Handle 'continue' command to resume pending tasks
        if user_input.lower() in ("continue", "resume", "next"):
            completed, total = _run_goal(
                container, workspace, plan_path, "(continue pending tasks)",
                budget=args.budget, step_mode=True,
            )
            print(f"\n  {completed}/{total} task(s) completed.\n")
            continue

        completed, total = _run_goal(
            container, workspace, plan_path, user_input,
            budget=args.budget, step_mode=True,
        )
        print(f"\n  {completed}/{total} task(s) completed.\n")

    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="quetz-ai",
        description="Token-saver coding agent. Minimal code, local models, fast iterations.",
        epilog=(
            "Examples:\n"
            "  quetz-ai \"create the folder structure for a clean architecture project in backend/\"\n"
            "  quetz-ai \"install vite and react on the frontend directory\"\n"
            "  quetz-ai \"create a py file named organization.py with CRUD mockup\"\n"
            "  quetz-ai -i \"build a newsletter API\"\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-i", "--interactive",
        action="store_true",
        help="Interactive session (REPL). Run until you type 'quit'.",
    )
    _add_common(parser)
    subparsers = parser.add_subparsers(dest="command")

    index_parser = subparsers.add_parser("index", help="Build or refresh the project index.")
    _add_common(index_parser)
    index_parser.add_argument("--force", action="store_true", help="Rebuild from scratch.")
    index_parser.set_defaults(func=_cmd_index)

    context_parser = subparsers.add_parser("context", help="Compile context for one task.")
    _add_common(context_parser)
    context_parser.add_argument("--task", default=None, help="Task id (default: next pending).")
    context_parser.add_argument("--show", action="store_true", help="Print the full prompt.")
    context_parser.set_defaults(func=_cmd_context)

    exec_parser = subparsers.add_parser("execute", help="Execute one task with the local model.")
    _add_common(exec_parser)
    exec_parser.add_argument("--task", default=None, help="Task id (default: next pending).")
    exec_parser.add_argument("--no-commit", action="store_true", help="Do not auto-commit.")
    exec_parser.set_defaults(func=_cmd_execute)

    status_parser = subparsers.add_parser("status", help="Show task status.")
    _add_common(status_parser)
    status_parser.set_defaults(func=_cmd_status)

    plan_parser = subparsers.add_parser("plan", help="Decompose a goal into tasks.")
    _add_common(plan_parser)
    plan_parser.add_argument("goal", nargs="?", default=None, help="Natural-language goal.")
    plan_parser.add_argument("--goal-file", default=None, help="Read the goal from a file.")
    plan_parser.add_argument(
        "--planner",
        choices=("local", "cloud"),
        default=None,
        help="Override the planner backend for this run.",
    )
    plan_parser.set_defaults(func=_cmd_plan)

    run_parser = subparsers.add_parser("run", help="Execute pending tasks in order.")
    _add_common(run_parser)
    run_parser.add_argument("--no-commit", action="store_true", help="Do not auto-commit.")
    run_parser.add_argument("--max-tasks", type=int, default=None, help="Stop after N tasks.")
    run_parser.set_defaults(func=_cmd_run)

    chat_parser = subparsers.add_parser("chat", help="Interactive session (REPL).")
    _add_common(chat_parser)
    chat_parser.set_defaults(func=_cmd_interactive)

    return parser


def main(argv: list[str] | None = None) -> None:
    if argv is None:
        argv = sys.argv[1:]

    parser = _build_parser()
    subcommands = {"index", "context", "execute", "status", "plan", "run", "chat"}

    # Find the first non-flag argument
    first_positional = None
    skip_next = False
    flags_with_value = {"-d", "--dir", "--tasks-file", "--budget", "--executor", "--task", "--goal-file", "--max-tasks"}
    for arg in argv:
        if skip_next:
            skip_next = False
            continue
        if arg in flags_with_value:
            skip_next = True
            continue
        if arg.startswith("-"):
            continue
        first_positional = arg
        break

    # If first positional is NOT a subcommand, treat all positionals as prompt
    if first_positional and first_positional not in subcommands:
        # Separate flags from prompt words
        flags_only = []
        prompt_parts = []
        skip_next = False
        for arg in argv:
            if skip_next:
                skip_next = False
                flags_only.append(arg)
                continue
            if arg in flags_with_value:
                skip_next = True
                flags_only.append(arg)
                continue
            if arg.startswith("-"):
                flags_only.append(arg)
            else:
                prompt_parts.append(arg)

        args = parser.parse_args(flags_only)
        args.prompt = " ".join(prompt_parts)
        if args.interactive:
            args.func = _cmd_interactive
        else:
            args.func = _cmd_oneshot
    else:
        args = parser.parse_args(argv)
        if args.interactive:
            args.func = _cmd_interactive
        elif getattr(args, "prompt", None) and not getattr(args, "command", None):
            args.func = _cmd_oneshot

    print_banner()

    if not getattr(args, "func", None):
        parser.print_help()
        raise SystemExit(2)

    try:
        code = args.func(args)
    except KeyboardInterrupt:
        print("\n\n⏹  Interrupted by user (Ctrl+C). Shutting down gracefully.")
        print("   Work already written to disk is kept.")
        raise SystemExit(130)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(f"\n❌ Error: {exc}")
        raise SystemExit(1)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
