#!/usr/bin/env python3
"""Contract for the single shared MyPeople design-system layer."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DesignSystemContract(unittest.TestCase):
    def setUp(self):
        self.css = (ROOT / "bin" / "mypeople-ui.css").read_text(encoding="utf-8")
        self.docs = (ROOT / "docs" / "design-system" / "README.md").read_text(encoding="utf-8")

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
            self.assertIn(marker, self.css.replace(" ", ""))

    def test_legacy_aliases_remain_for_incremental_migration(self):
        for marker in ("--dark-bg:var(--soot)", "--volt:var(--gold)", "--warning:var(--ember)", "--success:var(--jade)"):
            self.assertIn(marker, self.css.replace(" ", ""))

    def test_documentation_declares_single_runtime_source(self):
        self.assertIn("bin/mypeople-ui.css", self.docs)
        self.assertIn("not a second runtime", self.docs)
        self.assertIn("external static gallery", self.docs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
