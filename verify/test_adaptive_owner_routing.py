#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import copy
import importlib.machinery
import importlib.util
import json
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load_runtime():
    module_dir = str(ROOT / "bin")
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
    loader = importlib.machinery.SourceFileLoader(
        "mp_adaptive_owner_routing",
        str(ROOT / "bin" / "mp"),
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def load_queue_client():
    loader = importlib.machinery.SourceFileLoader(
        "queue_client_adaptive_owner_routing",
        str(ROOT / "bin" / "queue-client.py"),
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


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


def task_document(objective="Fix the Docker API integration"):
    return {
        "schemaVersion": 1,
        "taskId": "task-1",
        "projectSlug": "mypeople",
        "objective": objective,
        "acceptanceCriteria": "Focused tests pass",
        "verificationCommands": ["python3 -m unittest"],
        "allowedActions": ["read", "edit", "test"],
        "forbiddenActions": ["deploy", "push", "delete"],
        "evidencePolicy": "required",
        "routingHints": {},
    }


def owner_namespace(cwd, model=None):
    return argparse.Namespace(
        agent_id="node-1/main:adaptive-worker",
        backend="codex",
        cwd=str(cwd),
        boss="node-1/main:Boss",
        master=False,
        model=model,
        owner_task="task-1",
        temporary=False,
    )


class Result:
    returncode = 0
    stdout = ""
    stderr = ""


class AdaptiveOwnerRoutingContract(unittest.TestCase):
    def setUp(self):
        self.mp = load_runtime()

    def write_policy(self, root):
        path = Path(root) / "routing-policy.json"
        path.write_text(json.dumps(POLICY), encoding="utf-8")
        return path

    def context(self, root, objective="Fix the Docker API integration"):
        workspace = Path(root) / "workspace"
        workspace.mkdir(exist_ok=True)
        document = task_document(objective)
        document["workingDirectory"] = str(workspace)
        taskspec = Path(root) / "task-1.json"
        taskspec.write_text(
            json.dumps(document, sort_keys=True),
            encoding="utf-8",
        )
        return {
            "cwd": str(workspace),
            "document": document,
            "taskspec_sha256": self.mp.hashlib.sha256(
                taskspec.read_bytes()
            ).hexdigest(),
        }, str(taskspec)

    def test_fresh_owner_route_persists_automatic_model_and_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            context, _taskspec = self.context(temp)
            policy_path = self.write_policy(temp)
            decisions = Path(temp) / "decisions"
            ns = owner_namespace(context["cwd"])
            with mock.patch.dict(
                os.environ,
                {
                    "MYPEOPLE_ROUTING_POLICY_PATH": str(policy_path),
                    "MYPEOPLE_ROUTING_DECISIONS_DIR": str(decisions),
                    "MYPEOPLE_SESSION_CAPTURE_DIR": str(
                        Path(temp) / "capture"
                    ),
                },
                clear=False,
            ):
                decision, path, digest = self.mp.prepare_owner_routing(
                    ns,
                    context,
                    "codex-primary",
                )

            self.assertEqual(decision["tier"], "standard")
            self.assertEqual(decision["model"], "gpt-5.6-terra")
            self.assertEqual(decision["providerProfile"], "codex-primary")
            self.assertTrue(Path(path).is_file())
            self.assertRegex(digest, r"^[0-9a-f]{64}$")

    def test_non_codex_owner_keeps_existing_provider_agnostic_path(self):
        with tempfile.TemporaryDirectory() as temp:
            context, _taskspec = self.context(temp)
            ns = owner_namespace(context["cwd"], model="sonnet")
            ns.backend = "claude"
            with mock.patch.object(
                self.mp,
                "load_routing_policy",
                side_effect=AssertionError(
                    "Claude is outside Codex adaptive routing"
                ),
            ):
                decision, path, digest = self.mp.prepare_owner_routing(
                    ns,
                    context,
                    "",
                )
            self.assertIsNone(decision)
            self.assertEqual(path, "")
            self.assertEqual(digest, "")

    def test_non_codex_owner_keeps_legacy_default_model_resolution(self):
        with tempfile.TemporaryDirectory() as temp:
            context, taskspec = self.context(temp)
            contract = {
                "path": str(Path(temp) / "CONTRACT.md"),
                "sha256": "a" * 64,
                "version": "1.0.0",
                "content": "worker contract",
            }
            ns = owner_namespace(context["cwd"])
            ns.backend = "claude"

            def inspect_provider(
                _aid,
                backend,
                _master,
                _tab,
                requested,
                explicit,
            ):
                self.assertEqual(backend, "claude")
                self.assertEqual(requested, self.mp.DEFAULT_ENG_MODEL)
                self.assertFalse(explicit)
                raise RuntimeError("provider boundary reached")

            with mock.patch.object(
                self.mp,
                "resolve_owner_runtime",
                return_value=(taskspec, context, contract),
            ), mock.patch.object(
                self.mp,
                "window_exists",
                return_value=False,
            ), mock.patch.object(
                self.mp,
                "resolve_provider_runtime",
                side_effect=inspect_provider,
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "provider boundary reached",
                ):
                    self.mp.spawn(ns)

    def test_remote_codex_owner_preserves_automatic_model_selection(self):
        queue_client = load_queue_client()
        captured = []

        def run(argv, **_kwargs):
            captured.append(list(argv))
            return Result()

        task = {
            "type": "spawn",
            "target_agent": "node-2/main:worker",
            "payload": {
                "backend": "codex",
                "boss": "node-1/main:Boss",
                "model": None,
                "owner_task_id": "task-1",
            },
        }
        with mock.patch.object(
            queue_client.subprocess,
            "run",
            side_effect=run,
        ):
            ok, _output = queue_client.execute(task)

        self.assertTrue(ok)
        self.assertNotIn("--model", captured[-1])
        self.assertIn("--owner-task", captured[-1])

    def test_fresh_spawn_records_route_before_launching_selected_model(self):
        with tempfile.TemporaryDirectory() as temp:
            context, taskspec = self.context(temp)
            policy_path = self.write_policy(temp)
            decisions = Path(temp) / "decisions"
            provider_home = Path(temp) / "provider-home"
            provider_home.mkdir()
            records = []
            comments = []
            stderr = io.StringIO()
            tmux_calls = []
            contract = {
                "path": str(Path(temp) / "CONTRACT.md"),
                "sha256": "a" * 64,
                "version": "1.0.0",
                "content": "worker contract",
            }
            Path(contract["path"]).write_text(
                contract["content"],
                encoding="utf-8",
            )

            def fail_comment(*args):
                comments.append(args)
                raise RuntimeError("sensitive-provider-output")

            with mock.patch.dict(
                os.environ,
                {
                    "MYPEOPLE_ROUTING_POLICY_PATH": str(policy_path),
                    "MYPEOPLE_ROUTING_DECISIONS_DIR": str(decisions),
                    "MYPEOPLE_SESSION_CAPTURE_DIR": str(
                        Path(temp) / "capture"
                    ),
                },
                clear=False,
            ), mock.patch.object(
                self.mp,
                "resolve_owner_runtime",
                return_value=(taskspec, context, contract),
            ), mock.patch.object(
                self.mp,
                "resolve_provider_runtime",
                side_effect=lambda _aid, _backend, _master, _tab,
                requested, _explicit: (
                    requested,
                    "codex-primary",
                    str(provider_home),
                ),
            ), mock.patch.object(
                self.mp,
                "window_exists",
                return_value=False,
            ), mock.patch.object(
                self.mp,
                "run_tmux",
                side_effect=lambda argv, **_kwargs: (
                    tmux_calls.append(list(argv)) or Result()
                ),
            ), mock.patch.object(
                self.mp,
                "wait_for_composer",
                return_value=False,
            ), mock.patch.object(
                self.mp,
                "load_roster",
                return_value=[],
            ), mock.patch.object(
                self.mp,
                "update_roster",
                side_effect=records.append,
            ), mock.patch.object(
                self.mp,
                "write_status",
            ), mock.patch.object(
                self.mp,
                "queue_register",
            ), mock.patch.object(
                self.mp,
                "recorder",
            ), mock.patch.object(
                self.mp,
                "shell_export",
                return_value="true",
            ), mock.patch.object(
                self.mp,
                "ensure_routing_comment",
                side_effect=fail_comment,
            ):
                with contextlib.redirect_stderr(stderr):
                    self.mp.spawn(owner_namespace(context["cwd"]))

            record = records[-1]
            self.assertEqual(record["model"], "gpt-5.6-terra")
            self.assertEqual(record["routing_tier"], "standard")
            self.assertRegex(record["routing_sha256"], r"^[0-9a-f]{64}$")
            self.assertTrue(Path(record["routing_path"]).is_file())
            launch = next(
                call for call in tmux_calls if call[0] in {"new-session", "new-window"}
            )
            self.assertIn("gpt-5.6-terra", launch[-1])
            self.assertEqual(len(comments), 1)
            self.assertIn("routing comment deferred", stderr.getvalue())
            self.assertNotIn(
                "sensitive-provider-output",
                stderr.getvalue(),
            )

    def test_policy_denial_precedes_tmux_and_roster_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            context, taskspec = self.context(temp, "Translate the manual")
            policy_path = self.write_policy(temp)
            decisions = Path(temp) / "decisions"
            mutations = []
            contract = {
                "path": str(Path(temp) / "CONTRACT.md"),
                "sha256": "a" * 64,
                "version": "1.0.0",
                "content": "worker contract",
            }
            Path(contract["path"]).write_text(
                contract["content"],
                encoding="utf-8",
            )
            with mock.patch.dict(
                os.environ,
                {
                    "MYPEOPLE_ROUTING_POLICY_PATH": str(policy_path),
                    "MYPEOPLE_ROUTING_DECISIONS_DIR": str(decisions),
                },
                clear=False,
            ), mock.patch.object(
                self.mp,
                "resolve_owner_runtime",
                return_value=(taskspec, context, contract),
            ), mock.patch.object(
                self.mp,
                "resolve_provider_runtime",
                return_value=(
                    "unlisted-model",
                    "codex-primary",
                    str(Path(temp) / "provider-home"),
                ),
            ), mock.patch.object(
                self.mp,
                "window_exists",
                return_value=False,
            ), mock.patch.object(
                self.mp,
                "run_tmux",
                side_effect=lambda *_args, **_kwargs: mutations.append("tmux"),
            ), mock.patch.object(
                self.mp,
                "update_roster",
                side_effect=lambda _record: mutations.append("roster"),
            ), mock.patch.object(
                self.mp,
                "notify_agent",
            ):
                with self.assertRaisesRegex(
                    SystemExit,
                    "routing_model_denied",
                ):
                    self.mp.spawn(
                        owner_namespace(
                            context["cwd"],
                            model="unlisted-model",
                        )
                    )
            self.assertEqual(mutations, [])
            self.assertFalse(decisions.exists())

    def test_existing_route_is_validated_and_reused_without_policy_load(self):
        with tempfile.TemporaryDirectory() as temp:
            context, _taskspec = self.context(temp)
            policy_path = self.write_policy(temp)
            decisions = Path(temp) / "decisions"
            ns = owner_namespace(context["cwd"])
            with mock.patch.dict(
                os.environ,
                {
                    "MYPEOPLE_ROUTING_POLICY_PATH": str(policy_path),
                    "MYPEOPLE_ROUTING_DECISIONS_DIR": str(decisions),
                },
                clear=False,
            ):
                decision, path, digest = self.mp.prepare_owner_routing(
                    ns,
                    context,
                    "codex-primary",
                )
            record = {
                "owner_task_id": "task-1",
                "model": decision["model"],
                "provider_profile": "codex-primary",
                "routing_path": path,
                "routing_sha256": digest,
            }
            with mock.patch.object(
                self.mp,
                "load_routing_policy",
                side_effect=AssertionError("revive must not reclassify"),
            ):
                reused, reused_path, reused_digest = (
                    self.mp.prepare_owner_routing(
                        ns,
                        context,
                        "codex-primary",
                        receipt_record=copy.deepcopy(record),
                    )
                )
            self.assertEqual(reused, decision)
            self.assertEqual(reused_path, path)
            self.assertEqual(reused_digest, digest)

            mismatched = copy.deepcopy(record)
            mismatched["model"] = "gpt-5.6-sol"
            with self.assertRaisesRegex(
                SystemExit,
                "routing_receipt_mismatch",
            ):
                self.mp.prepare_owner_routing(
                    ns,
                    context,
                    "codex-primary",
                    receipt_record=mismatched,
                )

    def test_routing_comment_is_idempotent_by_receipt_marker(self):
        decision = {
            "taskClass": "implementation",
            "risk": "medium",
            "tier": "standard",
            "model": "gpt-5.6-terra",
            "selection": "automatic",
            "reasonCodes": [
                "implementation_signal",
                "project_policy_allowed",
            ],
            "aiUsage": "none",
        }
        digest = "a" * 64
        marker = f"[routing:{digest[:12]}]"
        calls = []

        def first_http(path, method="GET", payload=None, **_kwargs):
            calls.append((path, method, payload))
            if path == "/todo/board":
                return {"tasks": {"task-1": {"comments": []}}}
            return {"ok": True}

        with mock.patch.object(self.mp, "http_json", side_effect=first_http):
            self.assertTrue(
                self.mp.ensure_routing_comment(
                    "task-1",
                    decision,
                    digest,
                )
            )
        self.assertEqual(
            [call[0] for call in calls].count("/todo/comment"),
            1,
        )

        calls.clear()

        def second_http(path, method="GET", payload=None, **_kwargs):
            calls.append((path, method, payload))
            return {
                "tasks": {
                    "task-1": {
                        "comments": [{"body": f"{marker} already recorded"}]
                    }
                }
            }

        with mock.patch.object(self.mp, "http_json", side_effect=second_http):
            self.assertFalse(
                self.mp.ensure_routing_comment(
                    "task-1",
                    decision,
                    digest,
                )
            )
        self.assertEqual(
            [call[0] for call in calls].count("/todo/comment"),
            0,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
