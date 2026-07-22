#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

try:
    import memory_comparison
    IMPORT_ERROR = None
except ModuleNotFoundError as error:
    IMPORT_ERROR = error


CASES = [
    {"alias": "cmp-exact-01", "arm_order": ["baseline", "memory"]},
    {"alias": "cmp-temporal-01", "arm_order": ["memory", "baseline"]},
    {"alias": "cmp-contradiction-01", "arm_order": ["baseline", "memory"]},
]
CLEAN = {
    "worker_absent": True,
    "card_absent": True,
    "conversation_retired": True,
    "temp_artifacts_absent": True,
}


def result(alias: str, arm: str, score: int = 100):
    return {
        "score_receipt": {
            "schema_version": 1,
            "case_alias": alias,
            "components": {
                "correctness": 40,
                "provenance": 25,
                "verification": 20,
                "contradiction_avoidance": 10,
                "discipline": 5,
            },
            "score": score,
            "successful": score >= 80,
            "harmful": False,
            "violations": [],
        },
        "metrics": {
            "retrieval_latency_ms": 1.5 if arm == "memory" else "not_applicable",
            "memory_context_tokens_estimated": 18 if arm == "memory" else 0,
            "provider_tokens": "not_measured",
            "rework_count": 0,
        },
    }


class MemoryComparisonRuntimeContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.run_id = "pilot-001"

    def tearDown(self):
        self.temp.cleanup()

    def require_module(self):
        if IMPORT_ERROR:
            self.skipTest("runtime module missing")

    def start_qualified(self):
        memory_comparison.start_run(
            self.root,
            run_id=self.run_id,
            cases=CASES,
            fixture_sha256="a" * 64,
            now=lambda: 1.0,
        )
        return memory_comparison.record_offline_qualification(
            self.root,
            run_id=self.run_id,
            logical_digest="b" * 64,
            passed=True,
            now=lambda: 2.0,
        )

    def start_arm(self, alias, arm, suffix):
        return memory_comparison.start_arm(
            self.root,
            run_id=self.run_id,
            case_alias=alias,
            arm=arm,
            worker_id=f"worker-{suffix}",
            card_id=f"card-{suffix}",
            conversation_id=f"conversation-{suffix}",
            now=lambda: 3.0,
        )

    def record_and_clean(self, alias, arm):
        memory_comparison.record_arm_result(
            self.root,
            run_id=self.run_id,
            case_alias=alias,
            arm=arm,
            result=result(alias, arm),
            now=lambda: 4.0,
        )
        return memory_comparison.record_cleanup(
            self.root,
            run_id=self.run_id,
            evidence=CLEAN,
            now=lambda: 5.0,
        )

    def test_runtime_module_exists(self):
        self.assertIsNone(IMPORT_ERROR, f"comparison runtime is missing: {IMPORT_ERROR}")

    def test_happy_path_is_append_only_and_snapshots_are_atomic(self):
        self.require_module()
        state = self.start_qualified()
        self.assertEqual(state["status"], "offline_qualified")
        events_path = self.root / "memory-comparison" / "runs" / self.run_id / "events.jsonl"
        before = events_path.read_bytes()

        suffix = 0
        for case in CASES:
            for arm in case["arm_order"]:
                suffix += 1
                state = self.start_arm(case["alias"], arm, suffix)
                self.assertEqual(state["status"], "arm_started")
                state = self.record_and_clean(case["alias"], arm)
                self.assertEqual(state["status"], "arm_cleaned")
            state = memory_comparison.complete_pair(
                self.root, run_id=self.run_id, case_alias=case["alias"], now=lambda: 6.0
            )
            self.assertEqual(state["status"], "pair_completed")

        state = memory_comparison.complete_run(
            self.root, run_id=self.run_id, now=lambda: 7.0
        )
        self.assertEqual(state["status"], "completed")
        self.assertTrue(events_path.read_bytes().startswith(before))
        rows = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(rows[0]["event_type"], "run_started")
        self.assertEqual(rows[-1]["event_type"], "run_completed")
        run_dir = events_path.parent
        self.assertTrue((run_dir / "state.json").is_file())
        self.assertFalse(list(run_dir.glob("*.tmp")))
        self.assertEqual(
            json.loads((run_dir / "state.json").read_text(encoding="utf-8"))["status"],
            "completed",
        )

    def test_active_arm_order_cleanup_and_resource_reuse_fail_closed(self):
        self.require_module()
        self.start_qualified()
        self.start_arm("cmp-exact-01", "baseline", 1)
        with self.assertRaisesRegex(memory_comparison.MemoryComparisonError, "arm_already_active"):
            self.start_arm("cmp-exact-01", "memory", 2)
        state = memory_comparison.load_state(self.root, self.run_id)
        self.assertEqual(state["status"], "aborted")
        self.assertTrue(state["cleanup_required"])
        with self.assertRaisesRegex(memory_comparison.MemoryComparisonError, "run_aborted"):
            self.start_arm("cmp-exact-01", "memory", 2)
        state = memory_comparison.record_cleanup(
            self.root, run_id=self.run_id, evidence=CLEAN, now=lambda: 9.0
        )
        self.assertFalse(state["cleanup_required"])
        self.assertEqual(state["status"], "aborted")

        other = Path(self.temp.name) / "other"
        memory_comparison.start_run(other, run_id="order", cases=CASES, fixture_sha256="a" * 64)
        memory_comparison.record_offline_qualification(
            other, run_id="order", logical_digest="b" * 64, passed=True
        )
        with self.assertRaisesRegex(memory_comparison.MemoryComparisonError, "arm_order_violation"):
            memory_comparison.start_arm(
                other,
                run_id="order",
                case_alias="cmp-exact-01",
                arm="memory",
                worker_id="worker-x",
                card_id="card-x",
                conversation_id="conversation-x",
            )
        self.assertEqual(memory_comparison.load_state(other, "order")["status"], "aborted")

        reuse = Path(self.temp.name) / "reuse"
        memory_comparison.start_run(reuse, run_id="reuse", cases=CASES, fixture_sha256="a" * 64)
        memory_comparison.record_offline_qualification(
            reuse, run_id="reuse", logical_digest="b" * 64, passed=True
        )
        memory_comparison.start_arm(
            reuse,
            run_id="reuse",
            case_alias="cmp-exact-01",
            arm="baseline",
            worker_id="worker-reused",
            card_id="card-1",
            conversation_id="conversation-1",
        )
        memory_comparison.record_arm_result(
            reuse,
            run_id="reuse",
            case_alias="cmp-exact-01",
            arm="baseline",
            result=result("cmp-exact-01", "baseline"),
        )
        memory_comparison.record_cleanup(reuse, run_id="reuse", evidence=CLEAN)
        with self.assertRaisesRegex(memory_comparison.MemoryComparisonError, "resource_reuse"):
            memory_comparison.start_arm(
                reuse,
                run_id="reuse",
                case_alias="cmp-exact-01",
                arm="memory",
                worker_id="worker-reused",
                card_id="card-2",
                conversation_id="conversation-2",
            )

    def test_result_requires_cleanup_before_paired_arm_and_rejects_raw_content(self):
        self.require_module()
        self.start_qualified()
        self.start_arm("cmp-exact-01", "baseline", 1)
        memory_comparison.record_arm_result(
            self.root,
            run_id=self.run_id,
            case_alias="cmp-exact-01",
            arm="baseline",
            result=result("cmp-exact-01", "baseline"),
        )
        with self.assertRaisesRegex(memory_comparison.MemoryComparisonError, "cleanup_required"):
            self.start_arm("cmp-exact-01", "memory", 2)
        self.assertEqual(memory_comparison.load_state(self.root, self.run_id)["status"], "aborted")

        unsafe = Path(self.temp.name) / "unsafe"
        memory_comparison.start_run(unsafe, run_id="unsafe", cases=CASES, fixture_sha256="a" * 64)
        memory_comparison.record_offline_qualification(
            unsafe, run_id="unsafe", logical_digest="b" * 64, passed=True
        )
        memory_comparison.start_arm(
            unsafe,
            run_id="unsafe",
            case_alias="cmp-exact-01",
            arm="baseline",
            worker_id="worker-u",
            card_id="card-u",
            conversation_id="conversation-u",
        )
        unsafe_result = result("cmp-exact-01", "baseline")
        unsafe_result["provider_transcript"] = "raw conversation"
        with self.assertRaisesRegex(memory_comparison.MemoryComparisonError, "result_content_forbidden"):
            memory_comparison.record_arm_result(
                unsafe,
                run_id="unsafe",
                case_alias="cmp-exact-01",
                arm="baseline",
                result=unsafe_result,
            )
        self.assertEqual(memory_comparison.load_state(unsafe, "unsafe")["status"], "aborted")

    def test_public_summary_contains_aggregates_but_no_private_resource_ids(self):
        self.require_module()
        self.start_qualified()
        self.start_arm("cmp-exact-01", "baseline", 1)
        self.record_and_clean("cmp-exact-01", "baseline")
        self.start_arm("cmp-exact-01", "memory", 2)
        self.record_and_clean("cmp-exact-01", "memory")
        memory_comparison.complete_pair(
            self.root, run_id=self.run_id, case_alias="cmp-exact-01"
        )
        summary = memory_comparison.build_public_summary(self.root, self.run_id)
        serialized = json.dumps(summary, sort_keys=True)
        self.assertEqual(summary["completed_pair_count"], 1)
        self.assertEqual(summary["arm_count"], 2)
        self.assertEqual(summary["scores"], {"baseline": [100], "memory": [100]})
        for forbidden in (
            "worker-1",
            "card-1",
            "conversation-1",
            "provider_transcript",
            "fixture_sha256",
        ):
            self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main(verbosity=2)
