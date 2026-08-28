from quetz import config as q_config
import os
import sys
import json
import re
from typing import Annotated, TypedDict
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage, HumanMessage, RemoveMessage
from langchain_core.runnables import RunnableConfig
from langchain_ollama import ChatOllama
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from quetz.tools import tools, tool_map

def parse_tool_call_from_text(content: str) -> list[dict] | None:
    """Try to parse a tool call from the text content if native tool calling failed."""
    if not content:
        return None
        
    content_str = content.strip()
    
    # Check for <tool_call> tags
    tag_match = re.search(r"<tool_call>(.*?)</tool_call>", content_str, re.DOTALL)
    if tag_match:
        content_str = tag_match.group(1).strip()
    else:
        # Check for markdown code block
        code_block_match = re.search(r"```(?:json)?\s*(.*?)\s*```", content_str, re.DOTALL)
        if code_block_match:
            content_str = code_block_match.group(1).strip()
            
    # Try to parse the text as JSON
    try:
        # Try direct parse
        data = json.loads(content_str)
        if isinstance(data, dict) and "name" in data:
            args = data.get("arguments") or data.get("parameters") or data.get("args") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except:
                    pass
            return [{
                "name": data["name"],
                "args": args,
                "id": "fallback_id_" + os.urandom(4).hex(),
                "type": "tool_call"
            }]
    except Exception:
        # Find the first '{' and matching '}'
        try:
            start_idx = content_str.find('{')
            end_idx = content_str.rfind('}')
            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                json_part = content_str[start_idx:end_idx+1]
                data = json.loads(json_part)
                if isinstance(data, dict) and "name" in data:
                    args = data.get("arguments") or data.get("parameters") or data.get("args") or {}
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except:
                            pass
                    return [{
                        "name": data["name"],
                        "args": args,
                        "id": "fallback_id_" + os.urandom(4).hex(),
                        "type": "tool_call"
                    }]
        except:
            pass
            
    return None

class AgentState(TypedDict):
    task: str
    plan: str
    messages: Annotated[list[BaseMessage], add_messages]
    iteration: int
    review_feedback: str
    is_approved: bool
    summary: str

def load_context_files() -> str:
    """Detect and load instructions/context from workspace markdown files if they exist."""
    if q_config.NO_CONTEXT:
        return ""
    
    target_files = ["specs.md", "skills.md", "agents.md", "instructions.md"]
    context_parts = []
    
    for filename in target_files:
        path = os.path.join(q_config.WORKSPACE_DIR, filename)
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                if content:
                    context_parts.append(f"--- CONTEXT FROM {filename} ---\n{content}")
            except Exception as e:
                if q_config.VERBOSE:
                    print(f"Error reading context file {filename}: {e}")
                    
    if context_parts:
        return "\n\n" + "\n\n".join(context_parts)
    return ""

def build_system_prompt(plan: str = "", review_feedback: str = "") -> SystemMessage:
    prompt_content = (
        "You are Quetz-AI, an autonomous Unix software engineering agent.\n"
        f"Working directory: {q_config.WORKSPACE_DIR}\n\n"
        "Guidelines:\n"
        "1. ALWAYS prefer surgical block-editing of existing files using edit_file (replacing only the specific function, class, or code snippet that needs to change) over full file rewrites with write_file. Full rewrites should ONLY be used when creating entirely new files. This keeps edits precise, fast, and preserves the rest of the file contents.\n"
        "2. All file paths are relative to the working directory.\n"
        "3. Respect user rejections ('OPERATION REJECTED BY USER') and ask for clarification if blocked.\n"
        "4. When the entire task is complete, respond with: \"TASK COMPLETED: <summary>\" without calling any tools.\n"
        "5. CRITICAL: You must invoke the actual tools (e.g., write_file, edit_file) to write and modify files on disk. Simply printing code or text in your chat response does NOT modify the filesystem. Do not say 'TASK COMPLETED' until you have successfully executed the tools to save all files to disk and verified them."
    )
    
    if plan:
        prompt_content += f"\n\n### APPROVED ACTION PLAN (Strictly follow this):\n{plan}"
        
    if review_feedback:
        prompt_content += f"\n\n### PREVIOUS REVIEW FEEDBACK (Address these issues):\n{review_feedback}"
    
    context_str = load_context_files()
    if context_str:
        prompt_content += f"\n\nAdditional Workspace Context:{context_str}"
        
    return SystemMessage(content=prompt_content)

