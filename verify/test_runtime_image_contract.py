#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RuntimeImageContract(unittest.TestCase):
    def test_runtime_image_synchronizes_the_versioned_source(self):
        dockerfile = (ROOT / "docker" / "Dockerfile.runtime-image").read_text(
            encoding="utf-8"
        )
        self.assertIn("USER root", dockerfile)
        self.assertIn("COPY --chown=mp:mp . /tmp/mypeople-source", dockerfile)
        self.assertIn("sync_runtime_source.py", dockerfile)
        self.assertIn('ENTRYPOINT ["/usr/bin/env"]', dockerfile)
        self.assertIn('CMD ["sleep", "infinity"]', dockerfile)

    def test_source_sync_removes_stale_code_and_preserves_runtime_dependencies(self):
        path = ROOT / "docker" / "sync_runtime_source.py"
        spec = importlib.util.spec_from_file_location("runtime_source_sync", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            target = root / "target"
            (source / "bin").mkdir(parents=True)
            (source / "verify").mkdir()
            (source / "bin" / "current.py").write_text("current", encoding="utf-8")
            (source / "verify" / "current.py").write_text("current", encoding="utf-8")
            (target / "bin").mkdir(parents=True)
            (target / "verify" / "node_modules" / "playwright").mkdir(parents=True)
            (target / "run").mkdir()
            (target / "bin" / "voice-dock.js").write_text("stale", encoding="utf-8")
            (target / "verify" / "test_voice_dock.py").write_text("stale", encoding="utf-8")
            (target / "verify" / "node_modules" / "playwright" / "keep").write_text(
                "dependency", encoding="utf-8"
            )
            (target / "run" / "keep.json").write_text("runtime", encoding="utf-8")
            module.sync_runtime_source(source, target)
            self.assertFalse((target / "bin" / "voice-dock.js").exists())
            self.assertFalse((target / "verify" / "test_voice_dock.py").exists())
            self.assertEqual(
                (target / "bin" / "current.py").read_text(encoding="utf-8"),
                "current",
            )
            self.assertTrue(
                (target / "verify" / "node_modules" / "playwright" / "keep").is_file()
            )
            self.assertTrue((target / "run" / "keep.json").is_file())

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
