import unittest
import os
import importlib
from unittest.mock import patch
from quetz import config

class TestConfigMapping(unittest.TestCase):
    def setUp(self):
        # Save original environment variables
        self.original_env = dict(os.environ)

    def tearDown(self):
        # Restore original environment variables
        os.environ.clear()
        os.environ.update(self.original_env)
        import importlib
        importlib.reload(config)

    def test_langsmith_mapping(self):
        # Clean potential existing langchain/langsmith variables from env
        for key in ["LANGCHAIN_TRACING_V2", "LANGCHAIN_API_KEY", "LANGCHAIN_PROJECT", "LANGCHAIN_ENDPOINT",
                    "LANGSMITH_TRACING", "LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "LANGSMITH_ENDPOINT"]:
            os.environ.pop(key, None)

        # Set LANGSMITH_* variables
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGSMITH_API_KEY"] = "test-api-key"
        os.environ["LANGSMITH_PROJECT"] = "test-project"
        os.environ["LANGSMITH_ENDPOINT"] = "https://api.test.smith.com"

        # Patch os.path.exists so that reload does not load the actual .env file from disk
        with patch("os.path.exists", return_value=False):
            importlib.reload(config)

        # Verify that LANGCHAIN_* equivalents were set correctly
        self.assertEqual(os.environ.get("LANGCHAIN_TRACING_V2"), "true")
        self.assertEqual(os.environ.get("LANGCHAIN_API_KEY"), "test-api-key")
        self.assertEqual(os.environ.get("LANGCHAIN_PROJECT"), "test-project")
        self.assertEqual(os.environ.get("LANGCHAIN_ENDPOINT"), "https://api.test.smith.com")

    @patch("os.path.exists", return_value=True)
    def test_load_dotenv_inline_comments(self, mock_exists):
        # Clear specific env vars
        for key in ["VAR_SIMPLE", "VAR_WITH_COMMENT", "VAR_WITH_QUOTED", "VAR_WITH_QUOTED_HASH", "VAR_WITH_SINGLE_QUOTED"]:
            os.environ.pop(key, None)

        dotenv_content = (
            "VAR_SIMPLE=value_simple\n"
            "VAR_WITH_COMMENT=value_comment # this is a comment\n"
            "VAR_WITH_QUOTED=\"quoted_value\" # comment after quote\n"
            "VAR_WITH_QUOTED_HASH=\"quoted#hash\"\n"
            "VAR_WITH_SINGLE_QUOTED='single_quoted' # comment\n"
        )

        with patch("builtins.open", unittest.mock.mock_open(read_data=dotenv_content)):
            config.load_dotenv()

        self.assertEqual(os.environ.get("VAR_SIMPLE"), "value_simple")
        self.assertEqual(os.environ.get("VAR_WITH_COMMENT"), "value_comment")
        self.assertEqual(os.environ.get("VAR_WITH_QUOTED"), "quoted_value")
        self.assertEqual(os.environ.get("VAR_WITH_QUOTED_HASH"), "quoted#hash")
        self.assertEqual(os.environ.get("VAR_WITH_SINGLE_QUOTED"), "single_quoted")

    @patch("os.path.exists")
    def test_load_dotenv_project_root_fallback(self, mock_exists):
        # We want first check (.env) to fail, and second check (project_root/.env) to succeed
        mock_exists.side_effect = lambda path: path.endswith("quetz-ai/.env") or path.endswith("quetz-ai\\.env")

        # Clear specific env var
        os.environ.pop("VAR_FALLBACK", None)

        dotenv_content = "VAR_FALLBACK=success\n"

        with patch("builtins.open", unittest.mock.mock_open(read_data=dotenv_content)):
            config.load_dotenv()

        self.assertEqual(os.environ.get("VAR_FALLBACK"), "success")

    @patch("shutil.which", return_value="mpv")
    @patch("subprocess.Popen")
    @patch("os.path.exists")
    def test_play_alert_sound_triggers_player(self, mock_exists, mock_popen, mock_which):
        # Setup mock exists to return True for the alert candidate
        mock_exists.side_effect = lambda path: "alert/alert.mp3" in path or "alert\\alert.mp3" in path
        
        # Trigger function
        config.play_alert_sound()
        
        # Verify it found and tried to run the player
        mock_popen.assert_called_once()
        called_args = mock_popen.call_args[0][0]
        self.assertEqual(called_args[0], "mpv")
        self.assertTrue(called_args[-1].endswith("alert.mp3"))

if __name__ == "__main__":
    unittest.main()
