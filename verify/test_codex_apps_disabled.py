#!/usr/bin/env python3
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]

class CodexAppsDisabledContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "bin" / "mp").read_text(encoding="utf-8")

    def test_every_codex_agent_disables_product_apps_mcp(self):
        start = self.source.index("def _build_launch_args(")
        end = self.source.index("def build_launch(", start)
        block = self.source[start:end]
        self.assertIn('args += ["--disable", "apps"]', block)
        self.assertIn('if backend == "codex":', block)

    def test_claude_launch_is_unchanged(self):
        start = self.source.index("def _build_launch_args(")
        end = self.source.index("def build_launch(", start)
        block = self.source[start:end]
        self.assertLess(block.index('if backend == "codex":'), block.index("else:"))

    def test_cloudflare_memory_code_is_not_removed(self):
        self.assertTrue((ROOT / "bin" / "memory-profile").is_file())
        self.assertTrue((ROOT / "memory-gateway").is_dir())
        self.assertIn("memory-canary", self.source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
