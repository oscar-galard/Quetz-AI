"""Multiagent orchestrator: decides which agent to call based on context.

This is NOT a fixed workflow. The orchestrator:
1. Analyzes the situation (what type of task, what's on disk, what failed)
2. Decides which agent to call (Analyzer, Executor, Debugger, Fixer)
3. Recommends actions to the user
4. Asks for input when uncertain
5. Routes to the next agent based on results

Each agent is independent and composable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from quetz.application.ports.validator import ValidationPort
from quetz.application.use_cases.analyze_task import AnalyzerUseCase
from quetz.application.use_cases.debug_task import DebuggerUseCase
from quetz.application.use_cases.execute_task import ExecuteTaskUseCase
from quetz.application.use_cases.fixer import FixerUseCase
from quetz.application.use_cases.modify_task import ModifierUseCase
from quetz.domain.context import ContextBundle
from quetz.domain.edit import ExecutionResult
from quetz.domain.task_spec import TaskSpec
from quetz.infrastructure.fs.editor import AtomicEditor

Reporter = Callable[[str], None]
Asker = Callable[[str, list[str]], str]  # (question, options) -> answer


def _noop(_text: str) -> None:
    pass


def _default_ask(question: str, options: list[str]) -> str:
    """Default asker: just pick the first option (non-interactive fallback)."""
    return options[0] if options else "continue"


@dataclass
class OrchestratorState:
    """Tracks what happened and what to do next."""
    task: TaskSpec
    context: ContextBundle
    result: ExecutionResult | None = None
    attempts: int = 0
    history: list[str] = field(default_factory=list)
    recommendation: str = ""


class Orchestrator:
    """Multiagent coordinator: decides which agent to call and when."""

    def __init__(
        self,
        *,
        executor: ExecuteTaskUseCase,
        analyzer: AnalyzerUseCase | None = None,
        modifier: ModifierUseCase | None = None,
        debugger: DebuggerUseCase | None = None,
        fixer: FixerUseCase | None = None,
        validator: ValidationPort | None = None,
        editor: AtomicEditor | None = None,
        reporter: Reporter | None = None,
        asker: Asker | None = None,
    ) -> None:
        self._executor = executor
        self._analyzer = analyzer
        self._modifier = modifier
        self._debugger = debugger
        self._fixer = fixer
        self._validator = validator
        self._editor = editor
        self._report = reporter or _noop
        self._ask = asker or _default_ask

    def run(self, task: TaskSpec, context: ContextBundle) -> ExecutionResult:
        """Run the multiagent pipeline with decisions at each step."""
        state = OrchestratorState(task=task, context=context)

        # Step 1: Decide initial strategy
        strategy = self._decide_strategy(state)
        self._report(f"🧠 Orchestrator: strategy = {strategy}")

        # Step 2: Execute strategy
        if strategy == "improve":
            result = self._run_improver(state)
        else:
            result = self._run_creator(state)

        state.result = result
        if result.ok:
            return result

        # Step 3: Failure — decide what to do
        return self._handle_failure(state)

    def _decide_strategy(self, state: OrchestratorState) -> str:
        """Decide: improve existing code or create new code."""
        task = state.task
        has_existing = bool(task.files)
        has_new = bool(task.allowed_new_files)

        if has_existing and not has_new:
            return "improve"
        elif has_new and not has_existing:
            return "create"
        else:
            # Mixed: ask user
            self._report("🤔 Orchestrator: task has both existing and new files.")
            choice = self._ask(
                "Should I improve existing code or create new code?",
                ["improve", "create", "both"],
            )
            return choice if choice in ("improve", "create") else "create"

    def _run_improver(self, state: OrchestratorState) -> ExecutionResult:
        """Analyzer (cloud) → ChangeSpec → Modifier (local) → Editor."""
        task = state.task
        if self._analyzer is None or self._editor is None:
            return self._run_creator(state)

        # 1. Analyzer produces ChangeSpec (what to improve)
        self._report("🔍 Analyzer: producing change spec...")
        spec = self._analyzer.analyze(
            changed_paths=list(task.files),
            workspace=str(self._editor.workspace),
            goal=task.prompt,
            conventions=task.conventions or state.context.conventions,
            skills=state.context.skills,
        )
        if spec is None:
            self._report("  ⚠️  Analyzer produced no spec — falling back to executor.")
            return self._run_creator(state)

        # 2. Modifier (local) applies changes file-by-file with history
        if self._modifier is None:
            self._report("  ⚠️  Modifier not available — falling back to executor.")
            return self._run_creator(state)

        self._report("📝 Modifier: applying changes...")
        return self._modifier.apply_spec(
            task, spec,
            conventions=task.conventions or state.context.conventions,
            skills=state.context.skills,
        )

    def _run_creator(self, state: OrchestratorState) -> ExecutionResult:
        """Use Executor (local) for new code generation."""
        self._report("🦜 Executor: generating code...")
        return self._executor.execute(state.task, state.context)

    def _handle_failure(self, state: OrchestratorState) -> ExecutionResult:
        """Decide how to handle failure: fix, retry, or stop."""
        result = state.result
        if result is None:
            return ExecutionResult(
                task_id=state.task.id, ok=False, status="blocked",
                attempts=0, error="No result",
            )

        # Ask user what to do
        self._report(f"\n⚠️  Task failed: {result.error[:150]}")
        self._report("   Code is on disk — you can edit manually in Emacs.")

        choice = self._ask(
            "What should I do next?",
            ["fix", "retry", "manual", "skip"],
        )

        if choice == "fix":
            return self._run_fixer(state)
        elif choice == "retry":
            return self._run_creator(state)
        elif choice == "manual":
            self._report("   OK — code is on disk. Edit manually and run again.")
            return result
        else:  # skip
            self._report("   Skipping task.")
            return result

    def _run_fixer(self, state: OrchestratorState) -> ExecutionResult:
        """Use Debugger + Fixer to attempt a targeted fix."""
        result = state.result
        if result is None:
            return ExecutionResult(
                task_id=state.task.id, ok=False, status="blocked",
                attempts=0, error="No result",
            )

        if self._debugger is None or self._fixer is None or self._editor is None:
            self._report("   Debugger/Fixer not available — edit manually.")
            return result

        # Debugger analyzes
        self._report("🔍 Debugger: analyzing root cause...")
        hypothesis = self._debugger.analyze(
            changed_paths=list(result.changed_paths or ()),
            workspace=str(self._editor.workspace),
            error=result.error,
            task_prompt=state.task.prompt,
        )
        if hypothesis is None:
            self._report("   No hypothesis — edit manually.")
            return result

        self._report(f"   💡 Root cause: {hypothesis.root_cause}")
        self._report(f"   🔧 Strategy: {hypothesis.fix_strategy}")

        # Fixer applies
        self._report("🔧 Fixer: applying targeted fix...")
        fixed_plan = self._fixer.fix(
            changed_paths=list(result.changed_paths or ()),
            workspace=str(self._editor.workspace),
            error=result.error,
            task_prompt=state.task.prompt,
            hypothesis=hypothesis,
        )
        if fixed_plan is None or fixed_plan.blocked:
            self._report("   Fixer couldn't fix — edit manually.")
            return result

        # Apply fix
        applied = self._editor.apply(fixed_plan, state.task)
        if not applied.ok:
            self._report(f"   Fix apply failed: {applied.error}")
            return result

        # Validate fix
        if self._validator is None:
            return ExecutionResult(
                task_id=state.task.id, ok=True, status="done",
                attempts=result.attempts, summary=fixed_plan.summary,
                changed_paths=applied.changed_paths,
            )

        validation = self._validator.validate(
            state.task, list(applied.changed_paths), skip_acceptance=False
        )
        if validation.ok:
            self._report("   ✅ Fix succeeded!")
            return ExecutionResult(
                task_id=state.task.id, ok=True, status="done",
                attempts=result.attempts, summary=fixed_plan.summary,
                changed_paths=applied.changed_paths, validation=validation,
            )

        # Fix failed
        self._editor.revert(applied)
        self._report("   ❌ Fix validation failed — code kept on disk.")
        return result
