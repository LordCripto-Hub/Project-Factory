#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
SPEC = importlib.util.spec_from_file_location(
    "task_routing", ROOT / "bin" / "task_routing.py"
)
task_routing = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(task_routing)


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


def task_spec(objective, **updates):
    value = {
        "schemaVersion": 1,
        "taskId": "task-1",
        "projectSlug": "mypeople",
        "objective": objective,
        "acceptanceCriteria": "",
        "verificationCommands": ["python3 -m unittest"],
        "allowedActions": ["read", "edit", "test"],
        "forbiddenActions": ["deploy", "push", "delete"],
        "evidencePolicy": "optional",
        "routingHints": {},
    }
    value.update(updates)
    return value


class RoutingPolicyContract(unittest.TestCase):
    def setUp(self):
        self.policy = task_routing.validate_policy(copy.deepcopy(POLICY))

    def test_simple_and_ambiguous_tasks_choose_economy_without_ai(self):
        cases = (
            ("Translate the operator manual", "simple_signal"),
            ("Traducir el manual del operador", "simple_signal"),
            ("Investigate an unclear report", "insufficient_strong_signal"),
        )
        for objective, reason in cases:
            with self.subTest(objective=objective):
                decision = task_routing.route_task(
                    task_spec(objective),
                    self.policy,
                    "codex-primary",
                )
                self.assertEqual(decision["taskClass"], "simple")
                self.assertEqual(decision["risk"], "low")
                self.assertEqual(decision["tier"], "economy")
                self.assertEqual(decision["model"], "gpt-5.6-luna")
                self.assertEqual(decision["selection"], "automatic")
                self.assertEqual(decision["aiUsage"], "none")
                self.assertIn(reason, decision["reasonCodes"])

    def test_english_and_spanish_implementation_choose_standard(self):
        for objective in (
            "Fix the Docker API integration",
            "Corrige el bug de integracion Docker",
        ):
            with self.subTest(objective=objective):
                decision = task_routing.route_task(
                    task_spec(objective),
                    self.policy,
                    "codex-primary",
                )
                self.assertEqual(decision["taskClass"], "implementation")
                self.assertEqual(decision["risk"], "medium")
                self.assertEqual(decision["tier"], "standard")
                self.assertEqual(decision["model"], "gpt-5.6-terra")
                self.assertEqual(decision["maxAttempts"], 2)
                self.assertEqual(decision["maxEscalations"], 1)
                self.assertEqual(decision["attemptCount"], 1)
                self.assertEqual(decision["escalationCount"], 0)
                self.assertEqual(decision["nextEligibleTier"], "strong")
                self.assertIn(
                    "implementation_signal",
                    decision["reasonCodes"],
                )

    def test_critical_signal_uses_strong_only_when_ceiling_allows(self):
        decision = task_routing.route_task(
            task_spec(
                "Repair production authentication and prevent data loss"
            ),
            self.policy,
            "codex-primary",
        )
        self.assertEqual(decision["taskClass"], "critical")
        self.assertEqual(decision["risk"], "high")
        self.assertEqual(decision["tier"], "strong")
        self.assertEqual(decision["model"], "gpt-5.6-sol")
        self.assertIn("critical_signal", decision["reasonCodes"])

        capped = task_routing.route_task(
            task_spec(
                "Repair production authentication",
                routingHints={"maxTier": "standard"},
            ),
            self.policy,
            "codex-primary",
        )
        self.assertEqual(capped["tier"], "standard")
        self.assertEqual(capped["model"], "gpt-5.6-terra")
        self.assertIn("task_tier_ceiling", capped["reasonCodes"])

    def test_explicit_hints_are_deterministic_constraints(self):
        decision = task_routing.route_task(
            task_spec(
                "Review the change",
                routingHints={
                    "taskClass": "implementation",
                    "risk": "medium",
                    "maxTier": "standard",
                },
            ),
            self.policy,
            "codex-primary",
        )
        self.assertEqual(decision["taskClass"], "implementation")
        self.assertEqual(decision["risk"], "medium")
        self.assertEqual(decision["tier"], "standard")
        self.assertIn("explicit_task_class", decision["reasonCodes"])
        self.assertIn("explicit_risk", decision["reasonCodes"])

    def test_explicit_hints_cannot_downgrade_critical_text(self):
        decision = task_routing.route_task(
            task_spec(
                "Repair production authentication and prevent data loss",
                routingHints={
                    "taskClass": "simple",
                    "risk": "low",
                },
            ),
            self.policy,
            "codex-primary",
        )
        self.assertEqual(decision["taskClass"], "critical")
        self.assertEqual(decision["risk"], "high")
        self.assertEqual(decision["tier"], "strong")
        self.assertIn("critical_signal", decision["reasonCodes"])
        self.assertIn("explicit_task_class", decision["reasonCodes"])
        self.assertIn("explicit_risk", decision["reasonCodes"])

    def test_configured_default_tier_applies_to_ambiguous_tasks(self):
        policy = copy.deepcopy(POLICY)
        policy["defaults"]["tier"] = "standard"
        decision = task_routing.route_task(
            task_spec("Investigate an unclear report"),
            policy,
            "codex-primary",
        )
        self.assertEqual(decision["tier"], "standard")
        self.assertEqual(decision["model"], "gpt-5.6-terra")
        self.assertIn("default_tier", decision["reasonCodes"])

    def test_sparse_allowlist_never_downgrades_or_skips_escalation_tiers(self):
        policy = copy.deepcopy(POLICY)
        policy["projects"]["mypeople"]["allowedModels"] = [
            "gpt-5.6-luna",
            "gpt-5.6-sol",
        ]
        implementation = task_routing.route_task(
            task_spec("Fix the Docker API integration"),
            policy,
            "codex-primary",
        )
        self.assertEqual(implementation["tier"], "strong")
        self.assertEqual(implementation["model"], "gpt-5.6-sol")

        economy = task_routing.route_task(
            task_spec("Translate the operator manual"),
            policy,
            "codex-primary",
        )
        self.assertIsNone(economy["nextEligibleTier"])
        with self.assertRaisesRegex(
            task_routing.RoutingError,
            "routing_budget_exhausted",
        ):
            task_routing.next_route(
                economy,
                "verification_failed",
                policy,
            )

    def test_required_multi_command_evidence_raises_at_most_one_tier(self):
        decision = task_routing.route_task(
            task_spec(
                "Document the operator workflow",
                evidencePolicy="required",
                verificationCommands=[
                    "python3 verify/docs.py",
                    "python3 verify/links.py",
                ],
            ),
            self.policy,
            "codex-primary",
        )
        self.assertEqual(decision["taskClass"], "simple")
        self.assertEqual(decision["risk"], "medium")
        self.assertEqual(decision["tier"], "standard")
        self.assertIn(
            "structural_verification_signal",
            decision["reasonCodes"],
        )

        for field, value in (
            ("allowedActions", "read"),
            ("forbiddenActions", [1]),
            ("evidencePolicy", "unknown"),
        ):
            with self.subTest(field=field), self.assertRaisesRegex(
                task_routing.RoutingError,
                "routing_task_invalid",
            ):
                task_routing.route_task(
                    task_spec("Document the manual", **{field: value}),
                    self.policy,
                    "codex-primary",
                )

    def test_manual_model_is_allowed_or_denied_without_substitution(self):
        allowed = task_routing.route_task(
            task_spec("Fix the API integration"),
            self.policy,
            "codex-primary",
            requested_model="gpt-5.6-terra",
        )
        self.assertEqual(allowed["selection"], "manual")
        self.assertEqual(allowed["tier"], "standard")
        self.assertEqual(allowed["model"], "gpt-5.6-terra")
        self.assertIn("manual_model", allowed["reasonCodes"])

        with self.assertRaisesRegex(
            task_routing.RoutingError,
            "routing_model_denied",
        ):
            task_routing.route_task(
                task_spec("Translate the manual"),
                self.policy,
                "codex-primary",
                requested_model="unlisted-model",
            )

        with self.assertRaisesRegex(
            task_routing.RoutingError,
            "routing_tier_denied",
        ):
            task_routing.route_task(
                task_spec(
                    "Translate the manual",
                    routingHints={"maxTier": "standard"},
                ),
                self.policy,
                "codex-primary",
                requested_model="gpt-5.6-sol",
            )

    def test_policy_validation_and_project_lookup_fail_closed(self):
        reordered = copy.deepcopy(POLICY)
        reordered["tiers"] = {
            "strong": reordered["tiers"]["strong"],
            "economy": reordered["tiers"]["economy"],
            "standard": reordered["tiers"]["standard"],
        }
        validated = task_routing.validate_policy(reordered)
        self.assertEqual(set(validated["tiers"]), set(POLICY["tiers"]))

        invalid = []
        unknown = copy.deepcopy(POLICY)
        unknown["surprise"] = True
        invalid.append(unknown)
        duplicate_rank = copy.deepcopy(POLICY)
        duplicate_rank["tiers"]["standard"]["rank"] = 1
        invalid.append(duplicate_rank)
        negative_budget = copy.deepcopy(POLICY)
        negative_budget["defaults"]["maxAttempts"] = -1
        invalid.append(negative_budget)
        impossible_default_budget = copy.deepcopy(POLICY)
        impossible_default_budget["defaults"]["maxAttempts"] = 1
        impossible_default_budget["defaults"]["maxEscalations"] = 1
        invalid.append(impossible_default_budget)
        impossible_project_budget = copy.deepcopy(POLICY)
        impossible_project_budget["projects"]["mypeople"]["maxAttempts"] = 1
        impossible_project_budget["projects"]["mypeople"][
            "maxEscalations"
        ] = 1
        invalid.append(impossible_project_budget)
        unknown_model = copy.deepcopy(POLICY)
        unknown_model["projects"]["mypeople"]["allowedModels"].append(
            "unknown-model"
        )
        invalid.append(unknown_model)

        for value in invalid:
            with self.subTest(value=value), self.assertRaisesRegex(
                task_routing.RoutingError,
                "routing_policy_invalid",
            ):
                task_routing.validate_policy(value)

        with self.assertRaisesRegex(
            task_routing.RoutingError,
            "routing_project_missing",
        ):
            task_routing.route_task(
                task_spec("Fix the API", projectSlug="missing"),
                self.policy,
                "codex-primary",
            )


