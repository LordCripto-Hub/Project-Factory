#!/usr/bin/env python3
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class GraphCommandCanvasContract(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / "bin" / "terminal-graph.html").read_text(encoding="utf-8")
        self.graph_css = (ROOT / "bin" / "graph-canvas.css").read_text(encoding="utf-8")
        self.css = (ROOT / "bin" / "mypeople-ui.css").read_text(encoding="utf-8")
        self.server = (ROOT / "bin" / "todo-server.py").read_text(encoding="utf-8")

    def test_shell_contains_command_canvas_regions_and_labels(self):
        for marker in (
            "MyPeople",
            "Graph",
            "Mission",
            "Fleet",
            "Attention",
            "Execution",
            "Boss",
            "Nightwatch",
            "layerRail",
            "Agents",
            "Tasks",
            "Evidence",
            "Decisions",
            "Terminals",
            "inspector",
            "minimap",
            "canvasToolbar",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)

    def test_existing_canonical_controls_remain_in_the_graph_page(self):
        for marker in (
            "/assets/mypeople-ui.css",
            "/assets/graph-canvas.css",
            "'/todo/terminal?agent='",
            "target='_blank'",
            "rel='noopener'",
            "'/todo/update'",
            "openCard(t.id",
            "window.__graph",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)

    def test_graph_does_not_import_collaboration_runtime_concepts(self):
        lowered = self.html.lower()
        for marker in ("colmeia", "invite", "presence", "chat", "external agent", "room"):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, lowered)

    def test_shared_tactical_tokens_are_available_to_the_graph(self):
        for marker in (
            "--soot",
            "--charcoal",
            "--armor",
            "--gold",
            "--ember",
            "--bone",
            "--ash",
            "--crimson",
            "--jade",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.css)
                self.assertIn(marker, self.graph_css)

    def test_graph_stylesheet_is_served_by_the_same_origin_server(self):
        self.assertIn('p=="/assets/graph-canvas.css"', self.server)
        self.assertIn('graph-canvas.css', self.server)

    def test_impeccable_direction_contract_is_embedded_in_the_surface(self):
        for marker in (
            "THESIS:",
            "OWN-WORLD:",
            "FIRST VIEWPORT:",
            "impeccable-graph-polish",
            "unreviewed and undocumented is unfinished",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)

    def test_graph_polish_uses_thin_rules_and_scoped_depth_tokens(self):
        self.assertNotIn("border-left:4px", self.graph_css)
        self.assertNotIn("border-left:4px", self.graph_css.replace(" ", ""))
        for marker in (
            "--graph-panel",
            "--graph-shadow",
            "border-radius:12px",
            "prefers-reduced-motion",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.graph_css)


if __name__ == "__main__":
    unittest.main(verbosity=2)
