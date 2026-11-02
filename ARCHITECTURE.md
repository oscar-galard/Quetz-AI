# Node Responsibilities

Each node has ONE job. The orchestrator coordinates them.

## Orchestrator (cloud)
- **Job:** Route between nodes, manage state, decide next step
- **Input:** Goal or task + pipeline state
- **Output:** Pipeline state (done, retry, fix, blocked)
- **Model:** Cloud (fast decisions)
- **State:** LangGraph or simple loop

## Planner (cloud)
- **Job:** Decompose goal into tasks
- **Input:** Natural language goal + project tree + code summary
- **Output:** `tasks.json` with prompts, layers, acceptance commands
- **Model:** Cloud (good at decomposition)

## Context Compiler (Python, no LLM)
- **Job:** Build minimal context bundle for one task
- **Input:** Task spec + project index + skills + memory
- **Output:** `ContextBundle` (~1000 tokens)
- **Model:** None (deterministic)

## Executor (local)
- **Job:** Write code from instructions
- **Input:** Task prompt + context bundle
- **Output:** JSON edit plan (create/replace/append/prepend)
- **Model:** Local Qwen3 (cheap code generation)
- **NOT responsible for:** Fixing errors, analyzing bugs, retrying

## Validator (Python, no LLM)
- **Job:** Check syntax + acceptance commands
- **Input:** Changed files + acceptance criteria
- **Output:** ValidationResult (pass/fail + error)
- **Model:** None (deterministic)

## Debugger (cloud)
- **Job:** Analyze root cause of failures
- **Input:** Broken code + validation error
- **Output:** DebugHypothesis (root_cause, fix_strategy)
- **Model:** Cloud (good at analysis)

## Fixer (local)
- **Job:** Apply targeted fixes based on hypothesis
- **Input:** Broken code + error + debugger hypothesis
- **Output:** Edit plan (minimal fix)
- **Model:** Local Qwen3 (cheap fixes)

## Editor (Python, no LLM)
- **Job:** Apply edit plans atomically
- **Input:** Edit plan + task spec
- **Output:** Applied files (with rollback support)
- **Model:** None (deterministic)

## Git (Python, no LLM)
- **Job:** Commit successful tasks
- **Input:** Changed files + commit message
- **Output:** Git commit
- **Model:** None (deterministic)
