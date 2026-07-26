#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

from operator_telemetry import build_operator_telemetry, session_alias


class OperatorTelemetryContract(unittest.TestCase):
    def test_projection_is_ordered_sanitized_and_measured(self):
        roster = [
            {
                "agent_id": "node-1/main:eng-1",
                "backend": "codex",
                "model": "gpt-5.6-luna",
                "provider_profile": "codex-current",
                "session_id": "session-engineer-12345678",
                "state": "alive",
                "retired": False,
            },
            {
                "agent_id": "node-1/nightwatch:Nightwatch",
                "backend": "codex",
                "model": "gpt-5.6-luna",
                "provider_profile": "codex-current",
                "session_id": "session-nightwatch-87654321",
                "state": "alive",
                "retired": False,
            },
            {
                "agent_id": "node-1/main:Boss",
                "backend": "codex",
                "model": "gpt-5.6-sol",
                "provider_profile": "codex-primary",
                "session_id": "session-boss-abcdef12",
                "state": "alive",
                "retired": False,
                "is_master": True,
            },
            {"agent_id": "node-1/main:old", "retired": True},
        ]
        health = [
            {
                "agentId": "node-1/main:Boss",
                "provider": "codex",
                "profile": "codex-primary",
                "state": "unknown",
                "reasonCode": "insufficient_evidence",
                "observedAt": 90,
                "stale": True,
                "diagnosticRef": "do-not-expose",
            },
            {
                "agentId": "node-1/main:Boss",
                "provider": "codex",
                "profile": "codex-primary",
                "state": "authenticated",
                "reasonCode": "session_active",
                "observedAt": 99,
                "stale": False,
            },
        ]

        def usage(record):
            if record["agent_id"].endswith(":Boss"):
                return {
                    "provider": "codex",
                    "sessionId": "session-boss-abcdef12",
                    "usage": {"inputTokens": 12400, "outputTokens": 2100},
                }
            return {}

        result = build_operator_telemetry(
            roster, health, usage_reader=usage, observed_at=100
        )
        self.assertEqual(
            [row["role"] for row in result["agents"]],
            ["boss", "nightwatch", "engineer"],
        )
        boss = result["agents"][0]
        self.assertEqual(boss["sessionAlias"], "codex:abcdef12")
        self.assertEqual(
            boss["usage"],
            {
                "measurement": "measured",
                "inputTokens": 12400,
                "outputTokens": 2100,
            },
        )
        self.assertEqual(boss["health"]["state"], "authenticated")
        serialized = json.dumps(result)
        for forbidden in (
            "session-boss-abcdef12",
            "diagnosticRef",
            "do-not-expose",
            "session_id",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_missing_mismatched_and_invalid_usage_is_not_measured(self):
        base = {
            "agent_id": "node-1/main:Boss",
            "backend": "codex",
            "session_id": "session-boss-abcdef12",
            "state": "alive",
            "retired": False,
        }
        cases = (
            {},
            {
                "provider": "claude",
                "sessionId": base["session_id"],
                "usage": {"inputTokens": 1, "outputTokens": 2},
            },
            {
                "provider": "codex",
                "sessionId": "other-session",
                "usage": {"inputTokens": 1, "outputTokens": 2},
            },
            {
                "provider": "codex",
                "sessionId": base["session_id"],
                "usage": {"inputTokens": True, "outputTokens": 2},
            },
        )
        for snapshot in cases:
            with self.subTest(snapshot=snapshot):
                row = build_operator_telemetry(
                    [base], [], usage_reader=lambda _record: snapshot
                )["agents"][0]
                self.assertEqual(row["usage"], {"measurement": "not_measured"})
                self.assertEqual(row["health"]["state"], "unknown")
                self.assertTrue(row["health"]["stale"])

    def test_projection_skips_malformed_rows_and_caps_at_100(self):
        roster = [{"bad": "row"}] + [
            {
                "agent_id": f"node-1/main:eng-{index:03d}",
                "backend": "codex",
                "state": "alive",
                "retired": False,
            }
            for index in range(120)
        ]
        result = build_operator_telemetry(roster, [], observed_at=10)
        self.assertEqual(len(result["agents"]), 100)
        self.assertEqual(result["agents"][0]["agentId"], "node-1/main:eng-000")

    def test_session_alias_is_bounded(self):
        self.assertEqual(
            session_alias("codex", "session-boss-abcdef12"),
            "codex:abcdef12",
        )
        self.assertEqual(session_alias("codex", ""), "unavailable")
        self.assertEqual(session_alias("", "session-boss-abcdef12"), "unavailable")


class OperatorTelemetryRouteContract(unittest.TestCase):
    def test_route_is_authenticated_bounded_and_sanitized(self):
        source = (ROOT / "bin" / "todo-server.py").read_text(encoding="utf-8")
        auth = source.index("if not self.auth_kind():return self.json")
        route = source.index('if p=="/todo/operator-telemetry":')
        self.assertLess(auth, route)
        block = source[route:source.index(
            'if p=="/todo/provider-health":', route
        )]
        self.assertIn("build_live_operator_telemetry", block)
        self.assertIn("128 * 1024", source)
        for forbidden in ("diagnosticRef", '"session_id"'):
            self.assertNotIn(forbidden, block)


if __name__ == "__main__":
    unittest.main(verbosity=2)
