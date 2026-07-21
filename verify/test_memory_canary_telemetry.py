#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

import memory_canary


class MemoryCanaryTelemetryContract(unittest.TestCase):
    def snapshot(self, *, input_tokens, output_tokens, session="session-1"):
        return {
            "provider": "codex",
            "sessionId": session,
            "usage": {
                "inputTokens": input_tokens,
                "outputTokens": output_tokens,
            },
        }

    def test_provider_usage_delta_requires_same_attributable_session(self):
        before = self.snapshot(input_tokens=100, output_tokens=20)
        after = self.snapshot(input_tokens=220, output_tokens=50)
        self.assertEqual(
            memory_canary.provider_usage_delta(before, after),
            {"inputTokens": 120, "outputTokens": 30},
        )
        for left, right in (
            ({}, {}),
            (before, self.snapshot(input_tokens=99, output_tokens=50)),
            (before, self.snapshot(input_tokens=220, output_tokens=50, session="other")),
            (before, {**after, "provider": "claude"}),
            (before, {**after, "usage": {"inputTokens": True, "outputTokens": 50}}),
        ):
            with self.subTest(right=right):
                self.assertEqual(
                    memory_canary.provider_usage_delta(left, right),
                    "not_measured",
                )

    def test_completion_receipt_uses_alias_and_never_invents_tokens(self):
        with tempfile.TemporaryDirectory() as temp:
            start = {
                "schemaVersion": 1,
                "eventType": "start",
                "attemptId": "attempt-1",
                "taskId": "task-1",
                "startedAt": 100.0,
            }
            memory_canary.append_receipt(temp, start)
            result = memory_canary.complete_attempt(
                temp,
                attempt_id="attempt-1",
                task_id="task-1",
                runtime_record={
                    "backend": "codex",
                    "session_id": "session-1234567890",
                    "model": "gpt-5.6-luna",
                    "provider_profile": "shared",
                    "recovery_attempts": 1,
                },
                outcome="review",
                evidence_count=2,
                usage_before={},
                usage_after={},
                completed_at=112.5,
            )
            self.assertEqual(result["sessionAlias"], "codex:34567890")
            self.assertEqual(result["providerUsage"], "not_measured")
            self.assertEqual(result["durationMilliseconds"], 12500)
            self.assertEqual(result["evidenceCount"], 2)
            self.assertEqual(result["retryCount"], 1)
            self.assertNotIn("session_id", repr(result))
            self.assertEqual(
                memory_canary.latest_receipt(temp, "task-1"),
                result,
            )
            projection = memory_canary.receipt_projection(temp, "task-1")
            self.assertEqual(projection["attemptId"], "attempt-1")
            self.assertEqual(projection["providerUsage"], "not_measured")
            self.assertNotIn("session_id", repr(projection))

    def test_session_alias_is_bounded(self):
        self.assertEqual(
            memory_canary.session_alias("codex", "session-1234567890"),
            "codex:34567890",
        )
        self.assertEqual(memory_canary.session_alias("codex", ""), "unavailable")

    def test_codex_usage_snapshot_reads_only_validated_counters(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "rollout.jsonl"
            events = [
                {"type": "session_meta", "payload": {
                    "id": "session-1", "cwd": temp,
                }},
                {"type": "event_msg", "payload": {
                    "type": "token_count",
                    "info": {"total_token_usage": {
                        "input_tokens": 120,
                        "output_tokens": 30,
                    }},
                }},
            ]
            path.write_text(
                "".join(json.dumps(event) + "\n" for event in events),
                encoding="utf-8",
            )
            self.assertEqual(
                memory_canary.provider_usage_snapshot(
                    path, "codex", "session-1"
                ),
                {
                    "provider": "codex",
                    "sessionId": "session-1",
                    "usage": {"inputTokens": 120, "outputTokens": 30},
                },
            )
            self.assertEqual(
                memory_canary.provider_usage_snapshot(
                    path, "codex", "other-session"
                ),
                {},
            )

    def test_status_projection_route_is_behind_authentication(self):
        source = (ROOT / "bin" / "todo-server.py").read_text(encoding="utf-8")
        auth = source.index("if not self.auth_kind():return self.json")
        route = source.index('if p=="/todo/memory-canary":')
        self.assertLess(auth, route)
        forbidden = ("memoryQuestion", "memoryClaims", "transcript", "session_id")
        route_block = source[route:source.index(
            'if p in ("/todo/attach"', route
        )]
        for marker in forbidden:
            self.assertNotIn(marker, route_block)


if __name__ == "__main__":
    unittest.main(verbosity=2)
