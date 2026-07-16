#!/usr/bin/env python3
from __future__ import annotations

import importlib.machinery
import json
import os
import pathlib
import stat
import sys
import tempfile
import types
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
os.environ.setdefault("QUEUE_SECRET", "test-queue-secret")
sys.path.insert(0, str(ROOT / "bin"))
if "fcntl" not in sys.modules:
    fcntl = types.ModuleType("fcntl")
    fcntl.LOCK_EX = 2
    fcntl.LOCK_UN = 8
    fcntl.flock = lambda *_args, **_kwargs: None
    sys.modules["fcntl"] = fcntl


def load_runtime():
    return importlib.machinery.SourceFileLoader(
        "durable_control_queue_" + os.urandom(4).hex(),
        str(ROOT / "bin" / "queue-server.py"),
    ).load_module()


class DurableControlQueueContract(unittest.TestCase):
    def setUp(self):
        self.queue = load_runtime()
        self.queue.TASKS.clear()
        self.temporary = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.temporary.name) / "control-queue.json"

    def tearDown(self):
        self.temporary.cleanup()

    def test_persist_is_private_atomic_and_prunes_old_terminal_records(self):
        for index in range(520):
            self.queue.TASKS[f"done-{index:03d}"] = {
                "task_id": f"done-{index:03d}", "type": "peek",
                "target_agent": "node-1/main:Boss", "payload": {},
                "status": "done", "created_at": float(index),
                "completed_at": float(index), "ok": True,
            }
        self.queue.TASKS["active"] = {
            "task_id": "active", "type": "send",
            "target_agent": "node-1/main:Boss", "payload": {"message": "hello"},
            "status": "queued", "created_at": 999.0,
        }
        self.queue.persist_tasks(str(self.path), timestamp=1000.0)
        body = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(body["schemaVersion"], 1)
        self.assertEqual(len(body["tasks"]), 501)
        self.assertIn("active", body["tasks"])
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertFalse(list(self.path.parent.glob("*.tmp")))

    def test_restart_recovers_queued_and_quarantines_delivered(self):
        self.path.write_text(json.dumps({
            "schemaVersion": 1,
            "tasks": {
                "queued": {"task_id": "queued", "type": "send", "target_agent": "node-1/main:Boss", "payload": {"message": "a"}, "status": "queued", "created_at": 1.0},
                "delivered": {"task_id": "delivered", "type": "spawn", "target_agent": "node-1/main:eng-1", "payload": {}, "status": "delivered", "created_at": 2.0, "delivered_at": 3.0},
            },
        }), encoding="utf-8")
        recovered = self.queue.load_tasks(str(self.path), timestamp=10.0)
        self.assertEqual(recovered["queued"]["status"], "queued")
        self.assertEqual(recovered["delivered"]["status"], "uncertain")
        self.assertEqual(recovered["delivered"]["recovery"], "server_restart_after_delivery")

    def test_delivery_result_and_explicit_retry_are_persisted(self):
        self.queue.TASKS["task-1"] = {
            "task_id": "task-1", "type": "send",
            "target_agent": "node-1/main:Boss", "payload": {"message": "hello"},
            "status": "queued", "created_at": 1.0,
        }
        delivered = self.queue.claim_tasks_for_host("node-1", str(self.path), timestamp=2.0)
        self.assertEqual([row["task_id"] for row in delivered], ["task-1"])
        self.assertEqual(json.loads(self.path.read_text())["tasks"]["task-1"]["status"], "delivered")
        self.queue.complete_task("task-1", False, "boom", str(self.path), timestamp=3.0)
        self.assertEqual(json.loads(self.path.read_text())["tasks"]["task-1"]["status"], "failed")
        retried = self.queue.retry_task("task-1", str(self.path), timestamp=4.0)
        self.assertEqual(retried["status"], "queued")
        self.assertEqual(retried["attempt"], 2)
        with self.assertRaisesRegex(ValueError, "not retryable"):
            self.queue.retry_task("task-1", str(self.path), timestamp=5.0)

    def test_operator_cli_exposes_status_and_explicit_retry(self):
        cli = (ROOT / "bin" / "mp").read_text(encoding="utf-8")
        self.assertIn('sub.add_parser("queue-retry")', cli)
        self.assertIn('sub.add_parser("queue-status")', cli)
        self.assertIn('http_json("/task/retry","POST"', cli)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(DurableControlQueueContract)
    )
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("PASS durable control queue contract")
