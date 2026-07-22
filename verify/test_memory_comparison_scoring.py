#!/usr/bin/env python3
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "experiments" / "memory-gate-b"
DATASET = EXPERIMENT / "datasets" / "project-factory-history-80dce6f86632"
CASES = EXPERIMENT / "comparison" / "cases.json"
sys.path.insert(0, str(EXPERIMENT))

try:
    from comparison.contracts import load_cases
    from comparison.scoring import (
        ComparisonResultError,
        canonical_score_receipt,
        score_result,
        validate_result_envelope,
    )
    IMPORT_ERROR = None
except ModuleNotFoundError as error:
    IMPORT_ERROR = error


class MemoryComparisonScoringContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.case = next(case for case in load_cases(CASES, DATASET) if case.alias == "cmp-contradiction-01")
        cls.valid = {
            "decision_id": "reject_superseded_change",
            "selected_evidence_ids": ["file-2329c9ce5780-001"],
            "rejected_evidence_ids": ["file-0f90171133e7-001"],
            "commands": [
                {"command_id": "git_log_path_latest", "exit_code": 0},
                {"command_id": "git_show_superseded_edge", "exit_code": 0},
            ],
            "conclusion": "The newer verified path change supersedes the earlier record.",
        }

    def test_scoring_module_exists(self):
        self.assertIsNone(IMPORT_ERROR, f"comparison scorer is missing: {IMPORT_ERROR}")

    def test_valid_closed_result_scores_one_hundred(self):
        if IMPORT_ERROR:
            self.skipTest("scorer missing")
        normalized = validate_result_envelope(self.case, self.valid)
        receipt = score_result(self.case, normalized)
        self.assertEqual(
            receipt["components"],
            {
                "correctness": 40,
                "provenance": 25,
                "verification": 20,
                "contradiction_avoidance": 10,
                "discipline": 5,
            },
        )
        self.assertEqual(receipt["score"], 100)
        self.assertTrue(receipt["successful"])
        self.assertFalse(receipt["harmful"])

    def test_score_below_eighty_is_not_successful(self):
        if IMPORT_ERROR:
            self.skipTest("scorer missing")
        result = json.loads(json.dumps(self.valid))
        result["decision_id"] = "incorrect_decision"
        result["commands"][0]["exit_code"] = 1
        receipt = score_result(self.case, result)
        self.assertEqual(receipt["score"], 40)
        self.assertFalse(receipt["successful"])
        self.assertFalse(receipt["harmful"])

    def test_wrong_or_rejected_evidence_and_runtime_violations_are_harmful(self):
        if IMPORT_ERROR:
            self.skipTest("scorer missing")
        wrong = json.loads(json.dumps(self.valid))
        wrong["selected_evidence_ids"] = ["file-from-another-project"]
        for result, violations in (
            (wrong, ()),
            (self.valid, ("wrong_project",)),
            (self.valid, ("forbidden_action",)),
            (self.valid, ("isolation_breach",)),
        ):
            receipt = score_result(self.case, result, violations=violations)
            self.assertEqual(receipt["score"], 0)
            self.assertTrue(receipt["harmful"])
            self.assertFalse(receipt["successful"])

    def test_missing_extra_or_oversized_result_fields_fail_closed(self):
        if IMPORT_ERROR:
            self.skipTest("scorer missing")
        invalid = []
        missing = json.loads(json.dumps(self.valid))
        del missing["commands"]
        invalid.append(missing)
        extra = {**self.valid, "provider_transcript": "must not be accepted"}
        invalid.append(extra)
        oversized = {**self.valid, "conclusion": "x" * 501}
        invalid.append(oversized)
        command_text = json.loads(json.dumps(self.valid))
        command_text["commands"][0]["command"] = "git log --all"
        invalid.append(command_text)
        for result in invalid:
            with self.assertRaises(ComparisonResultError):
                validate_result_envelope(self.case, result)

    def test_canonical_receipt_is_byte_identical(self):
        if IMPORT_ERROR:
            self.skipTest("scorer missing")
        first = canonical_score_receipt(score_result(self.case, self.valid))
        second = canonical_score_receipt(score_result(self.case, json.loads(json.dumps(self.valid))))
        self.assertIsInstance(first, bytes)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main(verbosity=2)
