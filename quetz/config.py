import os

# Default values
WORKSPACE_DIR = "."
MAX_ITERATIONS = 25
INTERACTIVE_MODE = False
VERBOSE = False
MODEL_NAME = "qwen3-coder_IQ4XS:latest"
NO_CONTEXT = False

def load_dotenv(dotenv_path: str = ".env") -> None:
    """A minimal, dependency-free helper to load environmental variables from a .env file."""
    if os.path.exists(dotenv_path):
        with open(dotenv_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    os.environ[key] = val

# Load env variables on startup
load_dotenv()
MODEL_NAME = os.environ.get("QUETZ_MODEL", MODEL_NAME)

# Map LANGSMITH_* environment variables to LANGCHAIN_* equivalents for LangChain/LangSmith SDK compatibility
if os.environ.get("LANGSMITH_TRACING", "").lower() == "true":
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
if "LANGSMITH_API_KEY" in os.environ:
    os.environ.setdefault("LANGCHAIN_API_KEY", os.environ["LANGSMITH_API_KEY"])
if "LANGSMITH_PROJECT" in os.environ:
    os.environ.setdefault("LANGCHAIN_PROJECT", os.environ["LANGSMITH_PROJECT"])
if "LANGSMITH_ENDPOINT" in os.environ:
    os.environ.setdefault("LANGCHAIN_ENDPOINT", os.environ["LANGSMITH_ENDPOINT"])
