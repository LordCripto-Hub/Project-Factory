#!/usr/bin/env python3
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MobileModalViewportTests(unittest.TestCase):
    def test_shared_adapter_tracks_keyboard_viewport(self):
        source = (ROOT / "bin" / "visual-viewport.js").read_text(encoding="utf-8")
        self.assertIn("--mp-visible-height", source)
        self.assertIn("--mp-visible-offset", source)
        self.assertIn("visualViewport.addEventListener('resize'", source)
        self.assertIn("visualViewport.addEventListener('scroll'", source)
        self.assertIn("requestAnimationFrame", source)

    def test_board_and_graph_load_adapter_once(self):
        for name in ("todos.html", "terminal-graph.html"):
            page = (ROOT / "bin" / name).read_text(encoding="utf-8")
            self.assertEqual(page.count('/assets/visual-viewport.js'), 1, name)

    def test_mobile_contract_uses_visible_height_and_safe_controls(self):
        css = (ROOT / "bin" / "mypeople-ui.css").read_text(encoding="utf-8")
        self.assertIn("--mp-visible-height", css)
        self.assertIn("100dvh", css)
        self.assertIn("min-width:24px", css.replace(" ", ""))
        self.assertIn("min-height:24px", css.replace(" ", ""))
        self.assertIn('input[type="checkbox"]', css)
        self.assertIn(".navlink,", css)
        self.assertIn("font-size:16px", css.replace(" ", ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