def get_llm() -> ChatOllama:
    return ChatOllama(model=q_config.MODEL_NAME, temperature=0.0).bind_tools(tools)

def planner_node(state: AgentState, config: RunnableConfig) -> dict:
    """Interactively draft and approve a plan with the user before executing the rest of the graph."""
    from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
    
    # Check if a plan is already present
    if state.get("plan"):
        return {}
        
    task_text = state.get("task", "")
    print("🧠 Drafting proposed plan...")
    
    planning_sys_prompt = SystemMessage(content=(
        "You are Quetz-AI, a Unix programming agent.\n"
        "Before writing any code or executing tools, you must formulate a structured, "
        "step-by-step action plan to accomplish the user's task.\n"
        "Explain which files you will read, write, or modify, and how you will verify each change.\n"
        "Present your plan under the header '# PROPOSED PLAN'.\n"
        "CRITICAL: Keep your plan structured and high-level. Do NOT output full source code blocks or entire file contents in your plan, as this makes the Coder lazy and causes it to hallucinate that the files are already written. The actual file writing and coding MUST be done by the Coder using tools in the next phase."
    ))
    
    messages = [planning_sys_prompt, HumanMessage(content=task_text)]
    llm = ChatOllama(model=q_config.MODEL_NAME, temperature=0.0)
    
    while True:
        # Capture the conversation history length at the start of this generation/refinement turn
        turn_messages_len = len(messages)
        attempts = 0
        max_attempts = 5
        
        while True:
            response = llm.invoke(messages, config=config)
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
        
        if not q_config.INTERACTIVE_MODE:
            # If not in interactive mode, auto-approve the plan
            break
            
        print("Do you approve this plan? [Y]es, [n]o (abort), or type your feedback to refine it: ", end="", flush=True)
        user_input = input().strip()
        
        if user_input.lower() in ("y", "yes", ""):
            print("\n🚀 Plan approved. Executing agent...")
            break
        elif user_input.lower() in ("n", "no"):
            q_config.play_alert_sound()
            print("\n❌ Task aborted by user.")
            sys.exit(0)
        else:
            # User provided feedback to refine the plan
            q_config.play_alert_sound()
            print("\n🔄 Refining plan based on feedback...")
            messages.append(AIMessage(content=plan_content))
            messages.append(HumanMessage(content=f"Please refine the plan with this feedback: {user_input}"))
            
    return {"plan": plan_content}

def coder_node(state: AgentState, config: RunnableConfig) -> dict:
    current_iter = state.get("iteration", 0)
    if current_iter >= q_config.MAX_ITERATIONS:
        return {
            "messages": [AIMessage(content="TASK COMPLETED: max iterations reached, task may be incomplete.")],
            "iteration": current_iter,
        }

    llm = get_llm()
    
    print("\n🦜 Quetz-AI Coder Thinking...", flush=True)
    response = None
    active_tool_name = None
    has_printed_tool_call = False
    
    sys_prompt = build_system_prompt(
        plan=state.get("plan", ""),
        review_feedback=state.get("review_feedback", "")
    )
    
    # Include the summary in the prompt if it exists
    summary = state.get("summary", "")
    messages_to_send = [sys_prompt]
    
    # Add summary to context if it exists
    if summary:
        messages_to_send.append(SystemMessage(content=f"Recent Activity Summary:\n{summary}"))
    
    # Add all active messages to maintain full short-term context
    recent_messages = state.get("messages", [])
    messages_to_send.extend(recent_messages)
    
    for chunk in llm.stream(messages_to_send, config=config):
        if chunk.content:
            sys.stdout.write(chunk.content)
            sys.stdout.flush()
            
        if chunk.tool_call_chunks:
            for tc_chunk in chunk.tool_call_chunks:
                if tc_chunk.get("name"):
                    active_tool_name = tc_chunk["name"]
                    sys.stdout.write(f"\n  ⚙️  Calling tool: {active_tool_name}(")
                    sys.stdout.flush()
                    has_printed_tool_call = True
                if tc_chunk.get("args"):
                    sys.stdout.write(tc_chunk["args"])
                    sys.stdout.flush()
                    
        if response is None:
            response = chunk
        else:
            response += chunk
            
    if has_printed_tool_call:
        sys.stdout.write(")")
    print(flush=True)
    
    # Robust fallback: check if we have a tool call in text content but not in native tool_calls
    if not response.tool_calls and response.content:
        fallback_calls = parse_tool_call_from_text(response.content)
        if fallback_calls:
            response.tool_calls = fallback_calls
            print(f"\n🔄 Detected tool. Normalizing to native format: {fallback_calls[0]['name']}", flush=True)
            
    return {"messages": [response], "iteration": current_iter + 1}

