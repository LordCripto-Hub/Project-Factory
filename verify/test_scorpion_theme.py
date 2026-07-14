#!/usr/bin/env python3
"""Shared tactical dark/gold interface contract."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ScorpionThemeContract(unittest.TestCase):
    def test_shared_original_palette_and_signature(self):
        css = (ROOT / "bin" / "mypeople-ui.css").read_text(encoding="utf-8").lower()
        for token in ("--soot:#080807", "--charcoal:#12110e", "--armor:#1c1a14", "--gold:#f2c230", "--ember:#ff8a1f", "--bone:#f4f0df"):
            self.assertIn(token, css.replace(" ", ""))
        self.assertIn("mission-rail", css)
        self.assertIn("evidence-card", css)

    def test_every_operator_surface_loads_shared_theme_and_voice(self):
        for name in ("todos.html", "wall.html", "terminal-graph.html", "dashboard.html", "terminal.html"):
            html = (ROOT / "bin" / name).read_text(encoding="utf-8")
            self.assertIn("/assets/mypeople-ui.css", html, name)
            self.assertIn("/assets/voice-dock.js", html, name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
