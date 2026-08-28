import os
import sys
import json
import re
from typing import Annotated, TypedDict
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_ollama import ChatOllama
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from quetz import config
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
    messages: Annotated[list[BaseMessage], add_messages]
    iteration: int

def load_context_files() -> str:
    """Detect and load instructions/context from workspace markdown files if they exist."""
    if config.NO_CONTEXT:
        return ""
    
    target_files = ["specs.md", "skills.md", "agents.md", "instructions.md"]
    context_parts = []
    
    for filename in target_files:
        path = os.path.join(config.WORKSPACE_DIR, filename)
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                if content:
                    context_parts.append(f"--- CONTEXT FROM {filename} ---\n{content}")
            except Exception as e:
                if config.VERBOSE:
                    print(f"Error reading context file {filename}: {e}")
                    
    if context_parts:
        return "\n\n" + "\n\n".join(context_parts)
    return ""

def build_system_prompt() -> SystemMessage:
    prompt_content = (
        "You are Quetz-AI, an autonomous Unix software engineering agent.\n"
        f"Working directory: {config.WORKSPACE_DIR}\n\n"
        "Guidelines:\n"
        "1. Prefer editing existing files with edit_file over full rewrites with write_file.\n"
        "2. All file paths are relative to the working directory.\n"
        "3. Respect user rejections ('OPERATION REJECTED BY USER') and ask for clarification if blocked.\n"
        "4. When the entire task is complete, respond with: \"TASK COMPLETED: <summary>\" without calling any tools."
    )
    
    context_str = load_context_files()
    if context_str:
        prompt_content += f"\n\nAdditional Workspace Context:{context_str}"
        
    return SystemMessage(content=prompt_content)

def get_llm() -> ChatOllama:
    return ChatOllama(model=config.MODEL_NAME, temperature=0.0).bind_tools(tools)

def agent_node(state: AgentState) -> dict:
    current_iter = state.get("iteration", 0)
    if current_iter >= config.MAX_ITERATIONS:
        return {
            "messages": [AIMessage(content="TASK COMPLETED: max iterations reached, task may be incomplete.")],
            "iteration": current_iter,
        }

    llm = get_llm()
    
    print("\n🦜 Quetz-AI Thinking...", flush=True)
    response = None
    active_tool_name = None
    has_printed_tool_call = False
    
    for chunk in llm.stream([build_system_prompt(), *state["messages"]]):
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
    return config.INTERACTIVE_MODE and tool_name in ("write_file", "edit_file")

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
                full_path = os.path.join(config.WORKSPACE_DIR, args.get("file_path", ""))
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
            full_path = os.path.join(config.WORKSPACE_DIR, args.get("file_path", ""))
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

def tools_node(state: AgentState) -> dict:
    last_msg = state["messages"][-1]
    tool_calls = getattr(last_msg, "tool_calls", None) or []
    if not tool_calls:
        return {"messages": []}

    tc = tool_calls[0]  # only one call per turn
    tool_name = tc["name"]
    tool_args = tc["args"]

    if should_ask_confirmation(tool_name) and not confirm_message(tool_name, tool_args):
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

def should_continue(state: AgentState) -> str:
    last_msg = state["messages"][-1]
    has_tools = bool(getattr(last_msg, "tool_calls", None))
    if has_tools and state.get("iteration", 0) <= config.MAX_ITERATIONS:
        return "tools"
    return "finish"

def build_graph():
    builder = StateGraph(AgentState)
    builder.add_node("agent", agent_node)
    builder.add_node("tools", tools_node)

    builder.add_edge(START, "agent")
    builder.add_conditional_edges(
        "agent",
        should_continue,
        {"tools": "tools", "finish": END},
    )
    builder.add_edge("tools", "agent")
    return builder.compile()
