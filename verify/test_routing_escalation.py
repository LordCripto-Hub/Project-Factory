#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
from pathlib import Path
import stat
import tempfile
import unittest

import routing_escalation as escalation
import task_routing


POLICY = {
    "schemaVersion": 1,
    "tiers": {
        "economy": {"model": "gpt-5.6-luna", "rank": 1},
        "standard": {"model": "gpt-5.6-terra", "rank": 2},
        "strong": {"model": "gpt-5.6-sol", "rank": 3},
    },
    "defaults": {
        "tier": "economy",
        "maxAutomaticTier": "standard",
        "maxAttempts": 2,
        "maxEscalations": 1,
    },
    "projects": {
        "mypeople": {
            "allowedModels": [
                "gpt-5.6-luna",
                "gpt-5.6-terra",
                "gpt-5.6-sol",
            ],
            "maxAutomaticTier": "strong",
            "maxAttempts": 2,
            "maxEscalations": 1,
        }
    },
}


def task_spec():
    return {
        "schemaVersion": 1,
        "taskId": "task-1",
        "projectSlug": "mypeople",
        "objective": "Fix Docker integration",
        "acceptanceCriteria": "",
        "verificationCommands": ["python3 -m unittest"],
        "allowedActions": ["read", "edit", "test"],
        "forbiddenActions": ["deploy", "push", "delete"],
        "evidencePolicy": "optional",
        "routingHints": {},
    }


class RoutingEscalationContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "routing-escalations"
        self.history = Path(self.temp.name) / "routing-history"
        self.policy = task_routing.validate_policy(copy.deepcopy(POLICY))
        self.initial_decision = task_routing.route_task(
            task_spec(), self.policy, "codex-primary"
        )

    def make_request(self, **updates):
        values = {
            "request_id": "a" * 32,
            "agent_id": "node-1/main:Worker-1",
            "task_id": "task-1",
            "boss_id": "node-1/main:Boss",
            "requested_by": "node-1/main:Worker-1",
            "actor_class": "worker",
            "failure": "verification_failed",
            "summary": "Verifier still fails.",
            "proofs": ["python3 verify/example.py: 1 failed"],
            "routing_sha256": "b" * 64,
            "now": 10.0,
        }
        values.update(updates)
        return escalation.create_request(self.root, **values)

    def test_worker_request_is_private_closed_and_queue_safe(self):
        path, request = self.make_request()
        self.assertEqual(set(request), escalation.REQUEST_FIELDS)
        self.assertEqual(stat.S_IMODE(Path(path).stat().st_mode), 0o600)
        self.assertEqual(
            stat.S_IMODE(Path(path).parent.stat().st_mode), 0o700
        )
        self.assertNotIn("session", json.dumps(request).lower())
        self.assertEqual(escalation.load_request(self.root, "a" * 32), request)

    def test_request_rejects_ineligible_or_sensitive_input(self):
        for failure in ("provider_exhausted", "timeout", "crash"):
            with self.subTest(failure=failure), self.assertRaisesRegex(
                escalation.EscalationError,
                "routing_failure_not_escalatable",
            ):
                self.make_request(failure=failure)
        for update in (
            {"summary": "x" * 2001},
            {"proofs": ["OPENAI_API_KEY=secret"]},
            {"proofs": ["Authorization: Bearer secret-value"]},
            {"request_id": "../escape"},
            {"routing_sha256": "f" * 63},
            {"actor_class": "admin"},
        ):
            with self.subTest(update=update), self.assertRaisesRegex(
                escalation.EscalationError, "escalation_request_invalid"
            ):
                self.make_request(**update)
        self.assertFalse(self.root.exists())

    def test_existing_request_is_idempotent_but_conflicts_fail_closed(self):
        first_path, first = self.make_request()
        second_path, second = self.make_request()
        self.assertEqual((first_path, first), (second_path, second))
        with self.assertRaisesRegex(
            escalation.EscalationError, "escalation_request_conflict"
        ):
            self.make_request(summary="A different summary.")

    def test_request_state_transitions_are_closed_and_terminal(self):
        _, request = self.make_request()
        queued = escalation.write_request_state(self.root, request, "queued")
        processing = escalation.write_request_state(
            self.root, queued, "processing"
        )
        committed = escalation.write_request_state(
            self.root, processing, "committed"
        )
        self.assertEqual(committed["state"], "committed")
        self.assertEqual(
            escalation.write_request_state(
                self.root, committed, "committed"
            ),
            committed,
        )
        with self.assertRaisesRegex(
            escalation.EscalationError, "escalation_state_invalid"
        ):
            escalation.write_request_state(
                self.root, committed, "rolled_back"
            )

    def test_transaction_paths_and_states_are_private_and_closed(self):
        paths = escalation.transaction_paths(self.root, "a" * 32)
        state = escalation.write_transaction_state(
            self.root,
            "a" * 32,
            "prepared",
            failure="verification_failed",
        )
        self.assertEqual(state["phase"], "prepared")
        self.assertEqual(
            escalation.load_transaction_state(self.root, "a" * 32), state
        )
        self.assertEqual(
            stat.S_IMODE(Path(paths["directory"]).stat().st_mode), 0o700
        )
        self.assertEqual(
            stat.S_IMODE(Path(paths["state"]).stat().st_mode), 0o600
        )
        with self.assertRaisesRegex(
            escalation.EscalationError, "escalation_state_invalid"
        ):
            escalation.write_transaction_state(
                self.root, "a" * 32, "committed", unexpected="value"
            )

    def test_versioned_receipts_preserve_prior_attempt(self):
        first_path, first_hash = escalation.write_history_decision(
            self.history, self.initial_decision
        )
        second = task_routing.next_route(
            self.initial_decision, "verification_failed", self.policy
        )
        second_path, second_hash = escalation.write_history_decision(
            self.history, second
        )
        self.assertNotEqual(first_path, second_path)
        self.assertNotEqual(first_hash, second_hash)
        self.assertTrue(Path(first_path).is_file())
        self.assertTrue(Path(second_path).is_file())
        self.assertEqual(
            stat.S_IMODE(Path(first_path).stat().st_mode), 0o600
        )
        self.assertEqual(
            escalation.write_history_decision(
                self.history, copy.deepcopy(second)
            ),
            (second_path, second_hash),
        )

    def test_symlinked_private_roots_fail_closed(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        linked = Path(self.temp.name) / "linked"
        linked.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(
            escalation.EscalationError, "escalation_path_invalid"
        ):
            escalation.create_request(
                linked,
                request_id="a" * 32,
                agent_id="node-1/main:Worker-1",
                task_id="task-1",
                boss_id="node-1/main:Boss",
                requested_by="node-1/main:Worker-1",
                actor_class="worker",
                failure="verification_failed",
                summary="Verifier still fails.",
                proofs=["1 failed"],
                routing_sha256="b" * 64,
            )
        self.assertEqual(list(outside.iterdir()), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
