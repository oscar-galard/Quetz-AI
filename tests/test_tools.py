import unittest
import os
from unittest.mock import patch, mock_open
from quetz import config
from quetz.tools import read_file, read_symbol

class TestTools(unittest.TestCase):
    def setUp(self):
        self.original_workspace = config.WORKSPACE_DIR
        config.WORKSPACE_DIR = "."

    def tearDown(self):
        config.WORKSPACE_DIR = self.original_workspace

    @patch("os.path.isfile", return_value=True)
    def test_read_file_range(self, mock_isfile):
        file_content = "\n".join(f"Line {i}" for i in range(1, 20))
        with patch("builtins.open", mock_open(read_data=file_content)):
            # Test reading lines 3 to 6
            result = read_file.invoke({"file_path": "test.txt", "start_line": 3, "end_line": 6})
            lines = result.rstrip().split("\n")
            self.assertEqual(len(lines), 4)
            self.assertEqual(lines[0], "   3: Line 3")
            self.assertEqual(lines[3], "   6: Line 6")

            # Test reading starting at 5 with default max 300 lines (only 15 lines total left)
            result_default = read_file.invoke({"file_path": "test.txt", "start_line": 5})
            lines_default = result_default.rstrip().split("\n")
            self.assertEqual(len(lines_default), 15) # from index 4 to 18 (lines 5 to 19)
            self.assertEqual(lines_default[0], "   5: Line 5")

    @patch("os.path.isfile", return_value=True)
    def test_read_symbol_function(self, mock_isfile):
        file_content = (
            "import os\n"
            "\n"
            "def target_func(a, b):\n"
            "    # This is a comment\n"
            "    c = a + b\n"
            "    return c\n"
            "\n"
            "def other_func():\n"
            "    return None\n"
        )
        with patch("builtins.open", mock_open(read_data=file_content)):
            result = read_symbol.invoke({"file_path": "test.py", "symbol": "target_func"})
            self.assertIn("def target_func(a, b):", result)
            self.assertIn("c = a + b", result)
            self.assertNotIn("def other_func():", result)

    @patch("os.path.isfile", return_value=True)
    def test_read_symbol_class(self, mock_isfile):
        file_content = (
            "class MyClass:\n"
            "    def __init__(self):\n"
            "        self.x = 10\n"
            "\n"
            "    def get_x(self):\n"
            "        return self.x\n"
            "\n"
            "class OtherClass:\n"
            "    pass\n"
        )
        with patch("builtins.open", mock_open(read_data=file_content)):
            result = read_symbol.invoke({"file_path": "test.py", "symbol": "MyClass"})
            self.assertIn("class MyClass:", result)
            self.assertIn("def get_x(self):", result)
            self.assertNotIn("class OtherClass:", result)

if __name__ == "__main__":
    unittest.main()
