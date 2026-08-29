import unittest
from unittest.mock import patch, MagicMock

class TestBanner(unittest.TestCase):
    @patch("builtins.print")
    def test_print_banner(self, mock_print):
        from quetz.cli import print_banner, BANNER
        print_banner()
        mock_print.assert_called_once_with(BANNER)


class TestBannerGradient(unittest.TestCase):
    def test_bright_green_predominates(self):
        import re
        from collections import Counter
        from quetz.cli import _BANNER_QUETZ, _GREENS, _gradient_green

        # Escape codes considered "bright green": 46 and 82.
        bright_codes = {c for c in _GREENS if c.endswith(";46m") or c.endswith(";82m")}
        counts = Counter(_gradient_green(r, c)
                         for r, row in enumerate(_BANNER_QUETZ)
                         for c, ch in enumerate(row) if ch.strip())
        total = sum(counts.values())
        bright = sum(n for code, n in counts.items() if code in bright_codes)
        # Bright green must be the clear majority of the block.
        self.assertGreater(100 * bright / total, 70)


class TestGracefulInterrupt(unittest.TestCase):
    @patch("quetz.cli.config")
    @patch("quetz.cli.print_banner")
    @patch("quetz.cli.set_container")
    @patch("quetz.cli.build_graph")
    @patch("quetz.cli.make_container")
    def test_interrupt_message(self, mock_mc, mock_bg, mock_sc, mock_pb, mock_cfg):
        import sys
        from quetz.cli import main

        app = MagicMock()
        app.stream.side_effect = KeyboardInterrupt()
        mock_bg.return_value = app
        mock_cfg.WORKSPACE_DIR = "/tmp"
        mock_cfg.INTERACTIVE_MODE = False
        mock_cfg.DEBUG_MODE = False
        mock_cfg.MODE = "local"
        mock_cfg.MODEL_NAME = "m"

        argv = ["quetz-ai", "do the thing", "-d", ".", "-a"]
        with patch("sys.argv", argv), self.assertRaises(SystemExit) as cm:
            main()
        self.assertEqual(cm.exception.code, 130)


if __name__ == "__main__":
    unittest.main()
