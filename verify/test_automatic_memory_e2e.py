#!/usr/bin/env python3
"""Integrated acceptance contracts for bounded automatic memory and rollback."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

from memory_canary import load_control, set_control
from memory_recovery import LEVELS, recover
from project_context import compile_task_spec


def claim(level):
    return {
        "id": f"commit-{level}",
        "projectSlug": "project-factory",
        "content": f"Verified {level} memory",
        "sourceUri": f"git+repo://Project-Factory#{level}",
        "sourceType": "commit",
        "status": "canonical",
    }


def task():
    return {
        "id": "task-automatic-e2e",
        "projectSlug": "project-factory",
        "text": "Explain exact session recovery",
        "doneCondition": "Cite verified history",
        "contextQuestion": "",
        "evidencePolicy": "required",
    }


def profile():
    return {
        "schemaVersion": 1,
        "revision": 9,
        "slug": "project-factory",
        "repository": "https://github.com/LordCripto-Hub/Project-Factory.git",
        "workingDirectory": "/workspace/project-factory",
        "allowedBranches": ["main"],
        "contextFiles": ["README.md", "AGENTS.md"],
        "verificationCommands": ["python3 verify/test_automatic_memory_e2e.py"],
        "allowedActions": ["read", "edit", "test"],
        "forbiddenActions": ["deploy", "push", "delete"],
        "limits": {"contextChars": 6000, "memoryTopK": 3, "memoryHops": 0, "memoryTimeoutSeconds": 2},
        "memory": {"enabled": True, "serverUrl": "https://memory.example.invalid/mcp", "credentialRef": "env://MYPEOPLE_MEMORY_TOKEN"},
    }


class AutomaticMemoryE2E(unittest.TestCase):
    def test_each_level_is_selected_in_order_and_later_levels_have_zero_cost(self):
        for selected in LEVELS:
            calls = []
            adapters = {}
            for level in LEVELS:
                adapters[level] = (
                    lambda query, limit, name=level: calls.append(name)
                    or ([claim(name)] if name == selected else [])
                )
            outcome = recover("verified history", adapters)
            with self.subTest(selected=selected):
                self.assertEqual(outcome["status"], "memory_applied")
                self.assertEqual(outcome["selectedLevel"], selected)
                self.assertEqual(calls, list(LEVELS[: LEVELS.index(selected) + 1]))
                self.assertLessEqual(outcome["estimatedTokens"], 300)
                self.assertTrue(outcome["provenanceComplete"])

    def test_automatic_recall_and_rollback_survive_runtime_reload(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            board_path = runtime / "board.json"
            board_path.write_text(json.dumps({"tasks": {task()["id"]: task()}}), encoding="utf-8")
            set_control(runtime, mode="automatic", now=lambda: 10)
            loaded_task = json.loads(board_path.read_text(encoding="utf-8"))["tasks"][task()["id"]]
            response = recover("verified history", {
                "fast": lambda _query, _limit: [claim("fast")],
                "deep": lambda _query, _limit: self.fail("deep must not run"),
                "exhaustive": lambda _query, _limit: self.fail("exhaustive must not run"),
                "emergency": lambda _query, _limit: self.fail("emergency must not run"),
            })
            first = compile_task_spec(
                loaded_task, profile(), recall=lambda _request: response,
                memory_query="Explain exact session recovery | Cite verified history",
                memory_mode=load_control(runtime)["mode"],
            )
            self.assertEqual(first["memoryStatus"], "memory_applied")

            self.assertEqual(load_control(runtime)["mode"], "automatic")
            self.assertEqual(json.loads(board_path.read_text(encoding="utf-8"))["tasks"][task()["id"]]["id"], task()["id"])
            set_control(runtime, mode="off", now=lambda: 11)
            second = compile_task_spec(
                loaded_task, profile(),
                recall=lambda _request: self.fail("off must not recall"),
                memory_mode=load_control(runtime)["mode"],
            )
            self.assertEqual(second["memoryStatus"], "not_requested")
            self.assertEqual(json.loads(board_path.read_text(encoding="utf-8"))["tasks"][task()["id"]]["id"], task()["id"])

    def test_failures_are_typed_empty_and_never_block_taskspec(self):
        adapters = {level: (lambda _query, _limit: []) for level in LEVELS}
        outcomes = [
            recover("absent evidence", adapters),
            {**recover("absent evidence", adapters), "status": "memory_unavailable", "reasonCode": "deadline_exceeded"},
            {**recover("absent evidence", adapters), "status": "memory_invalid_response", "provenanceComplete": False, "reasonCode": "adapter_response_invalid"},
            {**recover("absent evidence", adapters), "status": "memory_budget_exceeded", "reasonCode": "token_budget_exceeded"},
        ]
        for outcome in outcomes:
            spec = compile_task_spec(task(), profile(), recall=lambda _request, value=outcome: value, memory_query="absent evidence", memory_mode="automatic")
            with self.subTest(status=outcome["status"]):
                self.assertEqual(spec["memoryStatus"], outcome["status"])
                self.assertEqual(spec["memoryClaims"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
