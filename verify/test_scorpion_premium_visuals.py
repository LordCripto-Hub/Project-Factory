#!/usr/bin/env python3
"""Premium Scorpion presentation contracts with frozen runtime boundaries."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
UI_FILES = (
    "todos.html",
    "dashboard.html",
    "terminal-graph.html",
    "terminal.html",
)


class PremiumScorpionVisualContract(unittest.TestCase):
    def setUp(self):
        self.css = (ROOT / "bin" / "mypeople-ui.css").read_text(encoding="utf-8")

    def test_canonical_scorpion_palette_and_semantic_system_remain_local(self):
        compact = re.sub(r"\s+", "", self.css).lower()
        for token in (
            "--soot:#080807",
            "--charcoal:#12110e",
            "--armor:#1c1a14",
            "--gold:#f2c230",
            "--ember:#ff8a1f",
            "--bone:#f4f0df",
            "--crimson:#dc493f",
            "--jade:#67b279",
            "--space-1:4px",
            "--radius-panel:14px",
        ):
            self.assertIn(token, compact)
        self.assertNotRegex(self.css, r"https?://|@import\s+url")

    def test_accessibility_and_responsive_modes_are_explicit(self):
        self.assertIn("@media (max-width: 720px)", self.css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", self.css)
        self.assertIn("@media (forced-colors: active)", self.css)
        self.assertIn(":focus-visible", self.css)
        self.assertIn("min-height: 38px", self.css)

    def test_every_operator_surface_keeps_the_shared_presentation_boundary(self):
        for filename in UI_FILES:
            page = (ROOT / "bin" / filename).read_text(encoding="utf-8")
            self.assertEqual(page.count('/assets/mypeople-ui.css'), 1, filename)

    def test_visual_capture_fixture_is_sanitized_and_loopback_only(self):
        capture = (ROOT / "verify" / "capture_scorpion_visuals.js").read_text(encoding="utf-8")
        self.assertIn("sanitized-scorpion-v1", capture)
        self.assertIn('server.listen(0, "127.0.0.1"', capture)
        self.assertIn("externalRequests", capture)
        self.assertNotIn("QUEUE_SECRET", capture)
        self.assertNotIn("OPENAI_API_KEY", capture)

    def test_visual_capture_targets_the_unified_hud_cards(self):
        capture = (ROOT / "verify" / "capture_scorpion_visuals.js").read_text(encoding="utf-8")
        self.assertIn("#telemetryCards .combat-card", capture)
        self.assertNotIn("#agentsTable", capture)


if __name__ == "__main__":
    unittest.main(verbosity=2)
