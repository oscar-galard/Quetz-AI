import argparse
import os
import sys
from langchain_core.messages import HumanMessage
from quetz import config
from quetz.agent import build_graph

def planning_phase(task_text: str) -> list:
    """Interactively draft and approve a plan with the user before executing the graph."""
    from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
    from quetz.agent import get_llm
    
    print("🧠 Drafting proposed plan...")
    
    planning_sys_prompt = SystemMessage(content=(
        "You are Quetz-AI, a Unix programming agent.\n"
        "Before writing any code or executing tools, you must formulate a structured, "
        "step-by-step action plan to accomplish the user's task.\n"
        "Explain which files you will read, write, or modify, and how you will verify each change.\n"
        "Present your plan under the header '# PROPOSED PLAN'."
    ))
    
    messages = [planning_sys_prompt, HumanMessage(content=task_text)]
    llm = get_llm()
    
    while True:
        # Capture the conversation history length at the start of this generation/refinement turn
        turn_messages_len = len(messages)
        attempts = 0
        max_attempts = 5
        
        while True:
            response = llm.invoke(messages)
            plan_content = response.content
            
            # If the response is extremely short (e.g. ":" or "a" or less than 30 characters),
            # it is invalid. We append it and a request for correction to messages and retry.
            if len(plan_content.strip()) < 30 and attempts < max_attempts:
                attempts += 1
                print(f"⚠️  Received short/invalid plan response from LLM (content: {repr(plan_content)}), retrying self-correction (attempt {attempts}/{max_attempts})...")
                messages.append(AIMessage(content=plan_content))
                messages.append(HumanMessage(content=(
                    "The plan you formulated is too short or invalid. "
                    "Please formulate a complete, structured, step-by-step action plan to accomplish the user's task. "
                    "Present your plan under the header '# PROPOSED PLAN'."
                )))
                continue
            
            # If we got a valid response (or hit max_attempts), revert messages of the current turn back
            # to hide the intermediate self-correction messages from the final conversational context
            if len(messages) > turn_messages_len:
                messages = messages[:turn_messages_len]
            break
            
        print("\n" + "="*80)
        print(plan_content)
        print("="*80 + "\n")
        
        if not config.INTERACTIVE_MODE:
            # If not in interactive mode, auto-approve the plan
            messages.append(AIMessage(content=plan_content))
            messages.append(HumanMessage(content="Plan auto-approved. Please proceed."))
            break
            
        print("Do you approve this plan? [Y]es, [n]o (abort), or type your feedback to refine it: ", end="", flush=True)
        user_input = input().strip()
        
        if user_input.lower() in ("y", "yes", ""):
            messages.append(AIMessage(content=plan_content))
            messages.append(HumanMessage(content="Plan approved. Please proceed with the implementation using the available tools."))
            print("\n🚀 Plan approved. Executing agent...")
            break
        elif user_input.lower() in ("n", "no"):
            print("\n❌ Task aborted by user.")
            sys.exit(0)
        else:
            # User provided feedback to refine the plan
            print("\n🔄 Refining plan based on feedback...")
            messages.append(AIMessage(content=plan_content))
            messages.append(HumanMessage(content=f"Please refine the plan with this feedback: {user_input}"))
            
    # Return the conversation history up to the approved plan, removing the planning_sys_prompt
    return [m for m in messages if m != planning_sys_prompt]

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
    
    # LangSmith tracing status info
    tracing_enabled = os.environ.get("LANGCHAIN_TRACING_V2", "").lower() == "true"
    if tracing_enabled:
        project_name = os.environ.get("LANGCHAIN_PROJECT", "quetz-ai")
        print(f"📡 Observability: LangSmith tracing enabled (Project: {project_name})")
        
    print(f"📋 Task: {task_text}\n")

    # Run the interactive/auto planning phase first
    planned_messages = planning_phase(task_text)

    app = build_graph()

    initial_state = {
        "messages": planned_messages,
        "iteration": 0,
    }

    # Run graph execution. The agent and tool nodes stream their progress in real-time.
    for update in app.stream(initial_state, stream_mode="updates"):
        pass

    print("\n🎯 Mission Complete!.")

if __name__ == "__main__":
    main()
