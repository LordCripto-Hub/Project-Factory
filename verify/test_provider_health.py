#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

from provider_health import (
    build_health_receipt,
    classify_provider_health,
    read_health_receipts,
    write_health_receipt,
)


class ProviderHealthContract(unittest.TestCase):
    def test_six_states_and_precedence_are_deterministic(self):
        cases = (
            ({"processAlive": False}, "process_dead"),
            ({"processAlive": True, "authRejected": True}, "expired"),
            ({"processAlive": True, "quotaRejected": True}, "quota_exhausted"),
            ({"processAlive": True, "transportFailure": True}, "unreachable"),
            ({"processAlive": True, "authenticatedInteraction": True}, "authenticated"),
            ({"processAlive": True}, "unknown"),
        )
        for evidence, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(classify_provider_health(evidence), expected)
        self.assertEqual(
            classify_provider_health({
                "processAlive": True,
                "transportFailure": True,
                "message": "credentials maybe expired",
            }),
            "unreachable",
        )

    def test_receipts_are_private_sanitized_and_become_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt = build_health_receipt(
                "codex", "primary", "node-1/main:Boss",
                {"processAlive": True, "authenticatedInteraction": True,
                 "diagnosticRef": "Authorization: Bearer secret-value"},
                "spawn", now=100.0,
            )
            path = Path(write_health_receipt(tmp, receipt))
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertNotIn("secret-value", path.read_text(encoding="utf-8"))
            rows = read_health_receipts(tmp, stale_after=30, now=131.0)
            self.assertEqual(rows[0]["state"], "authenticated")
            self.assertTrue(rows[0]["stale"])

    def test_receipt_schema_is_bounded(self):
        receipt = build_health_receipt(
            "codex", "primary", "node-1/main:Boss",
            {"processAlive": True}, "manual", now=5.0,
        )
        self.assertEqual(
            set(receipt),
            {"provider", "profile", "agentId", "state", "reasonCode",
             "observedAt", "source", "diagnosticRef"},
        )
        self.assertLess(len(json.dumps(receipt)), 1024)


if __name__ == "__main__":
    unittest.main(verbosity=2)
