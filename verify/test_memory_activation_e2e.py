#!/usr/bin/env python3
"""Opt-in live smoke for the synthetic project-scoped memory pilot."""
from __future__ import annotations

import os
import json
import unittest
import urllib.request

from project_context import compile_task_spec


PILOT_ENABLED = os.environ.get("MYPEOPLE_MEMORY_PILOT_E2E") == "1"
PILOT_ORIGIN = "https://mypeople-memory-sandbox.labmkt.workers.dev"
PILOT_URL = PILOT_ORIGIN + "/mcp"


def pilot_profile():
    return {
        "schemaVersion": 1,
        "revision": 1,
        "slug": "pilot-alpha",
        "repository": "https://example.invalid/synthetic/pilot-alpha.git",
        "workingDirectory": "/workspace/pilot-alpha",
        "allowedBranches": ["main"],
        "contextFiles": ["README.md"],
        "verificationCommands": ["python3 verify.py"],
        "allowedActions": ["read", "test"],
        "forbiddenActions": ["edit", "push", "deploy", "delete"],
        "limits": {
            "contextChars": 6000,
            "memoryTopK": 3,
            "memoryHops": 0,
            "memoryTimeoutSeconds": 8,
        },
        "memory": {
            "enabled": True,
            "serverUrl": PILOT_URL,
            "credentialRef": (
                "file:///run/mypeople-secrets/MYPEOPLE_MEMORY_TOKEN"
            ),
        },
    }


@unittest.skipUnless(
    PILOT_ENABLED,
    "set MYPEOPLE_MEMORY_PILOT_E2E=1 for the live synthetic pilot",
)
class LiveMemoryActivation(unittest.TestCase):
    def test_health_contract_is_exact(self):
        request = urllib.request.Request(
            PILOT_ORIGIN + "/health",
            headers={
                "Accept": "application/json",
                "User-Agent": "mypeople-memory-pilot-e2e/1.0",
            },
        )
        with urllib.request.urlopen(request, timeout=8) as response:
            health = json.load(response)
        self.assertEqual(
            health,
            {"ok": True, "mode": "mypeople-read-only-pilot"},
        )

    def test_compiles_bounded_provenance_complete_same_project_claims(self):
        task_spec = compile_task_spec(
            {
                "id": "synthetic-memory-e2e",
                "projectSlug": "pilot-alpha",
                "text": "Verify synthetic project-scoped recall.",
                "doneCondition": "The Codex Luna fixture is recalled.",
                "evidencePolicy": "required",
                "contextQuestion": "Codex Luna",
            },
            pilot_profile(),
            now=lambda: 1760000000,
        )

        self.assertEqual(task_spec["memoryStatus"], "ok")
        self.assertGreaterEqual(len(task_spec["memoryClaims"]), 1)
        self.assertLessEqual(len(task_spec["memoryClaims"]), 3)
        self.assertIn("a01", {claim["id"] for claim in task_spec["memoryClaims"]})
        for claim in task_spec["memoryClaims"]:
            self.assertEqual(claim["projectSlug"], "pilot-alpha")
            self.assertTrue(claim["sourceUri"])
            self.assertTrue(claim["sourceType"])
            self.assertTrue(claim["content"])
            self.assertIsInstance(claim["createdAt"], (int, float))
            self.assertIsInstance(claim["updatedAt"], (int, float))
            self.assertTrue(claim["status"])
        self.assertEqual(
            task_spec.memory_metadata["embeddedClaimCount"],
            len(task_spec["memoryClaims"]),
        )
        self.assertEqual(task_spec.memory_metadata["aiUsage"], "not_measured")
        self.assertLessEqual(
            len(json.dumps(task_spec, ensure_ascii=False, sort_keys=True)),
            pilot_profile()["limits"]["contextChars"],
        )

    def test_beta_only_query_cannot_cross_into_alpha(self):
        task_spec = compile_task_spec(
            {
                "id": "synthetic-memory-isolation-e2e",
                "projectSlug": "pilot-alpha",
                "text": "Verify cross-project recall isolation.",
                "doneCondition": "No beta memory is returned.",
                "evidencePolicy": "required",
                "contextQuestion": "short-lived OAuth grants",
            },
            pilot_profile(),
            now=lambda: 1760000000,
        )
        self.assertEqual(task_spec["memoryStatus"], "ok")
        self.assertEqual(task_spec["memoryClaims"], [])
        self.assertEqual(task_spec.memory_metadata["returnedClaimCount"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
