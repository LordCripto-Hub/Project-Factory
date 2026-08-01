#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


sys.path.insert(0, str(ROOT / "bin"))
from memory_observability import get_memory_projection, project_memory_readiness


class AutomaticMemoryObservabilityTests(unittest.TestCase):
    def test_readiness_projection_is_bounded_and_independent_from_last_recall(self):
        self.assertEqual(
            project_memory_readiness(False, False, "ignored secret"),
            {
                "configured": False,
                "adapter": "local_hybrid",
                "readiness": "disabled",
                "reason": "disabled",
            },
        )
        self.assertEqual(
            project_memory_readiness(True, True, "ignored secret"),
            {
                "configured": True,
                "adapter": "local_hybrid",
                "readiness": "ready",
                "reason": "ok",
            },
        )
        unavailable = project_memory_readiness(
            True, False, "Bearer top-secret failed at http://127.0.0.1:18443/mcp"
        )
        self.assertEqual(unavailable["readiness"], "unavailable")
        self.assertEqual(unavailable["reason"], "adapter_unavailable")
        self.assertNotIn("secret", json.dumps(unavailable).lower())

    def test_projection_reads_only_sanitized_local_adapter_readiness(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            (runtime / "memory-canary-control.json").write_text(
                json.dumps({
                    "schemaVersion": 2,
                    "mode": "automatic",
                    "allowedProjects": ["project-factory"],
                    "revision": 9,
                    "updatedAt": 1,
                }),
                encoding="utf-8",
            )
            (runtime / "local-memory-ready.json").write_text(
                json.dumps({"schema": 1, "ready": True, "pid": 99, "token": "must-not-leak"}),
                encoding="utf-8",
            )
            projection = get_memory_projection(runtime)
            self.assertEqual(projection["readiness"]["readiness"], "ready")
            self.assertNotIn("pid", json.dumps(projection).lower())
            self.assertNotIn("token", json.dumps(projection).lower())

    def test_public_projection_has_bounded_metadata_only(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            (runtime / "memory-canary-control.json").write_text(
                json.dumps({
                    "schemaVersion": 2,
                    "mode": "automatic",
                    "allowedProjects": ["project-factory"],
                    "revision": 8,
                    "updatedAt": 1,
                }),
                encoding="utf-8",
            )
            (runtime / "taskspec-events.jsonl").write_text(
                json.dumps({
                    "taskId": "task-1",
                    "projectSlug": "project-factory",
                    "memoryStatus": "memory_applied",
                    "selectedLevel": "deep",
                    "levelsAttempted": ["fast", "deep"],
                    "elapsedMilliseconds": 17,
                    "examinedCount": 12,
                    "embeddedClaimCount": 3,
                    "estimatedTokens": 236,
                    "provenanceComplete": True,
                    "reasonCode": None,
                    "query": "must-not-leak",
                    "claims": ["must-not-leak"],
                    "credential": "must-not-leak",
                }) + "\n",
                encoding="utf-8",
            )
            projection = get_memory_projection(runtime, "task-1")
            self.assertEqual(projection["mode"], "automatic")
            self.assertEqual(projection["last"]["status"], "memory_applied")
            self.assertEqual(projection["last"]["level"], "deep")
            encoded = json.dumps(projection).lower()
            self.assertNotIn("query", encoded)
            self.assertNotIn("claims", encoded)
            self.assertNotIn("credential", encoded)

    def test_hud_renders_mode_level_latency_and_token_state(self):
        page = (ROOT / "bin" / "dashboard.html").read_text(encoding="utf-8")
        for label in ("Memory mode", "Memory readiness", "Recall level", "Latency", "Memory tokens"):
            self.assertIn(label, page)
        self.assertIn('/todo/memory-canary', page)
        self.assertIn('memoryTelemetry.readiness', page)


if __name__ == "__main__":
    unittest.main(verbosity=2)
