#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load_runtime():
    module_dir = str(ROOT / "bin")
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
    loader = importlib.machinery.SourceFileLoader("mp_taskspec_spawn", str(ROOT / "bin" / "mp"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def namespace(cwd, owner="task-1"):
    return argparse.Namespace(
        agent_id="node-1/main:eng-context",
        backend="codex",
        cwd=cwd,
        boss="node-1/main:Boss",
        master=False,
        model="gpt-5.6-luna",
        owner_task=owner,
        temporary=False,
    )


class TaskSpecSpawnContract(unittest.TestCase):
    def setUp(self):
        self.mp = load_runtime()
        self.mp.ensure_worker_doctrine = lambda _cwd: None
        self.mp.load_roster = lambda: []
        self.mp.update_roster = lambda _rec: None
        self.mp.write_status = lambda *_args, **_kwargs: None
        self.mp.queue_register = lambda _rec: None
        self.mp.recorder = lambda *_args: None
        self.mp.shell_export = lambda _env: "true"

    def test_owner_worker_compiles_before_window_check(self):
        order = []
        self.mp.compile_owner_task_spec = lambda task_id: order.append(("compile", task_id)) or "/tmp/task-1.json"
        self.mp.window_exists = lambda target: order.append(("window", target)) or True
        with tempfile.TemporaryDirectory() as temp:
            self.mp.spawn(namespace(temp))
        self.assertEqual(order[0], ("compile", "task-1"))
        self.assertEqual(order[1][0], "window")

    def test_compile_failure_creates_no_window(self):
        notices = []
        self.mp.compile_owner_task_spec = lambda _task_id: (_ for _ in ()).throw(
            self.mp.TaskSpecError("memory_timeout")
        )
        self.mp.notify_agent = lambda target, message: notices.append((target, message))
        self.mp.window_exists = lambda _target: (_ for _ in ()).throw(
            AssertionError("window check must not run")
        )
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(SystemExit):
            self.mp.spawn(namespace(temp))
        self.assertEqual(notices[0][0], "node-1/main:Boss")
        self.assertIn("memory_timeout", notices[0][1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
