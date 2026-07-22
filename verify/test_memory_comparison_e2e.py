#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "verify"))

try:
    from memory_comparison_e2e_fixture import run_harmful_fixture, run_success_fixture
    IMPORT_ERROR = None
except ModuleNotFoundError as error:
    IMPORT_ERROR = error


EXPECTED = [
    ("cmp-exact-01", "baseline"),
    ("cmp-exact-01", "memory"),
    ("cmp-temporal-01", "memory"),
    ("cmp-temporal-01", "baseline"),
    ("cmp-contradiction-01", "baseline"),
    ("cmp-contradiction-01", "memory"),
]


class MemoryComparisonE2E(unittest.TestCase):
    def require_fixture(self):
        self.assertIsNone(IMPORT_ERROR, f"synthetic E2E adapter is missing: {IMPORT_ERROR}")

    def test_six_arms_are_isolated_and_fully_cleaned(self):
        self.require_fixture()
        with tempfile.TemporaryDirectory() as temp:
            receipt = run_success_fixture(Path(temp))
        self.assertEqual(receipt["schedule"], [list(item) for item in EXPECTED])
        self.assertEqual(len(set(receipt["worker_ids"])), 6)
        self.assertEqual(len(set(receipt["card_ids"])), 6)
        self.assertEqual(len(set(receipt["conversation_ids"])), 6)
        self.assertTrue(all(receipt["first_absent_before_second"]))
        self.assertTrue(receipt["baseline_has_no_memory"])
        self.assertTrue(receipt["memory_has_only_bounded_block"])
        self.assertTrue(receipt["cleanup_complete"])
        self.assertTrue(receipt["priorities_healthy"])
        self.assertTrue(receipt["hud_healthy"])

    def test_harmful_result_aborts_before_next_arm_and_cleans(self):
        self.require_fixture()
        with tempfile.TemporaryDirectory() as temp:
            receipt = run_harmful_fixture(Path(temp))
        self.assertEqual(receipt["status"], "aborted")
        self.assertEqual(receipt["arm_count"], 1)
        self.assertTrue(receipt["cleanup_complete"])

    @unittest.skipUnless(
        shutil.which("docker") and os.environ.get("MP_VERIFY_ISOLATED") != "1" and os.environ.get("MYPEOPLE_COMPARISON_E2E_INSIDE") != "1",
        "Docker lifecycle is exercised only by the host-level disposable test",
    )
    def test_disposable_docker_restart_count_is_unchanged(self):
        self.require_fixture()
        image = os.environ.get("MYPEOPLE_COMPARISON_E2E_IMAGE", "mypeople-node:upgrade-20260721T225008Z")
        name = f"mypeople-comparison-e2e-{uuid.uuid4().hex[:12]}"
        root = str(ROOT.resolve())
        try:
            started = subprocess.run(
                ["docker", "run", "-d", "--name", name, "-e", "MYPEOPLE_COMPARISON_E2E_INSIDE=1", "-v", f"{root}:/workspace:ro", image, "sleep", "infinity"],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(started.returncode, 0, started.stdout + started.stderr)
            before = subprocess.run(
                ["docker", "inspect", name, "--format", "{{.RestartCount}}"],
                check=True, capture_output=True, text=True,
            ).stdout.strip()
            completed = subprocess.run(
                ["docker", "exec", name, "python3", "/workspace/verify/test_memory_comparison_e2e.py"],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            after = subprocess.run(
                ["docker", "inspect", name, "--format", "{{.RestartCount}}"],
                check=True, capture_output=True, text=True,
            ).stdout.strip()
            self.assertEqual((before, after), ("0", "0"))
        finally:
            subprocess.run(["docker", "rm", "-f", name], check=False, capture_output=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
