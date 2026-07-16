#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_runtime():
    path = ROOT / "bin" / "provider_launch.py"
    spec = importlib.util.spec_from_file_location("provider_launch_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ProviderLaunchPauseContract(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.pause_path = Path(self.temporary.name) / "provider-launch.paused"

    def tearDown(self):
        self.temporary.cleanup()

    def test_pause_is_private_atomic_and_resume_is_idempotent(self):
        runtime = load_runtime()
        record = runtime.pause(self.pause_path, "provider profile exhausted")
        self.assertTrue(record["paused"])
        self.assertEqual(record["reason"], "provider profile exhausted")
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(self.pause_path.stat().st_mode), 0o600)
        self.assertEqual(json.loads(self.pause_path.read_text(encoding="utf-8")), record)
        self.assertFalse(list(self.pause_path.parent.glob("*.tmp")))
        self.assertEqual(runtime.status(self.pause_path), record)
        runtime.resume(self.pause_path)
        runtime.resume(self.pause_path)
        self.assertEqual(runtime.status(self.pause_path), {"paused": False})

    def test_supervisor_honors_durable_pause_and_environment_disable(self):
        source = (ROOT / "bin" / "boss-supervisor.sh").read_text(encoding="utf-8")
        loop = source.index("while :; do")
        pause_declaration = source.index('provider-launch.paused')
        pause_guard = source.index('-f "$pause_file"', loop)
        env_guard = source.index('MYPEOPLE_DISABLE_PROVIDER_LAUNCH', loop)
        boss_check = source.index("tmux has-session -t mc-main:Boss", loop)
        self.assertLess(pause_declaration, loop)
        self.assertLess(pause_guard, boss_check)
        self.assertLess(env_guard, boss_check)

    def test_operator_cli_exposes_pause_resume_and_status(self):
        source = (ROOT / "bin" / "mp").read_text(encoding="utf-8")
        self.assertIn('sub.add_parser("providers-pause")', source)
        self.assertIn('sub.add_parser("providers-resume")', source)
        self.assertIn('sub.add_parser("providers-status")', source)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(ProviderLaunchPauseContract)
    )
    raise SystemExit(0 if result.wasSuccessful() else 1)
