"""Theme asset failures remain observable without interrupting stylesheet creation."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from acw import theme


class ThemeTests(unittest.TestCase):
    def test_draw_failures_log_warnings_and_return_stylesheet(self):
        for theme_name in ("desktop", "metal", "hacker"):
            with self.subTest(theme=theme_name), tempfile.TemporaryDirectory() as tmpdir:
                with patch("acw.theme.ASSETS", Path(tmpdir)), \
                        patch("acw.theme._brushed", side_effect=RuntimeError("boom")) as brushed, \
                        patch("acw.theme._arrow", side_effect=RuntimeError("boom")) as arrow:
                    with self.assertLogs("acw.theme", "WARNING") as captured:
                        style = theme.build_style(theme_name)

                self.assertIsInstance(style, str)
                for placeholder in ("@BRUSHED@", "@ARROW_DOWN@", "@ARROW_UP@",
                                    "@ARROW_DOWN_LIGHT@", "@ARROW_UP_LIGHT@"):
                    self.assertNotIn(placeholder, style)
                self.assertTrue(any("could not be drawn" in message and "brushed.png" in message
                                    for message in captured.output))
                self.assertEqual(5, len(captured.output))
                brushed.assert_called_once_with(Path(tmpdir) / "brushed.png")
                self.assertEqual(4, arrow.call_count)


if __name__ == "__main__":
    unittest.main(verbosity=2)
