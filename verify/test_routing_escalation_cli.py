#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))


def load_runtime():
    loader = importlib.machinery.SourceFileLoader(
        "mypeople_escalation_cli_under_test", str(ROOT / "bin" / "mp")
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class RoutingEscalationCliContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.worker = "node-1/main:Worker-1"
        self.boss = "node-1/main:Boss"
        receipt = Path(self.temp.name) / "routing.json"
        receipt.write_bytes(b"{}\n")
        self.record = {
            "agent_id": self.worker,
            "backend": "codex",
            "lifecycle": "owner",
            "state": "alive",
            "retired": False,
            "session_id": "019f0000-0000-7000-8000-000000000111",
            "session_backend": "codex",
            "resume_state": "available",
            "owner_task_id": "task-1",
            "boss_id": self.boss,
            "routing_path": str(receipt),
            "routing_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
        }
        self.board = {
            "tasks": {
                "task-1": {
                    "state": "working",
                    "assignee": self.worker,
                    "comments": [],
                }
            },
            "deletedTasks": {},
        }
        self.submissions = []
        self.comments = []
        self.statuses = []
        self.executions = []
        self.mp = load_runtime()
        self.env = mock.patch.dict(
            os.environ,
            {
                "MYPEOPLE_ROUTING_ESCALATIONS_DIR": str(
                    Path(self.temp.name) / "escalations"
                ),
                "AGENT_ID": self.worker,
                "OWNER_TASK_ID": "task-1",
                "BOSS_ID": self.boss,
            },
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def fake_http(self, path, method="GET", body=None, **_kwargs):
        if path == "/todo/board":
            return copy.deepcopy(self.board)
        if path == "/todo/comment":
            self.comments.append(copy.deepcopy(body))
            self.board["tasks"][body["task_id"]]["comments"].append(
                {"body": body["body"], "by": body["by"]}
            )
            return {"ok": True}
        if path == "/task/submit":
            self.submissions.append(copy.deepcopy(body))
            return {"task_id": "queue-1"}
        raise AssertionError(f"unexpected request: {method} {path}")

    def patches(self):
        return (
            mock.patch.object(self.mp, "load_roster", return_value=[self.record]),
            mock.patch.object(self.mp, "http_json", side_effect=self.fake_http),
            mock.patch.object(
                self.mp,
                "write_status",
                side_effect=lambda *args, **kwargs: self.statuses.append(
                    (args, kwargs)
                ),
            ),
            mock.patch.object(
                self.mp,
                "execute_routing_escalation",
                create=True,
                side_effect=lambda agent, request: self.executions.append(
                    (agent, request)
                )
                or {"phase": "committed"},
            ),
        )

    def fail_namespace(self):
        return argparse.Namespace(
            failure="verification_failed",
            summary=["Verifier", "failed"],
            proof=["python3 verify/example.py: 1 failed"],
        )

    def direct_namespace(self, **updates):
        value = {
            "agent_id": self.worker,
            "request_id": None,
            "failure": "model_capability_insufficient",
            "summary": ["No", "viable", "implementation", "path."],
            "proof": ["Boss review confirmed the blocker."],
        }
        value.update(updates)
        return argparse.Namespace(**value)

    def test_parser_exposes_closed_fail_and_escalate_contracts(self):
        fail = self.mp.parser().parse_args(
            [
                "fail",
                "--failure",
                "verification_failed",
                "--summary",
                "Verifier",
                "failed",
                "--proof",
                "1 failed",
            ]
        )
        self.assertIs(fail.fn, self.mp.fail)
        direct = self.mp.parser().parse_args(
            [
                "escalate",
                self.worker,
                "--failure",
                "implementation_blocked",
                "--summary",
                "Blocked",
                "--proof",
                "No safe path",
            ]
        )
        self.assertIs(direct.fn, self.mp.escalate)

    def test_worker_fail_queues_only_an_opaque_request(self):
        patches = self.patches()
        with patches[0], patches[1], patches[2], patches[3]:
            self.mp.fail(self.fail_namespace())
        payload = self.submissions[0]
        self.assertEqual(payload["type"], "routing_escalate")
        self.assertEqual(payload["target_agent"], self.worker)
        self.assertEqual(set(payload["payload"]), {"request_id"})
        self.assertNotIn("Verifier", json.dumps(payload))
        self.assertEqual(self.statuses[0][0][1], "blocked")
        self.assertEqual(len(self.comments), 1)

    def test_worker_fail_rejects_reassignment_without_mutation(self):
        self.board["tasks"]["task-1"]["assignee"] = "node-1/main:Other"
        patches = self.patches()
        with patches[0], patches[1], patches[2], patches[3]:
            with self.assertRaisesRegex(
                SystemExit, "escalation_actor_unauthorized"
            ):
                self.mp.fail(self.fail_namespace())
        self.assertEqual(self.submissions, [])
        self.assertEqual(self.comments, [])

    def test_boss_or_operator_allowed_but_unrelated_worker_denied(self):
        patches = self.patches()
        with mock.patch.dict(os.environ, {"AGENT_ID": self.boss}), \
                patches[0], patches[1], patches[2], patches[3]:
            self.mp.escalate(self.direct_namespace())
        self.assertEqual(len(self.executions), 1)
        self.assertEqual(self.executions[0][1]["actorClass"], "boss")

        self.executions.clear()
        patches = self.patches()
        with mock.patch.dict(
            os.environ, {"AGENT_ID": "node-1/main:Other"}
        ), patches[0], patches[1], patches[2], patches[3]:
            with self.assertRaisesRegex(
                SystemExit, "escalation_actor_unauthorized"
            ):
                self.mp.escalate(self.direct_namespace())
        self.assertEqual(self.executions, [])

        patches = self.patches()
        with mock.patch.dict(os.environ, {"AGENT_ID": ""}), \
                patches[0], patches[1], patches[2], patches[3]:
            self.mp.escalate(self.direct_namespace())
        self.assertEqual(self.executions[-1][1]["actorClass"], "operator")

    def test_internal_request_uses_existing_private_record(self):
        patches = self.patches()
        with mock.patch.dict(os.environ, {"AGENT_ID": self.boss}), \
                patches[0], patches[1], patches[2], patches[3]:
            self.mp.escalate(self.direct_namespace())
        request = self.executions[-1][1]
        self.executions.clear()
        patches = self.patches()
        with mock.patch.dict(os.environ, {"AGENT_ID": ""}), \
                patches[0], patches[1], patches[2], patches[3]:
            self.mp.escalate(
                self.direct_namespace(
                    request_id=request["requestId"],
                    failure=None,
                    summary=None,
                    proof=[],
                )
            )
        self.assertEqual(self.executions[-1][1]["requestId"], request["requestId"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