def should_ask_confirmation(tool_name: str) -> bool:
    return q_config.INTERACTIVE_MODE and tool_name in ("write_file", "edit_file")

def confirm_message(tool_name: str, args: dict) -> bool:
    import difflib
    import pydoc

    print("\n" + "="*40)
    print(f"👉 Proposed Tool Call: {tool_name}")
    if tool_name == "write_file":
        print(f"📄 File: {args.get('file_path')}")
        print(f"📦 Size: {len(args.get('content', ''))} characters")
    elif tool_name == "edit_file":
        print(f"✏️  File: {args.get('file_path')}")
        reps = args.get("replacements", [])
        print(f"🔄 Replacements: {len(reps)}")
    print("="*40)

    while True:
        print("\nOptions: [y] Apply, [n] Reject/Abort, [v] View full content in pager, [d] View diff: ", end="", flush=True)
        answer = input().strip().lower()
        if answer in ("y", "yes"):
            return True
        elif answer in ("n", "no", ""):
            return False
        elif answer in ("v", "view"):
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
                original_lines = []
                new_lines = args.get("content", "").splitlines(keepends=True)
                diff = difflib.unified_diff(
                    original_lines, new_lines,
                    fromfile="/dev/null", tofile=args.get("file_path", "")
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
                        original_lines = content.splitlines(keepends=True)
                        new_lines = modified.splitlines(keepends=True)
                        diff = difflib.unified_diff(
                            original_lines, new_lines,
                            fromfile=args.get("file_path", "") + " (original)",
                            tofile=args.get("file_path", "") + " (modified)"
                        )
                        pydoc.pager("".join(diff))
                    except Exception as e:
                        print(f"Error generating diff: {e}")
                else:
                    print("Original file not found.")

def tools_node(state: AgentState, config: RunnableConfig = None) -> dict:
    last_msg = state["messages"][-1]
    tool_calls = getattr(last_msg, "tool_calls", None) or []
    if not tool_calls:
        return {"messages": []}

    tc = tool_calls[0]  # only one call per turn
    tool_name = tc["name"]
    tool_args = tc["args"]

    if should_ask_confirmation(tool_name) and not confirm_message(tool_name, tool_args):
        q_config.play_alert_sound()
        result_content = "OPERATION REJECTED BY USER. Do not retry the same edit without asking."
        print(f"  ❌ {result_content}\n")
    else:
        try:
            result_content = tool_map[tool_name].invoke(tool_args)
            print(f"  ✅ Tool Result: {result_content}\n")
        except Exception as e:
            result_content = f"Error executing {tool_name}: {e}"
            print(f"  ❌ {result_content}\n")

    result_msg = ToolMessage(
        content=str(result_content),
        tool_call_id=tc["id"],
        name=tool_name,
    )
    return {"messages": [result_msg]}

def reviewer_node(state: AgentState, config: RunnableConfig) -> dict:
    """Takes only the goal (plan), target specs/context, and the actual coder execution history.
    Evaluates whether the implementation met the plan.
    """
    print("\n🔍 Quetz-AI Reviewer evaluating implementation...", flush=True)
    
    plan = state.get("plan", "")
    task = state.get("task", "")
    
    coder_msgs = state.get("messages", [])
    actions_summary = []
    for msg in coder_msgs:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                actions_summary.append(f"Called Tool: {tc['name']} with args: {tc['args']}")
        elif isinstance(msg, ToolMessage):
            content_snippet = str(msg.content)[:300]
            if len(str(msg.content)) > 300:
                content_snippet += "..."
            actions_summary.append(f"Tool Result ({msg.name}): {content_snippet}")
        elif isinstance(msg, AIMessage) and msg.content:
            actions_summary.append(f"Agent response: {msg.content}")

    actions_text = "\n".join(actions_summary)
    
    reviewer_sys_prompt = SystemMessage(content=(
        "You are Quetz-AI Reviewer, an expert QA engineer.\n"
        "Your task is to review if the Coder's actions successfully completed the plan and user request.\n"
        "Review the original task, the approved plan, and the action log. "
        "Do NOT perform any edits yourself.\n"
        "Output 'APPROVED' if the implementation fully satisfies the plan.\n"
        "Otherwise, output 'REJECTED: <reasons for rejection and required changes>'.\n"
        "CRITICAL: Check the Coder Action Log to verify that the Coder actually executed the necessary tools (such as write_file, edit_file, etc.) to apply changes to the disk. If the Coder merely claimed to have completed the task in text/chat but the action log has zero tool calls to write or edit the relevant files, the files do not exist or were not updated on disk. You MUST output 'REJECTED: No tool calls were executed to write the code files on disk.' in this case."
    ))
    
    reviewer_human_prompt = HumanMessage(content=(
        f"Original Task: {task}\n\n"
        f"Approved Action Plan:\n{plan}\n\n"
        f"Coder Action Log:\n{actions_text}\n\n"
        f"Review the implementation now."
    ))
    
    llm = ChatOllama(model=q_config.MODEL_NAME, temperature=0.0)
    
    response = llm.invoke([reviewer_sys_prompt, reviewer_human_prompt], config=config)
    review_text = response.content.strip()
    
    print(f"\n📢 Review Result:\n{review_text}\n", flush=True)
    
    if "APPROVED" in review_text.upper():
        return {"is_approved": True, "review_feedback": ""}
    else:
        q_config.play_alert_sound()
        feedback = review_text
        if "REJECTED:" in review_text.upper():
            idx = review_text.upper().find("REJECTED:")
            feedback = review_text[idx + len("REJECTED:"):].strip()
        return {"is_approved": False, "review_feedback": feedback}

def should_continue(state: AgentState) -> str:
    last_msg = state["messages"][-1]
    has_tools = bool(getattr(last_msg, "tool_calls", None))
    if has_tools and state.get("iteration", 0) <= q_config.MAX_ITERATIONS:
        return "tools"
    return "reviewer"

def should_summarize(state: AgentState) -> str:
    """Check if we should trigger the summarization node."""
    message_count = len(state.get("messages", []))
    # Trigger summarization if we have more than 4 messages
    if message_count > 4:
        return "summarize"
    return "coder"

def summarize_node(state: AgentState, config: RunnableConfig) -> dict:
    """Periodically condense the message history into a concise summary."""
    from langchain_core.messages import RemoveMessage
    messages = state.get("messages", [])
    
    if len(messages) <= 4:
        return {}
        
    # Create a summary of recent activities
    summary_prompt = SystemMessage(content=(
        "You are Quetz-AI, an autonomous Unix software engineering agent.\n"
        "Summarize the recent coding activities in the conversation. Focus on:\n"
        "1. Files that were modified or created\n"
        "2. Key changes made\n"
        "3. Current state of the implementation\n\n"
        "Keep the summary concise (2-3 sentences) and focused on the technical aspects."
    ))
    
    # Limit the messages we pass to the summary to avoid overwhelming the LLM
    recent_messages = messages[-6:]  # Take last 6 messages
    
    llm = ChatOllama(model=q_config.MODEL_NAME, temperature=0.0)
    response = llm.invoke([summary_prompt] + recent_messages, config=config)
    
    # Clear the older messages to free up context
    # Create RemoveMessage directives for all messages except the last 2
    delete_messages = []
    if len(messages) > 2:
        for msg in messages[:-2]:
            if msg.id:
                delete_messages.append(RemoveMessage(id=msg.id))
    
    return {
        "summary": response.content,
        "messages": delete_messages
    }

def should_approve(state: AgentState) -> str:
    if state.get("is_approved"):
        return "finish"
    return "coder"

def build_graph():
    builder = StateGraph(AgentState)
    builder.add_node("planner", planner_node)
    builder.add_node("coder", coder_node)
    builder.add_node("tools", tools_node)
    builder.add_node("reviewer", reviewer_node)
    builder.add_node("summarize", summarize_node)

    builder.add_edge(START, "planner")
    builder.add_edge("planner", "coder")
    
    builder.add_conditional_edges(
        "coder",
        should_continue,
        {"tools": "tools", "reviewer": "reviewer"},
    )
    builder.add_edge("tools", "coder")
    
    # Add the summarize conditional edge
    builder.add_conditional_edges(
        "tools",
        should_summarize,
        {"summarize": "summarize", "coder": "coder"},
    )
    builder.add_edge("summarize", "coder")
    
    builder.add_conditional_edges(
        "reviewer",
        should_approve,
        {"coder": "coder", "finish": END},
    )
    return builder.compile()
