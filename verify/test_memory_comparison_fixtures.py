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
DATASET = EXPERIMENT / "datasets" / "project-factory-history-80dce6f86632"
EXPECTED = {
    "cmp-exact-01": ("hist-exact-005", "exact_constraint", True, ("baseline", "memory")),
    "cmp-exact-02": ("hist-exact-006", "exact_constraint", False, ()),
    "cmp-temporal-01": ("hist-temporal-006", "temporal_continuation", True, ("memory", "baseline")),
    "cmp-temporal-02": ("hist-temporal-004", "temporal_continuation", False, ()),
    "cmp-contradiction-01": ("hist-contradiction-004", "contradiction_prevention", True, ("baseline", "memory")),
    "cmp-contradiction-02": ("hist-contradiction-002", "contradiction_prevention", False, ()),
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
        cls.loaded = load_cases(CASES, DATASET)

    def test_fixture_exists(self):
        self.assertTrue(CASES.is_file(), "comparison case fixture is missing")

    def test_matrix_is_exactly_the_approved_six_cases(self):
        if self.loaded is None:
            self.skipTest("fixture missing")
        actual = {
            case.alias: (
                case.question_id,
                case.case_class,
                case.live,
                case.arm_order,
            )
            for case in self.loaded
        }
        self.assertEqual(actual, EXPECTED)

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
        for case in self.loaded:
            question = questions[case.question_id]
            self.assertEqual(set(case.allowed_evidence_ids), set(question["relevant_event_ids"]))
            self.assertTrue(case.verification_command_ids)
            self.assertFalse(set(case.allowed_evidence_ids) & set(case.rejected_evidence_ids))

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