class RoutingReceiptContract(unittest.TestCase):
    def setUp(self):
        self.policy = task_routing.validate_policy(copy.deepcopy(POLICY))

    def test_receipt_is_deterministic_private_atomic_and_secret_free(self):
        decision = task_routing.route_task(
            task_spec("Fix Docker integration"),
            self.policy,
            "codex-primary",
        )
        first_bytes = task_routing.canonical_decision_bytes(decision)
        second_bytes = task_routing.canonical_decision_bytes(
            copy.deepcopy(decision)
        )
        self.assertEqual(first_bytes, second_bytes)

        with tempfile.TemporaryDirectory() as temp:
            first_path, first_hash = task_routing.write_decision(
                temp,
                decision,
            )
            second_path, second_hash = task_routing.write_decision(
                temp,
                copy.deepcopy(decision),
            )
            self.assertEqual(first_path, second_path)
            self.assertEqual(first_hash, second_hash)
            self.assertRegex(first_hash, r"^[0-9a-f]{64}$")
            self.assertEqual(
                stat.S_IMODE(os.stat(first_path).st_mode),
                0o600,
            )
            self.assertEqual(
                json.loads(Path(first_path).read_text(encoding="utf-8")),
                decision,
            )
            body = Path(first_path).read_text(encoding="utf-8").lower()
            self.assertNotIn("session_id", body)
            self.assertNotIn("credential", body)
            self.assertNotIn("token", body)
            self.assertEqual(list(Path(temp).glob("*.tmp")), [])

    def test_receipt_rejects_unsafe_task_id_without_partial_file(self):
        decision = task_routing.route_task(
            task_spec("Translate docs"),
            self.policy,
            "codex-primary",
        )
        decision["taskId"] = "../escape"
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(
                task_routing.RoutingError,
                "routing_task_invalid",
            ):
                task_routing.write_decision(temp, decision)
            self.assertEqual(list(Path(temp).iterdir()), [])

    def test_receipt_rejects_extra_or_secret_bearing_fields(self):
        decision = task_routing.route_task(
            task_spec("Fix Docker integration"),
            self.policy,
            "codex-primary",
        )
        malicious = (
            {"providerSessionId": "019-provider-session"},
            {"apiKey": "secret-value"},
            {"password": "secret-value"},
            {
                "providerProfile":
                    "019f0000-0000-7000-8000-000000000999"
            },
            {"model": "sk-secret-material"},
            {
                "reasonCodes": [
                    {"providerSessionId": "019-provider-session"}
                ]
            },
        )
        for injected in malicious:
            with self.subTest(injected=injected):
                candidate = copy.deepcopy(decision)
                candidate.update(injected)
                with self.assertRaisesRegex(
                    task_routing.RoutingError,
                    "routing_task_invalid",
                ):
                    task_routing.canonical_decision_bytes(candidate)

    def test_receipt_uses_provider_profile_identifier_contract(self):
        decision = task_routing.route_task(
            task_spec("Fix Docker integration"),
            self.policy,
            "1primary",
        )
        self.assertEqual(decision["providerProfile"], "1primary")
        task_routing.canonical_decision_bytes(decision)

        for unsafe in (
            "session-abc",
            "019f0000-0000-7000-8000-000000000999",
        ):
            with self.subTest(unsafe=unsafe):
                candidate = copy.deepcopy(decision)
                candidate["providerProfile"] = unsafe
                with self.assertRaisesRegex(
                    task_routing.RoutingError,
                    "routing_task_invalid",
                ):
                    task_routing.canonical_decision_bytes(candidate)

    def test_next_route_advances_once_and_respects_budget(self):
        decision = task_routing.route_task(
            task_spec("Fix Docker integration"),
            self.policy,
            "codex-primary",
        )
        escalated = task_routing.next_route(
            decision,
            "verification_failed",
            self.policy,
        )
        self.assertEqual(escalated["tier"], "strong")
        self.assertEqual(escalated["model"], "gpt-5.6-sol")
        self.assertEqual(escalated["selection"], "automatic_escalation")
        self.assertEqual(escalated["attemptCount"], 2)
        self.assertEqual(escalated["escalationCount"], 1)
        self.assertIsNone(escalated["nextEligibleTier"])
        self.assertIn(
            "escalated_after_verification_failed",
            escalated["reasonCodes"],
        )

        with self.assertRaisesRegex(
            task_routing.RoutingError,
            "routing_budget_exhausted",
        ):
            task_routing.next_route(
                escalated,
                "verification_failed",
                self.policy,
            )

    def test_infrastructure_and_provider_failures_never_escalate_model(self):
        decision = task_routing.route_task(
            task_spec("Fix Docker integration"),
            self.policy,
            "codex-primary",
        )
        for failure in (
            "provider_exhausted",
            "authentication_failed",
            "infrastructure_failed",
            "context_missing",
            "unknown_failure",
            {},
            [],
        ):
            with self.subTest(failure=failure), self.assertRaisesRegex(
                task_routing.RoutingError,
                "routing_failure_not_escalatable",
            ):
                task_routing.next_route(
                    decision,
                    failure,
                    self.policy,
                )

    def test_next_route_rejects_malformed_receipt_budgets_with_typed_error(self):
        decision = task_routing.route_task(
            task_spec("Fix Docker integration"),
            self.policy,
            "codex-primary",
        )
        decision["maxAttempts"] = "2"
        with self.assertRaisesRegex(
            task_routing.RoutingError,
            "routing_task_invalid",
        ):
            task_routing.next_route(
                decision,
                "verification_failed",
                self.policy,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
