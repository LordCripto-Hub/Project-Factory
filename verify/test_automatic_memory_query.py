#!/usr/bin/env python3
"""Contracts for deterministic, provider-free automatic memory queries."""
import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

from automatic_memory import derive_memory_query, memory_eligibility


class AutomaticMemoryQueryTests(unittest.TestCase):
    def test_query_is_deterministic_line_deduplicated_and_bounded(self):
        task = {
            "id": "task-1",
            "projectSlug": "project-factory",
            "text": "Repair exact session recovery",
            "doneCondition": (
                "Repair exact session recovery\nPreserve task ownership"
            ),
            "contextQuestion": (
                "Why did recovery reject stale tmux windows?"
            ),
        }
        expected = (
            "Repair exact session recovery | Preserve task ownership | "
            "Why did recovery reject stale tmux windows?"
        )
        self.assertEqual(derive_memory_query(task), expected)
        self.assertEqual(derive_memory_query(task), expected)
        self.assertLessEqual(len(derive_memory_query(task)), 800)

    def test_private_and_noisy_fields_never_enter_query(self):
        task = {
            "projectSlug": "project-factory",
            "text": "Inspect publisher",
            "comments": [{"text": "secret-comment"}],
            "proofs": [{"url": "file:///secret"}],
            "providerTranscript": "hidden",
        }
        query = derive_memory_query(task)
        self.assertEqual(query, "Inspect publisher")
        self.assertNotIn("secret", query)
        self.assertNotIn("hidden", query)

    def test_query_normalizes_control_characters_and_safe_truncation(self):
        task = {
            "projectSlug": "project-factory",
            "text": "  Repair\x00   publisher  ",
            "doneCondition": "x" * 1_000,
        }
        query = derive_memory_query(task)
        self.assertTrue(query.startswith("Repair publisher | "))
        self.assertNotIn("\x00", query)
        self.assertLessEqual(len(query), 800)
        self.assertFalse(query.endswith(" |"))

    def test_eligibility_excludes_other_projects_baselines_and_empty_query(self):
        self.assertEqual(
            memory_eligibility({"projectSlug": "other"}),
            "project_denied",
        )
        baseline = {
            "projectSlug": "project-factory",
            "test": True,
            "experiment": {"memory_comparison": {"arm": "baseline"}},
        }
        self.assertEqual(memory_eligibility(baseline), "comparison_baseline")
        self.assertEqual(
            memory_eligibility({"projectSlug": "project-factory"}),
            "empty_query",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
