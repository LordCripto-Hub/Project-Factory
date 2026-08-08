#!/usr/bin/env python3
"""Contract for the single shared MyPeople design-system layer."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DesignSystemContract(unittest.TestCase):
    def setUp(self):
        self.css = (ROOT / "bin" / "mypeople-ui.css").read_text(encoding="utf-8")
        self.docs = (ROOT / "docs" / "design-system" / "README.md").read_text(encoding="utf-8")
        self.catalog = (ROOT / "docs" / "design-system" / "catalog.html").read_text(encoding="utf-8")
        self.compact_css = re.sub(r"\s+", "", self.css)

    def test_semantic_tokens_map_to_existing_scorpion_tokens(self):
        for marker in (
            "--surface-0:var(--soot)",
            "--surface-1:var(--charcoal)",
            "--surface-2:var(--armor)",
            "--text-primary:var(--bone)",
            "--border-focus:var(--gold)",
            "--state-working:var(--ember)",
            "--state-blocked:var(--crimson)",
            "--state-done:var(--jade)",
            "--font-code:var(--mono)",
        ):
            self.assertIn(marker, self.compact_css)

    def test_legacy_aliases_remain_for_incremental_migration(self):
        for marker in ("--dark-bg:var(--soot)", "--volt:var(--gold)", "--warning:var(--ember)", "--success:var(--jade)"):
            self.assertIn(marker, self.compact_css)

    def test_documentation_declares_single_runtime_source(self):
        self.assertIn("bin/mypeople-ui.css", self.docs)
        self.assertIn("not a second runtime", self.docs)
        self.assertIn("external static gallery", self.docs)

    def test_active_surfaces_consume_semantic_tokens(self):
        for marker in (
            "body{background:var(--surface-0)",
            ".task,.tile,.panel,section{background-color:var(--surface-1)",
            ".status.working,.st-working{color:var(--state-working)",
            ".status.blocked,.st-blocked{color:var(--state-blocked)",
            ".task-top{display:flex",
            ".viewbar{display:flex",
        ):
            self.assertIn(marker, self.compact_css)

    def test_wall_is_not_part_of_the_active_component_map(self):
        self.assertNotIn("`wall.html` |", self.docs)
        self.assertIn("legacy compatibility route", self.docs)

    def test_catalog_uses_runtime_stylesheet_and_representative_components(self):
        self.assertIn('../../bin/mypeople-ui.css', self.catalog)
        for marker in ('class="task"', 'class="evidence-card"', 'class="status working"', 'class="agent-tile"', 'class="viewbar"'):
            self.assertIn(marker, self.catalog)
        self.assertIn("not a new runtime", self.catalog)


if __name__ == "__main__":
    unittest.main(verbosity=2)
