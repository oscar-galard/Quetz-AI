from quetz import config
import argparse
import os
import sys
from langchain_core.messages import HumanMessage
from quetz.agent import build_graph

GREEN = "\033[38;5;46m"
CYAN = "\033[38;5;51m"
BOLD = "\033[1m"
RESET = "\033[0m"

# Banner limpio de QUETZ-AI
BANNER = f"""
{GREEN}{BOLD} ██████  ██   ██ ████████ ████████ ███████{CYAN}      █████  ██ 
██    ██ ██   ██ ██          ██    ██     {CYAN}     ██   ██ ██ 
██    ██ ██   ██ █████       ██    ███████{CYAN}     ███████ ██ 
██    ██ ██   ██ ██          ██         ██{CYAN}     ██   ██ ██ 
 ██████\\  █████  ████████    ██    ███████{CYAN}  ██ ██   ██ ██
{RESET}"""

def print_banner():
    print(BANNER)

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="quetz-ai",
        description="Unix-style autonomous coding agent powered by local LLMs.",
    )
    parser.add_argument("task", nargs="?", default="-",
                        help="Task description. Use '-' to read from stdin.")
    parser.add_argument("-a", "--auto", action="store_true",
                        help="Autonomous mode (apply changes without confirmation).")
    parser.add_argument("-d", "--dir", default=".",
                        help="Working directory (default: current).")
    parser.add_argument("-i", "--interactive", action="store_true",
                        help="Interactive mode: ask before writing/editing.")
    parser.add_argument("-p", "--prompt-file", default=None,
                        help="File containing the task description.")
    parser.add_argument("--no-context", action="store_true",
                        help="Disable auto-loading of context files (specs.md, skills.md, etc.).")
    parser.add_argument("--model", default=None,
                        help=f"Ollama model name (default from .env or '{config.MODEL_NAME}').")
    parser.add_argument("--max-iter", type=int, default=25,
                        help="Maximum tool calls (default: 25).")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Show detailed tool calls and results.")
    args = parser.parse_args()

    config.WORKSPACE_DIR = os.path.abspath(os.path.expanduser(args.dir))
    config.MAX_ITERATIONS = args.max_iter
    config.INTERACTIVE_MODE = not args.auto
    config.VERBOSE = args.verbose
    config.NO_CONTEXT = args.no_context
    if args.model:
        config.MODEL_NAME = args.model
    os.makedirs(config.WORKSPACE_DIR, exist_ok=True)

    # Read task from argument, prompt file, or stdin
    if args.prompt_file:
        prompt_path = args.prompt_file
        if not os.path.isfile(prompt_path):
            alt_path = os.path.join(config.WORKSPACE_DIR, args.prompt_file)
            if os.path.isfile(alt_path):
                prompt_path = alt_path
            else:
                parser.error(f"Prompt file not found in current directory or workspace: {args.prompt_file}")
        with open(prompt_path, "r", encoding="utf-8") as f:
            task_text = f.read().strip()
    elif args.task == "-":
        if sys.stdin.isatty():
            parser.error("No task provided. Use positional argument, -p/--prompt-file, or pipe into stdin.")
        task_text = sys.stdin.read().strip()
    else:
        task_text = args.task

    if not task_text:
        parser.error("No task provided.")

    print_banner()

    print(f"🔨 Workspace: {config.WORKSPACE_DIR}")
    print(f"🤖 Mode: {'interactive' if config.INTERACTIVE_MODE else 'autonomous'}")
    print(f"🧠 Model: {config.MODEL_NAME} ({config.MODE})")
    
    # LangSmith tracing status info
    tracing_enabled = os.environ.get("LANGCHAIN_TRACING_V2", "").lower() == "true"
    if tracing_enabled:
        project_name = os.environ.get("LANGCHAIN_PROJECT", "quetz-ai")
        print(f"📡 Observability: LangSmith tracing enabled (Project: {project_name})")
        
    print(f"📋 Task: {task_text}\n")

    # Initialize the isolated AgentState
    initial_state = {
        "task": task_text,
        "plan": "",
        "messages": [],
        "iteration": 0,
        "review_feedback": "",
        "is_approved": False,
    }

    app = build_graph()

    # Pass configuration to correct child runnable spans in LangSmith
    run_config = {"run_name": "Quetz_Execution"}

    # Run graph execution. The agent and tool nodes stream their progress in real-time.
    for update in app.stream(initial_state, config=run_config, stream_mode="updates"):
        pass

    print("\n🎯 Mission Complete!.")

if __name__ == "__main__":
    main()
