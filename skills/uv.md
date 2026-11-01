---
skill: uv
layer: infrastructure
tags: [python, uv, packaging, dependencies, install, add, pip]
---

## uv commands (NOT pip)

**NEVER use `pip install`.** Use `uv` for all Python package management.

| What you want | Command |
|---------------|---------|
| Add a dependency | `uv add fastapi uvicorn` |
| Add a dev dependency | `uv add --dev pytest ruff` |
| Install from lockfile | `uv sync` |
| Run a Python script | `uv run python script.py` |
| Run a module | `uv run python -m pytest` |
| Initialize a project | `uv init --package --name my-project` |
| Remove a dependency | `uv remove fastapi` |
| Show installed packages | `uv pip list` |

## Common mistakes

- ❌ `uv install fastapi` — WRONG, `install` is not a uv command
- ❌ `pip install fastapi` — WRONG, breaks system Python
- ❌ `python -m pip install fastapi` — WRONG
- ✅ `uv add fastapi` — correct

## Acceptance commands

```bash
# Check a package is importable
uv run python -c 'import fastapi'

# Run tests
uv run python -m pytest -q

# Run a script
uv run python main.py
```

## Project structure

```
project/
├── pyproject.toml    # dependencies listed here
├── uv.lock           # lockfile (auto-generated)
├── .venv/            # virtual environment (auto-created)
└── src/
    └── app/
        └── __init__.py
```
