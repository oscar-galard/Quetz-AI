import unittest
from unittest.mock import patch

class TestBanner(unittest.TestCase):
    @patch("builtins.print")
    def test_print_banner(self, mock_print):
        from quetz.cli import print_banner, BANNER
        print_banner()
        mock_print.assert_called_once_with(BANNER)

if __name__ == "__main__":
    unittest.main()
