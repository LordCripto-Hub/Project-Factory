#!/usr/bin/env python3
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class OperatorNavigationTests(unittest.TestCase):
    def test_all_surfaces_expose_only_board_graph_and_hud(self):
        expected = [('href="/"', "Board"), ('href="/terminal-graph"', "Graph"), ('href="/dashboard"', "HUD")]
        for name in ("todos.html", "terminal-graph.html", "dashboard.html"):
            page = (ROOT / "bin" / name).read_text(encoding="utf-8")
            for href, label in expected:
                self.assertIn(href, page, f"{name}: {label}")
            self.assertNotIn('href="/wall"', page, name)

    def test_wall_redirects_and_asset_is_retired(self):
        todo = (ROOT / "bin" / "todo-server.py").read_text(encoding="utf-8")
        self.assertIn('if p=="/wall":return self.redirect("/",head)', todo)
        self.assertNotIn('if p=="/todo/wall"', todo)
        self.assertFalse((ROOT / "bin" / "wall.html").exists())

    def test_graph_and_hud_retain_wall_capabilities(self):
        graph = (ROOT / "bin" / "terminal-graph.html").read_text(encoding="utf-8")
        hud = (ROOT / "bin" / "dashboard.html").read_text(encoding="utf-8")
        for contract in ("terminal-graph", "openFull", "taskNodes", "pattach"):
            self.assertIn(contract, graph)
        for contract in ("attachUrl", "buildCardRows", "healthState", "recordingState"):
            self.assertIn(contract, hud)


if __name__ == "__main__": unittest.main(verbosity=2)
