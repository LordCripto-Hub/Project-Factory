#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
