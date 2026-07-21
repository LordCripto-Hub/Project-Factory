from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from memory_bench.history_fixture import load_history_fixture
from memory_bench.taskspec_memory import PROJECT_SLUG, recall_history_claims


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "datasets" / "project-factory-history-80dce6f86632"
LOCK = ROOT / "docker" / "history-hybrid.dataset-lock.json"


class TaskSpecMemoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loaded = load_history_fixture(DATASET, LOCK)
        cls.events = {
            event.event_id: event for event in cls.loaded.fixture.events
        }

    def test_relevant_exact_question_returns_closed_grounded_claims(self):
        question = next(
            item
            for item in self.loaded.fixture.questions
            if item.question_id == "hist-exact-003"
        )
        claims = recall_history_claims(self.loaded, question.query, limit=3)
        self.assertGreaterEqual(len(claims), 1)
        self.assertLessEqual(len(claims), 3)
        self.assertTrue(
            set(question.relevant_event_ids) & {claim["id"] for claim in claims}
        )
        for claim in claims:
            self.assertEqual(
                set(claim),
                {
                    "id",
                    "projectSlug",
                    "content",
                    "sourceUri",
                    "sourceType",
                    "status",
                },
            )
            self.assertEqual(claim["projectSlug"], PROJECT_SLUG)
            self.assertEqual(claim["sourceUri"], self.events[claim["id"]].provenance)
            self.assertEqual(claim["status"], "canonical")

    def test_absent_question_returns_no_claim(self):
        claims = recall_history_claims(
            self.loaded,
            "zxqvplmokn 000000000000",
            limit=3,
        )
        self.assertEqual(claims, [])

    def test_limit_and_project_contract_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "invalid_recall_limit"):
            recall_history_claims(self.loaded, "question", limit=4)
        altered = replace(self.loaded, repo_slug="Other/Repository")
        with self.assertRaisesRegex(ValueError, "project_mismatch"):
            recall_history_claims(altered, "question", limit=1)

    def test_stdin_bridge_emits_only_claims_and_ai_usage(self):
        question = next(
            item
            for item in self.loaded.fixture.questions
            if item.question_id == "hist-exact-003"
        )
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "query_taskspec_memory.py"),
                "--dataset",
                str(DATASET),
                "--lock",
                str(LOCK),
            ],
            input=json.dumps(
                {
                    "projectSlug": PROJECT_SLUG,
                    "query": question.query,
                    "limit": 3,
                    "hops": 0,
                }
            ),
            text=True,
            capture_output=True,
            check=True,
            env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        )
        result = json.loads(completed.stdout)
        self.assertEqual(set(result), {"claims", "aiUsage"})
        self.assertEqual(result["aiUsage"], "not_measured")
        self.assertNotIn(str(ROOT), completed.stdout)

    def test_stdin_bridge_rejects_boolean_hops(self):
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "query_taskspec_memory.py"),
                "--dataset",
                str(DATASET),
                "--lock",
                str(LOCK),
            ],
            input=json.dumps(
                {
                    "projectSlug": PROJECT_SLUG,
                    "query": "Which constraint applies?",
                    "limit": 3,
                    "hops": False,
                }
            ),
            text=True,
            capture_output=True,
            check=False,
            env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("invalid_recall_hops", completed.stderr)


if __name__ == "__main__":
    unittest.main()
