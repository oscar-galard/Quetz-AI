import os

# Default values
WORKSPACE_DIR = "."
MAX_ITERATIONS = 25
INTERACTIVE_MODE = False
VERBOSE = False
MODE = "local"
LOCAL_MODEL = "qwen3-coder_IQ4XS:latest"
CLOUD_MODEL = "gpt-4o"
CLOUD_API_KEY = ""
CLOUD_BASE_URL = None
MODEL_NAME = "qwen3-coder_IQ4XS:latest"
NO_CONTEXT = False
DEBUG_MODE = False
NO_REVIEWER = False

def load_dotenv(dotenv_path: str = None) -> None:
    """A minimal, dependency-free helper to load environmental variables from a .env file."""
    paths_to_check = []
    if dotenv_path:
        paths_to_check.append(os.path.abspath(dotenv_path))
    else:
        paths_to_check.append(os.path.abspath(".env"))
        try:
            # Find project root relative to this file
            config_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(config_dir)
            paths_to_check.append(os.path.abspath(os.path.join(project_root, ".env")))
        except Exception:
            pass

    seen = set()
    for path in paths_to_check:
        if path in seen:
            continue
        seen.add(path)
        
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, val = line.split("=", 1)
                        key = key.strip()
                        val = val.strip()
                        
                        # Handle inline comments safely
                        if val.startswith('"'):
                            end_quote = val.find('"', 1)
                            if end_quote != -1:
                                val = val[:end_quote+1]
                        elif val.startswith("'"):
                            end_quote = val.find("'", 1)
                            if end_quote != -1:
                                val = val[:end_quote+1]
                        else:
                            if "#" in val:
                                val = val.split("#", 1)[0].strip()
                                
                        val = val.strip().strip("'\"")
                        os.environ[key] = val

# Load env variables on startup
load_dotenv()

MODE = os.environ.get("MODE", "local").lower()
LOCAL_MODEL = os.environ.get("LOCAL_MODEL", os.environ.get("QUETZ_MODEL", "qwen3-coder_IQ4XS:latest"))
CLOUD_MODEL = os.environ.get("CLOUD_MODEL", "gpt-4o")
CLOUD_API_KEY = os.environ.get("CLOUD_API_KEY", "")
CLOUD_BASE_URL = os.environ.get("CLOUD_BASE_URL", "").strip() or None

if MODE == "cloud":
    MODEL_NAME = CLOUD_MODEL
else:
    MODEL_NAME = LOCAL_MODEL

# Map LANGSMITH_* environment variables to LANGCHAIN_* equivalents for LangChain/LangSmith SDK compatibility
if os.environ.get("LANGSMITH_TRACING", "").lower() == "true":
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
if "LANGSMITH_API_KEY" in os.environ:
    os.environ.setdefault("LANGCHAIN_API_KEY", os.environ["LANGSMITH_API_KEY"])
if "LANGSMITH_PROJECT" in os.environ:
    os.environ.setdefault("LANGCHAIN_PROJECT", os.environ["LANGSMITH_PROJECT"])
if "LANGSMITH_ENDPOINT" in os.environ:
    os.environ.setdefault("LANGCHAIN_ENDPOINT", os.environ["LANGSMITH_ENDPOINT"])

def play_alert_sound() -> None:
    """Attempt to play 'alert.mp3' from the project's alert directory using system audio players.
    Falls back to a terminal beep on failure or if no player/file is found.
    """
    import subprocess
    import shutil

    sound_file = None
    try:
        config_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(config_dir)
        
        # 1. Check project_root/alert/alert.mp3
        candidate_1 = os.path.join(project_root, "alert", "alert.mp3")
        # 2. Check project_root/alert.mp3
        candidate_2 = os.path.join(project_root, "alert.mp3")
        
        if os.path.exists(candidate_1):
            sound_file = candidate_1
        elif os.path.exists(candidate_2):
            sound_file = candidate_2
    except Exception:
        pass

    if not sound_file or not os.path.exists(sound_file):
        # Fallback terminal beep
        print("\a", end="", flush=True)
        return

    # List of players to try
    players = [
        ["mpv", "--no-terminal", "--no-video"],
        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"],
        ["mpg123", "-q"],
        ["play", "-q"]
    ]

    for player in players:
        if shutil.which(player[0]):
            try:
                subprocess.Popen(player + [sound_file], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except Exception:
                pass

    # Fallback terminal beep
    print("\a", end="", flush=True)
