#!/usr/bin/env python3
"""Static regression contract for active MyPeople visual surfaces."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ActiveSurfaceVisualContract(unittest.TestCase):
    def setUp(self):
        self.css = (ROOT / "bin" / "mypeople-ui.css").read_text(encoding="utf-8")

    def test_active_routes_use_shared_theme_and_viewport(self):
        for name in ("todos.html", "dashboard.html", "terminal-graph.html"):
            html = (ROOT / "bin" / name).read_text(encoding="utf-8")
            with self.subTest(name=name):
                self.assertIn("/assets/mypeople-ui.css", html)
                self.assertIn('name="viewport"', html)

    def test_graph_keeps_its_scoped_canvas_layer(self):
        html = (ROOT / "bin" / "terminal-graph.html").read_text(encoding="utf-8")
        self.assertIn("/assets/graph-canvas.css", html)
        self.assertIn("canvasToolbar", html)

    def test_shared_theme_has_keyboard_focus_and_reduced_motion_guards(self):
        compact = self.css.replace(" ", "")
        self.assertIn("button:focus-visible", compact)
        self.assertIn("@media(prefers-reduced-motion:reduce)", compact)
        self.assertIn("scroll-behavior:auto", compact)

    def test_semantic_surface_and_state_contract_is_present(self):
        compact = self.css.replace(" ", "")
        for marker in ("--surface-0:var(--soot)", "--text-primary:var(--bone)", "--state-working:var(--ember)", "--state-done:var(--jade)"):
            self.assertIn(marker, compact)


if __name__ == "__main__":
    unittest.main(verbosity=2)
