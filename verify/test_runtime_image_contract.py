#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RuntimeImageContract(unittest.TestCase):
    def test_runtime_image_overlays_the_versioned_source(self):
        dockerfile = (ROOT / "docker" / "Dockerfile.runtime-image").read_text(
            encoding="utf-8"
        )
        self.assertIn("USER root", dockerfile)
        self.assertIn("COPY --chown=mp:mp . /home/mp/mypeople", dockerfile)
        self.assertIn('ENTRYPOINT ["/usr/bin/env"]', dockerfile)
        self.assertIn('CMD ["sleep", "infinity"]', dockerfile)

    def test_build_context_excludes_host_and_runtime_state(self):
        ignored = {
            line.strip()
            for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        for required in (
            ".git",
            ".env",
            ".env.*",
            ".codex/",
            ".claude/",
            "run/",
            "status/",
            "todos/",
            "recordings/",
            "**/__pycache__/",
            "*.pyc",
            "*.pem",
            "*.key",
            "*.p12",
        ):
            self.assertIn(required, ignored)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(RuntimeImageContract)
    )
    raise SystemExit(0 if result.wasSuccessful() else 1)
