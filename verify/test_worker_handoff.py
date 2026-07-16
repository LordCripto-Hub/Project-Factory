#!/usr/bin/env python3
"""Worker-to-Boss review handoff contract."""
from __future__ import annotations

import argparse
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


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
        self.mp = load_runtime(
            os.environ.get("MYPEOPLE_MP_BIN", str(ROOT / "bin" / "mp"))
        )

    def write_taskspec(self, directory):
        path = Path(directory) / "task.json"
        path.write_text(
            json.dumps({"workingDirectory": os.path.realpath(directory)}),
            encoding="utf-8",
        )
        return str(path)

    def test_worker_contract_is_external_idempotent_and_preserves_project_doctrine(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            runtime = Path(tmp) / "runtime-roles"
            project.mkdir()
            agents = project / "AGENTS.md"
            claude = project / "CLAUDE.md"
            agents.write_bytes(b"# Project AGENTS rules\n")
            claude.write_bytes(b"# Project CLAUDE rules\n")
            before_agents = agents.read_bytes()
            before_claude = claude.read_bytes()

            with patch.dict(
                os.environ,
                {"MYPEOPLE_ROLE_BUNDLES_DIR": str(runtime)},
                clear=False,
            ):
                first = self.mp.materialize_worker_contract()
                second = self.mp.materialize_worker_contract()

            self.assertEqual(first, second)
            self.assertEqual(agents.read_bytes(), before_agents)
            self.assertEqual(claude.read_bytes(), before_claude)
            self.assertEqual(
                os.path.commonpath([os.path.realpath(first["path"]), os.path.realpath(runtime)]),
                os.path.realpath(runtime),
            )
            content = Path(first["path"]).read_text(encoding="utf-8")
            self.assertIn("mp complete", content)
            self.assertIn("--proof", content)
            self.assertIn("review", content)
            self.assertEqual(
                first["sha256"],
                hashlib.sha256(content.encode("utf-8")).hexdigest(),
            )

    def test_worker_contract_adapters_are_backend_specific_but_content_equivalent(self):
        contract = {
            "path": "/runtime/roles/worker/abc/CONTRACT.md",
            "sha256": "a" * 64,
            "version": "1.0.0",
            "content": "same worker contract",
        }
        codex = self.mp.mount_worker_contract(["codex"], "codex", contract)
        claude = self.mp.mount_worker_contract(["claude"], "claude", contract)

        self.assertEqual(codex[0], "codex")
        self.assertIn("--config", codex)
        self.assertTrue(
            any(value.startswith("developer_instructions=") for value in codex)
        )
        self.assertEqual(
            claude[-2:],
            ["--append-system-prompt-file", contract["path"]],
        )

    def test_owner_spawn_exports_task_and_installs_worker_doctrine(self):
        exported = {}
        roster = []
        contract = {
            "path": "/tmp/worker-contract.md",
            "sha256": "a" * 64,
            "version": "1.0.0",
            "content": "worker contract",
        }
        self.mp.materialize_worker_contract = lambda: contract
        self.mp.window_exists = lambda _target: False
        self.mp.run_tmux = lambda *_args, **_kwargs: type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        self.mp.wait_for_composer = lambda _target: True
        self.mp.tmux_send_message = lambda *_args: True
        self.mp.load_roster = lambda: []
        self.mp.update_roster = lambda rec: roster.append(rec)
        self.mp.write_status = lambda *_args, **_kwargs: None
        self.mp.queue_register = lambda _rec: None
        self.mp.recorder = lambda *_args: None
        self.mp.shell_export = lambda env: exported.update(env) or "true"

        with tempfile.TemporaryDirectory() as tmp:
            taskspec = self.write_taskspec(tmp)
            self.mp.compile_owner_task_spec = lambda _task_id: taskspec
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
            self.assertEqual(exported["OWNER_TASK_ID"], "task-123")
            self.assertEqual(exported["MYPEOPLE_TASKSPEC_PATH"], taskspec)
            self.assertEqual(roster[0]["role_contract_path"], contract["path"])
            self.assertEqual(roster[0]["role_contract_sha256"], "a" * 64)
            self.assertEqual(roster[0]["role_contract_version"], "1.0.0")
            self.assertEqual(
                roster[0]["taskspec_sha256"],
                hashlib.sha256(Path(taskspec).read_bytes()).hexdigest(),
            )


    def test_created_owner_worker_crosses_trust_gate_and_receives_handoff_contract(self):
        events = []
        self.mp.window_exists = lambda _target: False
        self.mp.load_roster = lambda: []
        self.mp.update_roster = lambda _rec: None
        self.mp.write_status = lambda *_args, **_kwargs: None
        self.mp.queue_register = lambda _rec: None
        self.mp.recorder = lambda *_args: None
        self.mp.run_tmux = lambda *_args, **_kwargs: type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        self.mp.materialize_worker_contract = lambda: {
            "path": "/tmp/worker-contract.md",
            "sha256": "a" * 64,
            "version": "1.0.0",
            "content": "worker contract",
        }
        self.mp.wait_for_composer = lambda target: events.append(("wait", target)) or True
        self.mp.tmux_send_message = lambda target, message: events.append(("send", target, message)) or True

        with tempfile.TemporaryDirectory() as tmp:
            taskspec = self.write_taskspec(tmp)
            self.mp.compile_owner_task_spec = lambda _task_id: taskspec
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
        self.assertIn("TaskSpec", sent[0][2])
        self.assertIn("MYPEOPLE_TASKSPEC_PATH", sent[0][2])
        self.assertIn("already mounted", sent[0][2])
        self.assertNotIn("AGENTS.md", sent[0][2])
        self.assertNotIn("CLAUDE.md", sent[0][2])
        self.assertIn("mp complete", sent[0][2])
        self.assertIn("task-ready", sent[0][2])
    def test_claude_owner_receives_provider_agnostic_taskspec_handoff(self):
        sent = []
        contract = {
            "path": "/tmp/worker-contract.md",
            "sha256": "a" * 64,
            "version": "1.0.0",
            "content": "worker contract",
        }
        self.mp.materialize_worker_contract = lambda: contract
        self.mp.window_exists = lambda _target: False
        self.mp.run_tmux = lambda *_args, **_kwargs: type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        self.mp.load_roster = lambda: []
        self.mp.update_roster = lambda _rec: None
        self.mp.write_status = lambda *_args, **_kwargs: None
        self.mp.queue_register = lambda _rec: None
        self.mp.recorder = lambda *_args: None
        self.mp.wait_for_composer = lambda _target: True
        self.mp.tmux_send_message = lambda target, message: sent.append((target, message)) or True
        with tempfile.TemporaryDirectory() as tmp:
            taskspec = self.write_taskspec(tmp)
            self.mp.compile_owner_task_spec = lambda _task_id: taskspec
            self.mp.spawn(argparse.Namespace(
                agent_id="node-1/main:eng-claude", backend="claude", cwd=tmp,
                boss="node-1/main:Boss", master=False, model="sonnet",
                owner_task="task-claude", temporary=False,
            ))
        self.assertEqual(len(sent), 1)
        self.assertIn("MYPEOPLE_TASKSPEC_PATH", sent[0][1])
        self.assertIn("already mounted", sent[0][1])
        self.assertNotIn("AGENTS.md", sent[0][1])
        self.assertNotIn("CLAUDE.md", sent[0][1])

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
