#!/usr/bin/env python3
import json
from pathlib import Path
import re
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "experiments" / "memory-gate-b"
DATASET = EXPERIMENT / "datasets" / "project-factory-history-039a62988625"
LOCK = EXPERIMENT / "docker" / "history-hybrid-039a62988625.dataset-lock.json"
CASES = EXPERIMENT / "comparison" / "cases.json"
sys.path.insert(0, str(EXPERIMENT))
sys.path.insert(0, str(EXPERIMENT / "src"))

from comparison.contracts import load_cases
from memory_bench.history_fixture import load_history_fixture

try:
    from comparison.offline import canonical_receipt, run_offline_comparison
    IMPORT_ERROR = None
except ModuleNotFoundError as error:
    IMPORT_ERROR = error


def clock_with_elapsed(milliseconds):
    values = []
    current = 0
    for elapsed in milliseconds:
        values.extend((current, current + elapsed * 1_000_000))
        current += (elapsed + 1) * 1_000_000
    iterator = iter(values)
    return lambda: next(iterator)


class MemoryComparisonOfflineContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loaded = load_history_fixture(DATASET, LOCK)
        cls.cases = load_cases(CASES, DATASET)

    def test_offline_runner_exists(self):
        self.assertIsNone(IMPORT_ERROR, f"offline comparison runner is missing: {IMPORT_ERROR}")

    def test_all_six_cases_retrieve_gold_without_rejected_evidence(self):
        if IMPORT_ERROR:
            self.skipTest("offline runner missing")
        receipt = run_offline_comparison(
            self.loaded,
            self.cases,
            fixture_path=CASES,
            clock_ns=clock_with_elapsed([1, 2, 3, 4, 5, 6]),
        )
        self.assertTrue(receipt["passed"])
        self.assertEqual(len(receipt["cases"]), 6)
        self.assertLessEqual(receipt["aggregates"]["escalation_count"], 40)
        self.assertEqual(receipt["aggregates"]["median_retrieval_latency_ms"], 3.5)
        by_alias = {case.alias: case for case in self.cases}
        for row in receipt["cases"]:
            case = by_alias[row["alias"]]
            self.assertTrue(set(case.allowed_evidence_ids).issubset(row["selected_evidence_ids"]))
            self.assertEqual(row["rejected_evidence_ids"], [])
            self.assertTrue(row["passed"])
            self.assertLessEqual(row["estimated_memory_context_tokens"], 300)

    def test_logical_digest_ignores_nondeterministic_timing_only(self):
        if IMPORT_ERROR:
            self.skipTest("offline runner missing")
        fast = run_offline_comparison(
            self.loaded,
            self.cases,
            fixture_path=CASES,
            clock_ns=clock_with_elapsed([1] * 6),
        )
        slow = run_offline_comparison(
            self.loaded,
            self.cases,
            fixture_path=CASES,
            clock_ns=clock_with_elapsed([9] * 6),
        )
        self.assertNotEqual(canonical_receipt(fast), canonical_receipt(slow))
        self.assertEqual(fast["logical_digest"], slow["logical_digest"])

    def test_receipt_is_public_safe_and_contains_no_raw_memory(self):
        if IMPORT_ERROR:
            self.skipTest("offline runner missing")
        receipt = run_offline_comparison(
            self.loaded,
            self.cases,
            fixture_path=CASES,
            clock_ns=clock_with_elapsed([1] * 6),
        )
        serialized = canonical_receipt(receipt).decode("utf-8")
        for forbidden_key in ('"query"', '"expected_values"', '"content"', '"prompt"'):
            self.assertNotIn(forbidden_key, serialized)
        for pattern in (
            r"(?i)tskey-auth-",
            r"(?i)sk-[a-z0-9]{20,}",
            r"(?i)c:\\users\\",
            r"(?i)/home/[^/]+/",
        ):
            self.assertIsNone(re.search(pattern, serialized), pattern)


if __name__ == "__main__":
    unittest.main(verbosity=2)
