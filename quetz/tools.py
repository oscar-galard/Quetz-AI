import os
import subprocess
from langchain_core.tools import tool
from quetz import config

@tool
def list_dir(path: str = ".") -> str:
    """List files and directories relative to the workspace."""
    full = os.path.join(config.WORKSPACE_DIR, path)
    if not os.path.exists(full):
        return f"Error: path does not exist: {path}"
    entries = os.listdir(full)
    return "\n".join(entries) if entries else "Directory is empty."

@tool
def read_file(file_path: str) -> str:
    """Read a text file (max 300 lines, with line numbers)."""
    full = os.path.join(config.WORKSPACE_DIR, file_path)
    if not os.path.isfile(full):
        return f"Error: file not found: {file_path}"
    with open(full, "r", encoding="utf-8") as f:
        lines = f.readlines()
    shown = lines[:300]
    return "\n".join(f"{i+1:4d}: {line}" for i, line in enumerate(shown))

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

tools = [list_dir, read_file, write_file, edit_file, search, create_directory]
tool_map = {t.name: t for t in tools}
