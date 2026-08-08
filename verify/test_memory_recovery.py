#!/usr/bin/env python3
"""Contracts for the ordered bounded hybrid-memory recovery ladder."""
from __future__ import annotations

import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

from memory_recovery import RecoveryLimits, recover


LEVELS = ("fast", "deep", "exhaustive", "emergency")


def claim(name="a", content=None):
    return {
        "id": name,
        "projectSlug": "project-factory",
        "content": content or name,
        "sourceUri": f"git://project-factory/{name}",
        "sourceType": "commit",
    }


def adapters(**overrides):
    result = {name: (lambda _query, _limit: []) for name in LEVELS}
    result.update(overrides)
    return result


class MemoryRecoveryTests(unittest.TestCase):
    def test_fast_success_stops_without_later_cost(self):
        calls = []
        result = recover("query", adapters(
            fast=lambda _q, _n: calls.append("fast") or [claim()],
            deep=lambda _q, _n: calls.append("deep") or [],
            exhaustive=lambda _q, _n: calls.append("exhaustive") or [],
            emergency=lambda _q, _n: calls.append("emergency") or [],
        ))
        self.assertEqual(calls, ["fast"])
        self.assertEqual(result["selectedLevel"], "fast")
        self.assertEqual(result["status"], "memory_applied")
        self.assertEqual(result["levelsAttempted"], ["fast"])

    def test_empty_levels_end_as_insufficient_evidence(self):
        result = recover("query", adapters())
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertEqual(result["claims"], [])
        self.assertEqual(result["levelsAttempted"], list(LEVELS))

    def test_transport_failures_fall_through_and_remain_typed(self):
        def down(_query, _limit):
            raise OSError("not public")
        result = recover("query", adapters(
            fast=down, deep=down, exhaustive=down, emergency=down
        ))
        self.assertEqual(result["status"], "memory_unavailable")
        self.assertEqual(result["reasonCode"], "adapter_unavailable")
        self.assertNotIn("not public", str(result))

    def test_shared_deadline_prevents_next_adapter(self):
        ticks = iter((0.0, 0.1, 2.1, 2.1))
        calls = []
        result = recover(
            "query",
            adapters(fast=lambda _q, _n: calls.append("fast") or []),
            clock=lambda: next(ticks),
        )
        self.assertEqual(calls, ["fast"])
        self.assertEqual(result["status"], "memory_unavailable")
        self.assertEqual(result["reasonCode"], "deadline_exceeded")

    def test_claim_and_token_budgets_fail_open(self):
        result = recover(
            "query",
            adapters(fast=lambda _q, _n: [claim("large", "x" * 2_000)]),
            limits=RecoveryLimits(max_estimated_tokens=20),
        )
        self.assertEqual(result["status"], "memory_budget_exceeded")
        self.assertEqual(result["claims"], [])

    def test_malformed_claim_never_reaches_caller(self):
        result = recover(
            "query", adapters(fast=lambda _q, _n: [{"content": "unsourced"}])
        )
        self.assertEqual(result["status"], "memory_invalid_response")
        self.assertEqual(result["claims"], [])
        self.assertFalse(result["provenanceComplete"])

    def test_structured_adapter_counts_examined_fragments(self):
        result = recover("query", adapters(
            fast=lambda _q, _n: {
                "claims": [], "examinedCount": 7,
            },
            deep=lambda _q, _n: {
                "claims": [claim("deep")], "examinedCount": 5,
            },
        ))
        self.assertEqual(result["selectedLevel"], "deep")
        self.assertEqual(result["examinedCount"], 12)
        self.assertEqual(result["returnedCount"], 1)

    def test_adapter_contract_is_closed(self):
        missing = adapters()
        missing.pop("emergency")
        result = recover("query", missing)
        self.assertEqual(result["status"], "memory_invalid_response")
        self.assertEqual(result["reasonCode"], "adapter_contract_invalid")


if __name__ == "__main__":
    unittest.main(verbosity=2)
