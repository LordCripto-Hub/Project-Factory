#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

from agent_identity import validate_agent_identity


class AgentIdentityContract(unittest.TestCase):
    def setUp(self):
        self.expected = {
            "target": "mc-main:Boss",
            "backend": "codex",
            "profile": "primary",
            "model": "gpt-5.6-sol",
            "cwd": "/home/mp/mypeople/run/boss",
            "owner_task_id": "task-1",
        }
        self.matching = {
            **self.expected,
            "windowExists": True,
            "processAlive": True,
            "ready": True,
        }

    def state(self, **changes):
        return validate_agent_identity(
            self.expected, {**self.matching, **changes}
        )["state"]

    def test_matching_identity_is_ready(self):
        result = validate_agent_identity(self.expected, self.matching)
        self.assertTrue(result["ok"])
        self.assertEqual(result["state"], "ready")
        self.assertTrue(all(value == "pass" for value in result["checks"].values()))

    def test_missing_process_is_not_identity(self):
        self.assertEqual(self.state(processAlive=False), "process_missing")

    def test_backend_profile_and_model_must_match(self):
        self.assertEqual(self.state(backend="claude"), "backend_mismatch")
        self.assertEqual(self.state(profile="other"), "profile_mismatch")
        self.assertEqual(self.state(model="other"), "model_mismatch")

    def test_required_arguments_match_exactly(self):
        self.assertEqual(self.state(cwd="/tmp"), "arguments_mismatch")
        self.assertEqual(self.state(owner_task_id="task-2"), "arguments_mismatch")

    def test_composer_must_be_ready(self):
        self.assertEqual(self.state(ready=False), "not_ready")

    def test_missing_window_has_highest_precedence(self):
        self.assertEqual(
            self.state(windowExists=False, processAlive=False),
            "window_missing",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
