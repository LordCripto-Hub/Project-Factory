#!/usr/bin/env python3
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "experiments" / "memory-gate-b"
COMPARISON = EXPERIMENT / "comparison"
CASES = COMPARISON / "cases.json"
DATASET = EXPERIMENT / "datasets" / "project-factory-history-039a62988625"
EXPECTED_SOURCE_SHA = "039a62988625369f3f86c055cd476b0080395daa"
EXPECTED_CLASSES = {
    "exact_constraint": 2,
    "temporal_continuation": 2,
    "contradiction_prevention": 2,
}
EXPECTED_LIVE_ORDERS = {
    "exact_constraint": ("baseline", "memory"),
    "temporal_continuation": ("memory", "baseline"),
    "contradiction_prevention": ("baseline", "memory"),
}


class MemoryComparisonFixtureContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not CASES.is_file():
            cls.document = None
            cls.loaded = None
            return
        sys.path.insert(0, str(EXPERIMENT))
        from comparison.contracts import load_cases

        cls.document = json.loads(CASES.read_text(encoding="utf-8"))
        try:
            cls.loaded = load_cases(CASES, DATASET)
            cls.load_error = None
        except ValueError as exc:
            cls.loaded = None
            cls.load_error = exc

    def test_fixture_exists(self):
        self.assertTrue(CASES.is_file(), "comparison case fixture is missing")
        self.assertIsNone(
            getattr(self, "load_error", None),
            f"comparison fixture must bind the current dataset: {getattr(self, 'load_error', None)}",
        )

    def test_matrix_has_two_cases_per_class_and_one_live_order(self):
        if self.loaded is None:
            self.skipTest("fixture missing")
        self.assertEqual(self.document["dataset"]["source_sha"], EXPECTED_SOURCE_SHA)
        counts = {
            case_class: sum(case.case_class == case_class for case in self.loaded)
            for case_class in EXPECTED_CLASSES
        }
        self.assertEqual(counts, EXPECTED_CLASSES)
        for case_class, order in EXPECTED_LIVE_ORDERS.items():
            live = [case for case in self.loaded if case.case_class == case_class and case.live]
            self.assertEqual(len(live), 1)
            self.assertEqual(live[0].arm_order, order)

    def test_every_case_resolves_to_locked_dataset_evidence(self):
        if self.loaded is None:
            self.skipTest("fixture missing")
        questions = {
            row["question_id"]: row
            for row in (
                json.loads(line)
                for line in (DATASET / "questions.jsonl").read_text(encoding="utf-8").splitlines()
                if line
            )
        }
        event_ids = {
            row["event_id"]
            for row in (
                json.loads(line)
                for line in (DATASET / "events.jsonl").read_text(encoding="utf-8").splitlines()
                if line
            )
        }
        for case in self.loaded:
            question = questions[case.question_id]
            self.assertEqual(set(case.allowed_evidence_ids), set(question["relevant_event_ids"]))
            self.assertTrue(case.verification_command_ids)
            self.assertFalse(set(case.allowed_evidence_ids) & set(case.rejected_evidence_ids))
            self.assertTrue(set(case.allowed_evidence_ids) <= event_ids)
            self.assertTrue(set(case.rejected_evidence_ids) <= event_ids)

    def test_public_fixture_does_not_duplicate_gold_text_or_private_material(self):
        if self.document is None:
            self.skipTest("fixture missing")
        serialized = json.dumps(self.document, ensure_ascii=False)
        forbidden_keys = {"query", "expected_values", "answer", "prompt", "conclusion"}

        def visit(value):
            if isinstance(value, dict):
                self.assertFalse(forbidden_keys & set(value))
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(self.document)
        for pattern in (
            r"(?i)tskey-auth-",
            r"(?i)sk-[a-z0-9]{20,}",
            r"(?i)c:\\users\\",
            r"(?i)[a-z0-9._%+-]+@gmail\.com",
        ):
            self.assertIsNone(re.search(pattern, serialized), pattern)

    def test_loader_rejects_duplicate_alias_unknown_class_and_dataset_mismatch(self):
        if self.document is None:
            self.skipTest("fixture missing")
        from comparison.contracts import ComparisonFixtureError, load_cases

        mutations = []
        duplicate = json.loads(json.dumps(self.document))
        duplicate["cases"][1]["alias"] = duplicate["cases"][0]["alias"]
        mutations.append(duplicate)
        unknown = json.loads(json.dumps(self.document))
        unknown["cases"][0]["class"] = "unknown"
        mutations.append(unknown)
        mismatch = json.loads(json.dumps(self.document))
        mismatch["dataset"]["source_sha"] = "0" * 40
        mutations.append(mismatch)

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "cases.json"
            for document in mutations:
                path.write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaises(ComparisonFixtureError):
                    load_cases(path, DATASET)


if __name__ == "__main__":
    unittest.main(verbosity=2)
