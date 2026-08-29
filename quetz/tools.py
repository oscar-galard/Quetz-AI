from quetz import config
import os
import re
import subprocess
from langchain_core.tools import tool

DEFAULT_READ_LINES = 100
MAX_SYMBOL_LINES = 200
MAX_READ_LINES = 500

def resolve_path(path: str) -> str:
    """Resolve a user-supplied path to an absolute path inside the workspace.

    Accepts both workspace-relative paths (e.g. 'quetz/agent.py') and absolute
    paths that live inside the workspace. Rejects absolute paths that escape the
    workspace to keep the agent contained.
    """
    workspace = os.path.abspath(config.WORKSPACE_DIR)
    if os.path.isabs(path):
        candidate = os.path.normpath(path)
    else:
        candidate = os.path.normpath(os.path.join(workspace, path))

    if not candidate.startswith(workspace + os.sep) and candidate != workspace:
        return ""
    return candidate


def generate_tree(dir_path: str, max_depth: int, current_depth: int = 1, prefix: str = "") -> list[str]:
    """Generates a list of strings representing a directory tree, ignoring noisy directories."""
    if current_depth > max_depth:
        return []
    
    try:
        entries = sorted(os.listdir(dir_path))
    except Exception as e:
        return [f"{prefix}└── Error reading directory: {e}"]
        
    exclude_dirs = {".git", ".venv", "__pycache__", "node_modules", "build", "dist", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".uv"}
    entries = [e for e in entries if e not in exclude_dirs]
    
    lines = []
    for i, entry in enumerate(entries):
        full_path = os.path.join(dir_path, entry)
        is_last = (i == len(entries) - 1)
        connector = "└── " if is_last else "├── "
        
        if os.path.isdir(full_path):
            lines.append(f"{prefix}{connector}{entry}/")
            new_prefix = prefix + ("    " if is_last else "│   ")
            lines.extend(generate_tree(full_path, max_depth, current_depth + 1, new_prefix))
        else:
            lines.append(f"{prefix}{connector}{entry}")
            
    return lines

@tool
def list_dir(path: str = ".", depth: int = 1) -> str:
    """List files and directories relative to the workspace.
    
    If depth > 1, returns a visual tree representation up to the specified depth 
    (excluding noisy folders like .git, .venv, __pycache__).
    """
    full = resolve_path(path)
    if not full:
        return f"Error: path escapes the workspace: {path}"
    if not os.path.exists(full):
        return f"Error: path does not exist: {path}"
        
    if depth > 1:
        tree_lines = generate_tree(full, depth)
        if not tree_lines:
            return "Directory is empty or all contents are ignored."
        return "\n".join(tree_lines)
    else:
        try:
            entries = sorted(os.listdir(full))
        except Exception as e:
            return f"Error listing directory: {e}"
            
        exclude_dirs = {".git", ".venv", "__pycache__", "node_modules", "build", "dist", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".uv"}
        filtered_entries = [e for e in entries if e not in exclude_dirs]
        
        formatted = []
        for entry in filtered_entries:
            if os.path.isdir(os.path.join(full, entry)):
                formatted.append(f"{entry}/")
            else:
                formatted.append(entry)
        return "\n".join(formatted) if formatted else "Directory is empty."

@tool
def read_file(file_path: str, start_line: int = 1, end_line: int = None) -> str:
    """Read specific lines of a text file (with line numbers). Supports reading specific line ranges.
    
    If 'end_line' is not provided, it reads up to 100 lines starting from 'start_line'.
    Prefer read_symbol or search to inspect specific definitions instead of whole files.
    """
    full = resolve_path(file_path)
    if not full:
        return f"Error: file path escapes the workspace: {file_path}"
    if not os.path.isfile(full):
        return f"Error: file not found: {file_path}"
    with open(full, "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    start_idx = max(0, start_line - 1)
    if end_line is None:
        end_idx = min(len(lines), start_idx + DEFAULT_READ_LINES)
    else:
        end_idx = min(len(lines), max(start_idx, end_line))
        
    end_idx = min(end_idx, start_idx + MAX_READ_LINES)
        
    shown = lines[start_idx:end_idx]
    return "".join(f"{start_idx + i + 1:4d}: {line}" for i, line in enumerate(shown))

@tool
def write_file(file_path: str, content: str) -> str:
    """Write (overwrite) a file. Creates parent directories if needed."""
    full = resolve_path(file_path)
    if not full:
        return f"Error: file path escapes the workspace: {file_path}"
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
    full = resolve_path(file_path)
    if not full:
        return f"Error: file path escapes the workspace: {file_path}"
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
def search(pattern: str, path: str = ".", context_lines: int = 0, case_sensitive: bool = False) -> str:
    """Recursively search for a regex pattern using grep.
    
    If context_lines > 0, it includes surrounding lines of context (equivalent to grep -C).
    Automatically excludes common ignore directories like .git, .venv, and __pycache__.
    """
    full = resolve_path(path)
    if not full:
        return f"Error: path escapes the workspace: {path}"
    if not os.path.exists(full):
        return f"Error: path does not exist: {path}"
        
    cmd = ["grep", "-rnI", "--color=never"]
    
    # Auto-exclude noisy directories
    exclude_dirs = [".git", ".venv", "__pycache__", "node_modules", "build", "dist", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".uv"]
    for d in exclude_dirs:
        cmd.append(f"--exclude-dir={d}")
        
    if not case_sensitive:
        cmd.append("-i")
        
    if context_lines > 0:
        cmd.append(f"-C{context_lines}")
        
    cmd.extend([pattern, full])
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=10
        )
        output = result.stdout.strip()
        return output if output else "No matches found."
    except Exception as e:
        return f"Error running grep: {e}"

@tool
def create_directory(path: str) -> str:
    """Create a directory (equivalent to mkdir -p)."""
    full = resolve_path(path)
    if not full:
        return f"Error: path escapes the workspace: {path}"
    os.makedirs(full, exist_ok=True)
    return f"OK: directory ready: {path}"

@tool
def read_symbol(file_path: str, symbol: str) -> str:
    """Read a specific function, class, or definition block from a file.
    
    The 'symbol' parameter is the name of the function (e.g. 'get_random_moves') 
    or class (e.g. 'Pokemon') to read.
    """
    full = resolve_path(file_path)
    if not full:
        return f"Error: file path escapes the workspace: {file_path}"
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
        
    if len(block_lines) > MAX_SYMBOL_LINES:
        block_lines = block_lines[:MAX_SYMBOL_LINES]
        block_lines.append(f"... truncated at {MAX_SYMBOL_LINES} lines; symbol block is larger. Use read_file for a specific range.")
        
    return "".join(block_lines)

tools = [list_dir, read_file, write_file, edit_file, search, create_directory, read_symbol]
tool_map = {t.name: t for t in tools}

read_only_tools = [list_dir, read_file, search, read_symbol]
read_tool_map = {t.name: t for t in read_only_tools}
