#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
SPEC = importlib.util.spec_from_file_location(
    "queue_routing_escalation_under_test",
    ROOT / "bin" / "queue-client.py",
)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class QueueRoutingEscalationContract(unittest.TestCase):
    def task(self, **updates):
        value = {
            "type": "routing_escalate",
            "target_agent": "node-1/main:Worker-1",
            "payload": {"request_id": "a" * 32},
        }
        value.update(updates)
        return value

    def test_queue_invokes_internal_request_without_sensitive_payload(self):
        task = self.task()
        with mock.patch.object(module.subprocess, "run") as run:
            run.return_value = SimpleNamespace(
                returncode=0, stdout="committed\n", stderr=""
            )
            ok, result = module.execute(task)
        self.assertEqual(
            run.call_args.args[0][-4:],
            [
                "escalate",
                "node-1/main:Worker-1",
                "--request-id",
                "a" * 32,
            ],
        )
        self.assertEqual(run.call_args.kwargs["timeout"], 120)
        self.assertTrue(ok)
        self.assertEqual(result, "committed")
        self.assertNotIn("summary", json.dumps(task))

    def test_invalid_payload_or_target_never_starts_process(self):
        invalid = (
            self.task(payload={}),
            self.task(payload={"request_id": "a" * 32, "summary": "secret"}),
            self.task(payload={"request_id": "../escape"}),
            self.task(payload={"request_id": "A" * 32}),
            self.task(target_agent=""),
            self.task(target_agent="not-an-agent"),
        )
        with mock.patch.object(module.subprocess, "run") as run:
            for task in invalid:
                with self.subTest(task=task):
                    self.assertEqual(
                        module.execute(task),
                        (False, "invalid escalation request"),
                    )
        run.assert_not_called()

    def test_output_is_bounded(self):
        with mock.patch.object(module.subprocess, "run") as run:
            run.return_value = SimpleNamespace(
                returncode=1, stdout="x" * 5000, stderr="y" * 5000
            )
            ok, result = module.execute(self.task())
        self.assertFalse(ok)
        self.assertEqual(len(result), 4000)

    def test_timeout_returns_typed_failure(self):
        with mock.patch.object(
            module.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(["mp"], 120),
        ):
            self.assertEqual(
                module.execute(self.task()),
                (False, "routing escalation timed out"),
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
