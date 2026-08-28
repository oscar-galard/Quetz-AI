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

if __name__ == "__main__":
    unittest.main()
