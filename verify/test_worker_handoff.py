#!/usr/bin/env python3
"""Worker-to-Boss review handoff contract."""
from __future__ import annotations

import argparse
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
import sys
from unittest.mock import patch


def load_runtime(path: str):
    module_dir = str(Path(path).resolve().parent)
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
    loader = importlib.machinery.SourceFileLoader(
        "mypeople_mp_worker_handoff_under_test_" + os.urandom(4).hex(), path
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class WorkerHandoffContract(unittest.TestCase):
    def setUp(self):
        self.mp = load_runtime(os.environ.get("MYPEOPLE_MP_BIN", "/home/mp/mypeople/bin/mp"))

    def test_worker_doctrine_is_idempotent_and_requires_review_handoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "AGENTS.md"
            target.write_text("# Project rules\n\nPreserve this text.\n", encoding="utf-8")
            self.mp.ensure_worker_doctrine(tmp)
            first = target.read_text(encoding="utf-8")
            self.mp.ensure_worker_doctrine(tmp)
            second = target.read_text(encoding="utf-8")

            self.assertEqual(first, second)
            self.assertIn("Preserve this text.", first)
            self.assertIn("mp complete", first)
            self.assertIn("--proof", first)
            self.assertIn("review", first)
            self.assertNotIn("mark the card done", first.lower())

    def test_owner_spawn_exports_task_and_installs_worker_doctrine(self):
        events = []
        exported = {}
        self.mp.ensure_worker_doctrine = lambda cwd: events.append(os.path.realpath(cwd))
        self.mp.window_exists = lambda _target: True
        self.mp.load_roster = lambda: []
        self.mp.update_roster = lambda _rec: None
        self.mp.write_status = lambda *_args, **_kwargs: None
        self.mp.queue_register = lambda _rec: None
        self.mp.recorder = lambda *_args: None
        self.mp.shell_export = lambda env: exported.update(env) or "true"

        with tempfile.TemporaryDirectory() as tmp:
            self.mp.spawn(argparse.Namespace(
                agent_id="node-1/main:eng-review",
                backend="codex",
                cwd=tmp,
                boss="node-1/main:Boss",
                master=False,
                model="gpt-5.6-luna",
                owner_task="task-123",
                temporary=False,
            ))
            self.assertEqual(events, [os.path.realpath(tmp)])
            self.assertEqual(exported["OWNER_TASK_ID"], "task-123")


    def test_created_owner_worker_crosses_trust_gate_and_receives_handoff_contract(self):
        events = []
        self.mp.window_exists = lambda _target: False
        self.mp.load_roster = lambda: []
        self.mp.update_roster = lambda _rec: None
        self.mp.write_status = lambda *_args, **_kwargs: None
        self.mp.queue_register = lambda _rec: None
        self.mp.recorder = lambda *_args: None
        self.mp.run_tmux = lambda *_args, **_kwargs: type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        self.mp.ensure_worker_doctrine = lambda _cwd: None
        self.mp.wait_for_composer = lambda target: events.append(("wait", target)) or True
        self.mp.tmux_send_message = lambda target, message: events.append(("send", target, message)) or True

        with tempfile.TemporaryDirectory() as tmp:
            self.mp.spawn(argparse.Namespace(
                agent_id="node-1/main:eng-ready",
                backend="codex",
                cwd=tmp,
                boss="node-1/main:Boss",
                master=False,
                model="gpt-5.6-luna",
                owner_task="task-ready",
                temporary=False,
            ))

        self.assertIn(("wait", "mc-main:eng-ready"), events)
        sent = [event for event in events if event[0] == "send"]
        self.assertEqual(len(sent), 1)
        self.assertIn("AGENTS.md", sent[0][2])
        self.assertIn("mp complete", sent[0][2])
        self.assertIn("task-ready", sent[0][2])
    def test_complete_comments_moves_to_review_and_notifies_boss(self):
        calls = []
        notices = []
        self.mp.http_json = lambda path, method="GET", body=None, **_kwargs: calls.append((path, method, body)) or {"ok": True}
        self.mp.notify_agent = lambda target, message: notices.append((target, message))

        env = {
            "AGENT_ID": "node-1/main:eng-review",
            "OWNER_TASK_ID": "task-123",
            "BOSS_ID": "node-1/main:Boss",
        }
        with patch.dict(os.environ, env, clear=False):
            self.mp.complete(argparse.Namespace(
                summary=["Fixed", "the", "priority", "popup."],
                proof=["python verify/test_popup.py: 3 passed"],
            ))

        self.assertEqual(calls[0][0:2], ("/todo/comment", "POST"))
        self.assertEqual(calls[0][2]["task_id"], "task-123")
        self.assertIn("Fixed the priority popup.", calls[0][2]["body"])
        self.assertIn("3 passed", calls[0][2]["body"])
        self.assertEqual(calls[1][0:2], ("/todo/proof", "POST"))
        self.assertEqual(calls[1][2]["kind"], "text")
        self.assertEqual(calls[2], (
            "/todo/status",
            "POST",
            {
                "task_id": "task-123",
                "state": "review",
                "verified": False,
                "by": "node-1/main:eng-review",
            },
        ))
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0][0], "node-1/main:Boss")
        self.assertIn("task-123", notices[0][1])
        self.assertNotIn('"state": "done"', repr(calls))


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(WorkerHandoffContract)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)