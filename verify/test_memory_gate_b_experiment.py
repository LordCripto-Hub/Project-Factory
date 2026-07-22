#!/usr/bin/env python3
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "experiments" / "memory-gate-b"
DATASET = EXPERIMENT / "datasets" / "project-factory-history-80dce6f86632"
LOCK = EXPERIMENT / "docker" / "history-hybrid.dataset-lock.json"


class MemoryGateBExperimentContract(unittest.TestCase):
    def test_standard_isolated_suite_registers_the_fast_contract(self):
        suite = (ROOT / "verify" / "run-suite.sh").read_text(encoding="utf-8")
        invocation = 'python3 "$VERIFY/test_memory_gate_b_experiment.py"'
        self.assertEqual(suite.count(invocation), 1)

    def test_required_package_surfaces_exist(self):
        required = (
            EXPERIMENT / "README.md",
            EXPERIMENT / "src" / "memory_bench" / "taskspec_gate.py",
            EXPERIMENT / "src" / "memory_bench" / "taskspec_memory.py",
            EXPERIMENT / "scripts" / "run_taskspec_memory_gate.py",
            EXPERIMENT / "docker" / "compose.taskspec-memory.yml",
            EXPERIMENT / "windows" / "Invoke-IsolatedTaskSpecMemory.ps1",
            EXPERIMENT / "artifacts" / "taskspec-memory-result.json",
        )
        for path in required:
            self.assertTrue(path.is_file(), path)

    def test_dataset_is_final_locked_and_complete(self):
        self.assertTrue(LOCK.is_file(), LOCK)
        lock = json.loads(LOCK.read_text(encoding="utf-8"))
        self.assertEqual(lock["dataset_dir"], DATASET.name)
        self.assertEqual(
            lock["source_sha"],
            "80dce6f866329b79061bb1ed6b0594f9fdf2dd45",
        )
        self.assertNotIn("preliminary", json.dumps(lock).lower())
        for name, expected in lock["files"].items():
            path = DATASET / name
            self.assertTrue(path.is_file(), path)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected)

    def test_experiment_is_not_activated_by_production_entrypoints(self):
        production = [ROOT / "install.sh", *sorted((ROOT / "bin").glob("*"))]
        production += sorted((ROOT / "docker").rglob("*"))
        production += sorted((ROOT / "windows").rglob("*"))
        for path in production:
            if path.name == "Start-MyPeopleMemoryComparison.ps1":
                continue  # Explicit, dry-run-by-default operator surface; never a startup entrypoint.
            if path.is_file():
                self.assertNotIn(
                    "experiments/memory-gate-b",
                    path.read_text(encoding="utf-8", errors="ignore"),
                    path,
                )

    def test_public_experiment_has_no_private_material(self):
        forbidden = (
            re.compile(r"(?i)tskey-auth-"),
            re.compile(r"(?i)sk-[a-z0-9]{20,}"),
            re.compile(r"(?i)[a-z0-9._%+-]+@gmail\.com"),
            re.compile(r"(?i)c:\\users\\[^\\]+"),
            re.compile(r"(?i)/users/[^/]+"),
            re.compile(r"(?i)authorization\s*:\s*bearer\s+[^\"'\s]+"),
        )
        for path in EXPERIMENT.rglob("*"):
            if path.is_file() and path.suffix not in {".pyc", ".pyo"}:
                text = path.read_text(encoding="utf-8", errors="ignore")
                for pattern in forbidden:
                    self.assertIsNone(pattern.search(text), f"{path}: {pattern.pattern}")

    def test_focused_experiment_suite_passes(self):
        self.assertTrue(EXPERIMENT.is_dir(), EXPERIMENT)
        env = {
            **os.environ,
            "PYTHONPATH": str(EXPERIMENT / "src"),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                str(EXPERIMENT / "tests"),
                "-v",
            ],
            cwd=EXPERIMENT,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
