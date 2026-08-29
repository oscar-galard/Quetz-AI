from quetz import config
import os
import re
import subprocess
from langchain_core.tools import tool

@tool
def list_dir(path: str = ".") -> str:
    """List files and directories relative to the workspace."""
    full = os.path.join(config.WORKSPACE_DIR, path)
    if not os.path.exists(full):
        return f"Error: path does not exist: {path}"
    entries = os.listdir(full)
    return "\n".join(entries) if entries else "Directory is empty."

@tool
def read_file(file_path: str, start_line: int = 1, end_line: int = None) -> str:
    """Read specific lines of a text file (with line numbers). Supports reading specific line ranges.
    
    If 'end_line' is not provided, it reads up to 300 lines starting from 'start_line'.
    """
    full = os.path.join(config.WORKSPACE_DIR, file_path)
    if not os.path.isfile(full):
        return f"Error: file not found: {file_path}"
    with open(full, "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    start_idx = max(0, start_line - 1)
    if end_line is None:
        end_idx = min(len(lines), start_idx + 300)
    else:
        end_idx = min(len(lines), max(start_idx, end_line))
        
    shown = lines[start_idx:end_idx]
    return "".join(f"{start_idx + i + 1:4d}: {line}" for i, line in enumerate(shown))

@tool
def write_file(file_path: str, content: str) -> str:
    """Write (overwrite) a file. Creates parent directories if needed."""
    full = os.path.join(config.WORKSPACE_DIR, file_path)
    parent = os.path.dirname(full)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)
    return f"OK: wrote {file_path} ({len(content)} bytes)"

@tool
def edit_file(file_path: str, replacements: list[dict]) -> str:
    """Apply exact find/replace edits to a file.

    Each replacement is a dict: {"find": "...", "replace": "..."}
    The "find" string must occur exactly once in the file.
    """
    full = os.path.join(config.WORKSPACE_DIR, file_path)
    if not os.path.isfile(full):
        return f"Error: file not found: {file_path}"

    with open(full, "r", encoding="utf-8") as f:
        original = f.read()

    modified = original
    applied = 0
    for rep in replacements:
        find_text = rep.get("find", "")
        replace_text = rep.get("replace", "")
        if not find_text:
            return "Error: 'find' cannot be empty."
        count = modified.count(find_text)
        if count == 0:
            return f"Error: '{find_text[:80]}...' not found in {file_path}."
        if count > 1:
            return f"Error: '{find_text[:80]}...' appears {count} times. Provide more context."
        modified = modified.replace(find_text, replace_text, 1)
        applied += 1

    with open(full, "w", encoding="utf-8") as f:
        f.write(modified)

    return f"OK: applied {applied} replacement(s) to {file_path}"

@tool
def search(pattern: str, path: str = ".") -> str:
    """Recursively search for a regex pattern using grep."""
    full = os.path.join(config.WORKSPACE_DIR, path)
    if not os.path.exists(full):
        return f"Error: path does not exist: {path}"
    try:
        result = subprocess.run(
            ["grep", "-rnI", "--color=never", pattern, full],
            capture_output=True, text=True, timeout=10
        )
        output = result.stdout.strip()
        return output if output else "No matches found."
    except Exception as e:
        return f"Error running grep: {e}"

@tool
def create_directory(path: str) -> str:
    """Create a directory (equivalent to mkdir -p)."""
    full = os.path.join(config.WORKSPACE_DIR, path)
    os.makedirs(full, exist_ok=True)
    return f"OK: directory ready: {path}"

@tool
def read_symbol(file_path: str, symbol: str) -> str:
    """Read a specific function, class, or definition block from a file.
    
    The 'symbol' parameter is the name of the function (e.g. 'get_random_moves') 
    or class (e.g. 'Pokemon') to read.
    """
    full = os.path.join(config.WORKSPACE_DIR, file_path)
    if not os.path.isfile(full):
        return f"Error: file not found: {file_path}"
        
    with open(full, "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    # Build strict regexes for function/class definitions
    symbol_patterns = [
        re.compile(rf"^\s*(?:def|class)\s+{re.escape(symbol)}\b"),
        re.compile(rf"\b{re.escape(symbol)}\b\s*=")  # variable assignment
    ]
    
    start_line = -1
    for pattern in symbol_patterns:
        for i, line in enumerate(lines):
            if pattern.search(line):
                start_line = i
                break
        if start_line != -1:
            break
            
    if start_line == -1:
        # Fallback to general substring search
        for i, line in enumerate(lines):
            if symbol in line and ("def " in line or "class " in line or "=" in line):
                start_line = i
                break
                
    if start_line == -1:
        return f"Error: symbol '{symbol}' not found in {file_path}."
        
    symbol_line = lines[start_line]
    indent_match = re.match(r"^(\s*)", symbol_line)
    symbol_indent = len(indent_match.group(1)) if indent_match else 0
    
    block_lines = [f"{start_line + 1:4d}: {symbol_line}"]
    
    # Read subsequent lines until indentation is less than or equal to symbol_indent
    for i in range(start_line + 1, len(lines)):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            block_lines.append(f"{i + 1:4d}: {line}")
            continue
            
        indent_match = re.match(r"^(\s*)", line)
        line_indent = len(indent_match.group(1)) if indent_match else 0
        
        # Block ends if we return to the same or lower indentation level,
        # unless it is a comment line.
        if line_indent <= symbol_indent and not stripped.startswith("#"):
            break
            
        block_lines.append(f"{i + 1:4d}: {line}")
        
    return "".join(block_lines)

tools = [list_dir, read_file, write_file, edit_file, search, create_directory, read_symbol]
tool_map = {t.name: t for t in tools}

read_only_tools = [list_dir, read_file, search, read_symbol]
read_tool_map = {t.name: t for t in read_only_tools}
