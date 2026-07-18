#!/usr/bin/env python3
from __future__ import annotations

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
BIN = ROOT / "bin"
sys.path.insert(0, str(BIN))
import routing_escalation
import task_routing


def load_mp():
    loader = importlib.machinery.SourceFileLoader(
        "lossless_routing_escalation_under_test", str(BIN / "mp")
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
        "maxAutomaticTier": "strong",
        "maxAttempts": 3,
        "maxEscalations": 2,
    },
    "projects": {
        "mypeople": {
            "allowedModels": [
                "gpt-5.6-luna",
                "gpt-5.6-terra",
                "gpt-5.6-sol",
            ],
            "maxAutomaticTier": "strong",
            "maxAttempts": 3,
            "maxEscalations": 2,
        }
    },
}


def task_spec():
    return {
        "schemaVersion": 1,
        "taskId": "task-1",
        "projectSlug": "mypeople",
        "objective": "Translate the operator notes",
        "acceptanceCriteria": "",
        "verificationCommands": ["python3 verify/example.py"],
        "allowedActions": ["read", "edit", "test"],
        "forbiddenActions": ["deploy", "push", "delete"],
        "evidencePolicy": "optional",
        "routingHints": {},
    }


class Result:
    returncode = 0
    stdout = ""
    stderr = ""


class LosslessRoutingEscalationContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cwd = self.root / "project"
        self.cwd.mkdir()
        self.worker = "node-1/main:Worker-1"
        self.boss = "node-1/main:Boss"
        self.sid = "019f0000-0000-7000-8000-000000000111"
        self.policy_path = self.root / "routing-policy.json"
        self.policy_path.write_text(json.dumps(POLICY), encoding="utf-8")
        self.decision = task_routing.route_task(
            task_spec(), POLICY, "codex-primary"
        )
        self.decisions = self.root / "routing-decisions"
        path, digest = task_routing.write_decision(
            self.decisions, self.decision
        )
        taskspec = self.root / "taskspec.json"
        taskspec.write_text("{}\n", encoding="utf-8")
        role = self.root / "role.md"
        role.write_text("worker\n", encoding="utf-8")
        self.original = {
            "agent_id": self.worker,
            "host": "node-1",
            "session": "main",
            "tab": "Worker-1",
            "backend": "codex",
            "model": "gpt-5.6-luna",
            "provider_profile": "codex-primary",
            "cwd": os.path.realpath(self.cwd),
            "boss_id": self.boss,
            "is_master": False,
            "lifecycle": "owner",
            "owner_task_id": "task-1",
            "state": "alive",
            "retired": False,
            "session_id": self.sid,
            "session_backend": "codex",
            "session_profile": "codex-primary",
            "session_cwd": os.path.realpath(self.cwd),
            "resume_state": "available",
            "taskspec_path": str(taskspec),
            "taskspec_sha256": hashlib.sha256(taskspec.read_bytes()).hexdigest(),
            "role_contract_path": str(role),
            "role_contract_sha256": hashlib.sha256(role.read_bytes()).hexdigest(),
            "routing_path": path,
            "routing_sha256": digest,
            "routing_tier": "economy",
            "routing_selection": "automatic",
            "routing_reason_codes": self.decision["reasonCodes"],
            "routing_max_attempts": 3,
            "routing_max_escalations": 2,
        }
        self.other = {
            "agent_id": "node-1/main:Worker-2",
            "session": "main",
            "tab": "Worker-2",
            "backend": "codex",
            "model": "gpt-5.6-luna",
            "state": "alive",
            "retired": False,
        }
        self.roster = {
            self.worker: copy.deepcopy(self.original),
            self.other["agent_id"]: copy.deepcopy(self.other),
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
        self.events = []
        self.messages = []
        self.mp = load_mp()
        self.env = mock.patch.dict(
            os.environ,
            {
                "MYPEOPLE_ROUTING_POLICY_PATH": str(self.policy_path),
                "MYPEOPLE_ROUTING_ESCALATIONS_DIR": str(
                    self.root / "escalations"
                ),
                "MYPEOPLE_ROUTING_HISTORY_DIR": str(
                    self.root / "routing-history"
                ),
                "PROVIDER_SWITCH_LOCK": str(self.root / "provider-switch.lock"),
            },
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        _path, request = routing_escalation.create_request(
            self.root / "escalations",
            request_id="a" * 32,
            agent_id=self.worker,
            task_id="task-1",
            boss_id=self.boss,
            requested_by=self.boss,
            actor_class="boss",
            failure="model_capability_insufficient",
            summary="The implementation path exceeds this model.",
            proofs=["Boss review confirmed the capability blocker."],
            routing_sha256=digest,
            now=10.0,
        )
        self.request = routing_escalation.write_request_state(
            self.root / "escalations", request, "processing"
        )

    def fake_http(self, path, method="GET", body=None, **_kwargs):
        if path == "/todo/board":
            return copy.deepcopy(self.board)
        if path == "/todo/comment":
            self.board["tasks"][body["task_id"]]["comments"].append(
                {"body": body["body"], "by": body["by"]}
            )
            self.events.append(("comment", body["body"]))
            return {"ok": True}
        raise AssertionError(f"unexpected request: {method} {path}")

    def update_roster(self, record):
        self.roster[record["agent_id"]] = copy.deepcopy(record)

    def spawn(self, namespace, resume_session="", receipt_record=None, **_kwargs):
        self.events.append(
            ("spawn", namespace.agent_id, namespace.model, resume_session)
        )
        self.assertEqual(resume_session, self.sid)
        revived = copy.deepcopy(receipt_record)
        revived.update(
            state="alive",
            retired=False,
            resume_state="available",
            recovery_state="healthy",
        )
        self.update_roster(revived)

    def run_tmux(self, argv, **_kwargs):
        self.events.append(("tmux", tuple(argv)))
        if argv[:2] == ["capture-pane", "-p"]:
            return type(
                "Capture",
                (),
                {
                    "returncode": 0,
                    "stdout": "OPENAI_API_KEY=secret\nwork in progress",
                    "stderr": "",
                },
            )()
        return Result()

    def send_message(self, target, message):
        self.events.append(("message", target, message))
        self.messages.append((target, message))
        return True

    def patches(self):
        return (
            mock.patch.object(
                self.mp,
                "load_roster",
                side_effect=lambda: [
                    copy.deepcopy(row) for row in self.roster.values()
                ],
            ),
            mock.patch.object(
                self.mp, "update_roster", side_effect=self.update_roster
            ),
            mock.patch.object(self.mp, "http_json", side_effect=self.fake_http),
            mock.patch.object(
                self.mp,
                "resolve_provider_runtime",
                side_effect=lambda aid, backend, master, tab, model, explicit: (
                    model,
                    "codex-primary",
                    str(self.root / "codex-home"),
                ),
            ),
            mock.patch.object(self.mp, "spawn", side_effect=self.spawn),
            mock.patch.object(self.mp, "run_tmux", side_effect=self.run_tmux),
            mock.patch.object(self.mp, "window_exists", return_value=True),
            mock.patch.object(
                self.mp,
                "tmux_send_message",
                side_effect=self.send_message,
            ),
            mock.patch.object(
                self.mp,
                "write_status",
                side_effect=lambda *a, **k: self.events.append(
                    ("status", a, k)
                ),
            ),
            mock.patch.object(
                self.mp,
                "acquire_provider_transaction_lock",
                create=True,
                side_effect=lambda path, owner: self.events.append(
                    ("lock", "acquire", owner)
                ),
            ),
            mock.patch.object(
                self.mp,
                "release_provider_transaction_lock",
                create=True,
                side_effect=lambda path, owner: self.events.append(
                    ("lock", "release", owner)
                ),
            ),
        )

    def execute(self):
        patches = self.patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
                patches[5], patches[6], patches[7], patches[8], patches[9], \
                patches[10]:
            return self.mp.execute_routing_escalation(
                self.worker, copy.deepcopy(self.request)
            )

    def test_forward_changes_only_model_and_receipt(self):
        result = self.execute()
        current = self.roster[self.worker]
        self.assertEqual(result["phase"], "committed")
        self.assertEqual(current["agent_id"], self.worker)
        self.assertEqual(current["session_id"], self.sid)
        self.assertEqual(current["owner_task_id"], "task-1")
        self.assertEqual(current["model"], "gpt-5.6-terra")
        self.assertNotEqual(
            current["routing_sha256"], self.original["routing_sha256"]
        )
        self.assertEqual(self.roster[self.other["agent_id"]], self.other)
        killed = [
            event[1]
            for event in self.events
            if event[0] == "tmux" and event[1][0].startswith("kill-")
        ]
        self.assertEqual(
            killed,
            [
                ("kill-window", "-t", "mc-main:Worker-1"),
                ("kill-session", "-t", "rec-Worker-1"),
            ],
        )

    def test_continuation_is_fixed_submitted_once_and_handoff_is_private(self):
        self.execute()
        self.assertEqual(
            self.messages,
            [
                (
                    "mc-main:Worker-1",
                    self.mp.ROUTING_CONTINUATION_MESSAGE,
                )
            ],
        )
        self.assertLess(len(self.messages[0][1]), 220)
        self.assertNotIn("terminal", self.messages[0][1].lower())
        self.assertNotIn("proof", self.messages[0][1].lower())
        handoff = (
            self.root
            / "escalations"
            / "transactions"
            / ("a" * 32)
            / "handoff.json"
        )
        self.assertTrue(handoff.is_file())
        self.assertNotIn("secret", handoff.read_text(encoding="utf-8"))

    def test_duplicate_committed_request_has_no_new_side_effect(self):
        first = self.execute()
        event_count = len(self.events)
        message_count = len(self.messages)
        second = self.execute()
        self.assertEqual(first, second)
        self.assertEqual(len(self.events), event_count)
        self.assertEqual(len(self.messages), message_count)


if __name__ == "__main__":
    unittest.main(verbosity=2)
