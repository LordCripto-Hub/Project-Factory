#!/usr/bin/env python3
from __future__ import annotations

import json
import hashlib
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "experiments" / "memory-gate-b"
README = EXPERIMENT / "README.md"
OFFLINE = EXPERIMENT / "reports" / "comparison-offline-039a62988625.json"
LIVE = EXPERIMENT / "reports" / "comparison-live-039a62988625.json"
OLD_OFFLINE = EXPERIMENT / "reports" / "comparison-offline-2026-07-22.json"
QUESTIONS = EXPERIMENT / "datasets" / "project-factory-history-039a62988625" / "questions.jsonl"
SOURCE_SHA = "039a62988625369f3f86c055cd476b0080395daa"
OLD_OFFLINE_SHA256 = "e064add0142eb65566b379cbc252937cc80756836853df7c2caa91ca2d4eebbd"


class MemoryComparisonPublicArtifacts(unittest.TestCase):
    def test_offline_report_exists_and_has_honest_metric_semantics(self):
        self.assertTrue(OFFLINE.is_file(), OFFLINE)
        report = json.loads(OFFLINE.read_text(encoding="utf-8"))
        self.assertTrue(report["passed"])
        self.assertEqual(report["aggregates"]["passed_count"], 6)
        self.assertEqual(report["aggregates"]["case_count"], 6)
        self.assertEqual(report["metrics"]["provider_tokens"], "not_measured")
        self.assertEqual(report["metrics"]["memory_context_tokens"], "estimated")
        self.assertEqual(report["metrics"]["retrieval_latency"], "actual")
        self.assertEqual(report["dataset"]["source_sha"], SOURCE_SHA)
        self.assertEqual(report["configuration"]["top_k"], 3)
        self.assertEqual(report["aggregates"]["escalation_count"], 0)
        self.assertRegex(report["fixture_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(report["logical_digest"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            hashlib.sha256(OLD_OFFLINE.read_bytes()).hexdigest(),
            OLD_OFFLINE_SHA256,
        )

    def test_public_artifacts_are_sanitized_and_do_not_duplicate_raw_gold_text(self):
        combined = README.read_text(encoding="utf-8") + "\n" + OFFLINE.read_text(encoding="utf-8")
        forbidden = (
            r"(?i)c:\\users\\[^\\\s]+",
            r"(?i)/users/[^/\s]+",
            r"(?i)tskey-auth-",
            r"(?i)(?:sk|ghp|github_pat)-?[a-z0-9_]{20,}",
            r"(?i)authorization\s*:\s*bearer",
            r"(?i)raw_provider_(?:conversation|prompt|reasoning)",
        )
        for pattern in forbidden:
            with self.subTest(pattern=pattern):
                self.assertIsNone(re.search(pattern, combined))
        for line in QUESTIONS.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            for key in ("question", "gold_answer", "answer"):
                value = row.get(key)
                if isinstance(value, str) and len(value) >= 24:
                    self.assertNotIn(value, combined)

    def test_readme_documents_scope_commands_stop_conditions_and_non_proof(self):
        text = README.read_text(encoding="utf-8")
        for marker in (
            "Controlled Comparison",
            "run_memory_comparison_offline.py",
            "Stop conditions",
            "does not prove production benefit",
            "not_measured",
            "estimated",
            "actual",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_readme_records_the_current_live_decision_without_claiming_promotion(self):
        text = README.read_text(encoding="utf-8")
        normalized = " ".join(text.split())
        self.assertIn("not_promoted", text)
        self.assertIn("six completed arms", normalized)
        self.assertIn("baseline scores were `75`, `65`, and `65`", normalized)
        self.assertIn("memory scores were `100`, `90`, and `90`", normalized)
        self.assertIn("cleanup was verified complete", normalized.lower())

    def test_live_report_records_complete_pairs_and_honest_non_promotion(self):
        self.assertTrue(LIVE.is_file(), LIVE)
        report = json.loads(LIVE.read_text(encoding="utf-8"))
        self.assertEqual("not_promoted", report["decision"])
        self.assertEqual(3, report["aggregates"]["completed_pair_count"])
        self.assertEqual(6, report["aggregates"]["arm_count"])
        self.assertEqual(0, report["aggregates"]["harmful_count"])
        self.assertEqual([75, 65, 65], report["aggregates"]["scores"]["baseline"])
        self.assertEqual([100, 90, 90], report["aggregates"]["scores"]["memory"])
        self.assertFalse(report["promotion_gates"]["live_retrieval_latency_measured"])
        self.assertFalse(report["promotion_gates"]["live_memory_context_measured"])
        self.assertEqual("not_measured", report["metrics"]["provider_tokens"])
        self.assertTrue(report["safety"]["cleanup_complete"])
        self.assertEqual(0, report["safety"]["container_restart_delta"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
