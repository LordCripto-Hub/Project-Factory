#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.machinery
import importlib.util
import json
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
        if hasattr(self.mp, "materialize_worker_contract"):
            self.mp.materialize_worker_contract = lambda: {
                "path": "/tmp/worker-contract.md",
                "sha256": "a" * 64,
                "version": "1.0.0",
                "content": "worker contract",
            }
        self.mp.load_roster = lambda: []
        self.mp.update_roster = lambda _rec: None
        self.mp.write_status = lambda *_args, **_kwargs: None
        self.mp.queue_register = lambda _rec: None
        self.mp.recorder = lambda *_args: None
        self.mp.shell_export = lambda _env: "true"

    def write_taskspec(self, directory, working_directory):
        path = Path(directory) / "task.json"
        path.write_text(
            json.dumps({"workingDirectory": str(working_directory)}),
            encoding="utf-8",
        )
        return str(path)

    def test_owner_cwd_is_derived_from_taskspec_and_matching_explicit_cwd_passes(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "workspace"
            workspace.mkdir()
            taskspec = self.write_taskspec(temp, workspace)
            derived = self.mp.resolve_owner_task_context(taskspec, None)
            explicit = self.mp.resolve_owner_task_context(taskspec, str(workspace))

            self.assertEqual(derived["cwd"], os.path.realpath(workspace))
            self.assertEqual(explicit["cwd"], os.path.realpath(workspace))
            self.assertRegex(derived["taskspec_sha256"], r"^[0-9a-f]{64}$")

    def test_owner_cwd_rejects_conflict_missing_directory_and_malformed_spec(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "workspace"
            workspace.mkdir()
            taskspec = self.write_taskspec(temp, workspace)
            other = Path(temp) / "other"
            other.mkdir()
            with self.assertRaisesRegex(
                self.mp.TaskSpecError, "working_directory_mismatch"
            ):
                self.mp.resolve_owner_task_context(taskspec, str(other))

            missing = self.write_taskspec(temp, Path(temp) / "missing")
            with self.assertRaisesRegex(
                self.mp.TaskSpecError, "working_directory_missing"
            ):
                self.mp.resolve_owner_task_context(missing, None)

            malformed = Path(temp) / "malformed.json"
            malformed.write_text("{", encoding="utf-8")
            with self.assertRaisesRegex(
                self.mp.TaskSpecError, "taskspec_runtime_invalid"
            ):
                self.mp.resolve_owner_task_context(str(malformed), None)

    def test_spawn_rejects_cwd_mismatch_before_tmux_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "workspace"
            workspace.mkdir()
            other = Path(temp) / "other"
            other.mkdir()
            taskspec = self.write_taskspec(temp, workspace)
            self.mp.compile_owner_task_spec = lambda _task_id: taskspec
            self.mp.window_exists = lambda _target: False
            notices = []
            self.mp.notify_agent = lambda target, message: notices.append(
                (target, message)
            )
            self.mp.run_tmux = lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("tmux creation must not run")
            )
            with self.assertRaisesRegex(SystemExit, "working_directory_mismatch"):
                self.mp.spawn(namespace(str(other)))
            self.assertEqual(notices[0][0], "node-1/main:Boss")
            self.assertIn("working_directory_mismatch", notices[0][1])

    def test_existing_owner_target_is_rejected_before_context_compilation(self):
        order = []
        self.mp.compile_owner_task_spec = lambda task_id: order.append(("compile", task_id)) or "/tmp/task-1.json"
        self.mp.window_exists = lambda target: order.append(("window", target)) or True
        with tempfile.TemporaryDirectory() as temp, self.assertRaisesRegex(SystemExit, "target_already_exists"):
            self.mp.spawn(namespace(temp))
        self.assertEqual(order, [("window", "mc-main:eng-context")])

    def test_compile_failure_creates_no_window(self):
        notices = []
        self.mp.compile_owner_task_spec = lambda _task_id: (_ for _ in ()).throw(
            self.mp.TaskSpecError("memory_timeout")
        )
        self.mp.notify_agent = lambda target, message: notices.append((target, message))
        self.mp.window_exists = lambda _target: False
        self.mp.run_tmux = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("tmux creation must not run")
        )
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(SystemExit):
            self.mp.spawn(namespace(temp))
        self.assertEqual(notices[0][0], "node-1/main:Boss")
        self.assertIn("memory_timeout", notices[0][1])


    def test_failed_compile_records_typed_metadata_without_content(self):
        events = []
        self.mp.http_json = lambda *_args, **_kwargs: {
            "tasks": {"task-1": {
                "id": "task-1", "projectSlug": "mypeople",
                "text": "private objective", "contextQuestion": "private question",
            }}
        }
        self.mp.load_profile = lambda *_args: {
            "revision": 7, "limits": {"memoryTopK": 3},
            "memory": {"enabled": True},
        }
        self.mp.compile_task_spec = lambda *_args: (_ for _ in ()).throw(
            self.mp.TaskSpecError("memory_timeout")
        )
        self.mp.record_taskspec_event = lambda event: events.append(event)
        with self.assertRaisesRegex(self.mp.TaskSpecError, "memory_timeout"):
            self.mp.compile_owner_task_spec("task-1")
        self.assertEqual(events[0]["error"], "memory_timeout")
        self.assertEqual(events[0]["projectSlug"], "mypeople")
        self.assertNotIn("question", repr(events[0]).lower())
        self.assertNotIn("objective", repr(events[0]).lower())

    def test_success_event_uses_compiler_usage_metadata(self):
        events = []
        class Document(dict):
            pass
        document = Document({
            "projectSlug": "mypeople", "profileRevision": 7,
            "memoryStatus": "ok", "memoryClaims": [{"content": "claim"}],
        })
        document.memory_metadata = {
            "responseCharacters": 5,
            "aiUsage": {"neurons": 12},
        }
        self.mp.http_json = lambda *_args, **_kwargs: {
            "tasks": {"task-1": {
                "id": "task-1", "projectSlug": "mypeople",
                "contextQuestion": "question",
            }}
        }
        self.mp.load_profile = lambda *_args: {
            "revision": 7, "limits": {"memoryTopK": 3},
            "memory": {"enabled": True},
        }
        self.mp.compile_task_spec = lambda *_args: document
        self.mp.write_task_spec = lambda *_args: "/tmp/task-1.json"
        self.mp.record_taskspec_event = lambda event: events.append(event)
        self.assertEqual(self.mp.compile_owner_task_spec("task-1"), "/tmp/task-1.json")
        self.assertEqual(events[0]["aiUsage"], {"neurons": 12})
        self.assertEqual(events[0]["responseCharacters"], 5)
        self.assertEqual(events[0]["requestedClaimCount"], 3)
        self.assertEqual(events[0]["returnedClaimCount"], 1)
    def test_operational_failures_are_typed_and_observed(self):
        events = []
        self.mp.record_taskspec_event = lambda event: events.append(event)
        self.mp.http_json = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("private board response")
        )
        with self.assertRaisesRegex(self.mp.TaskSpecError, "board_unavailable"):
            self.mp.compile_owner_task_spec("task-1")
        self.assertEqual(events[-1]["error"], "board_unavailable")
        self.assertNotIn("private", repr(events[-1]).lower())

        self.mp.http_json = lambda *_args, **_kwargs: {
            "tasks": {"task-1": {
                "id": "task-1", "projectSlug": "mypeople",
                "contextQuestion": "",
            }}
        }
        self.mp.load_profile = lambda *_args: {"revision": 7}
        document = {
            "projectSlug": "mypeople", "profileRevision": 7,
            "memoryStatus": "disabled", "memoryClaims": [],
        }
        self.mp.compile_task_spec = lambda *_args: document
        self.mp.write_task_spec = lambda *_args: (_ for _ in ()).throw(
            OSError("private write path")
        )
        with self.assertRaisesRegex(self.mp.TaskSpecError, "taskspec_write_failed"):
            self.mp.compile_owner_task_spec("task-1")
        self.assertEqual(events[-1]["error"], "taskspec_write_failed")
        self.assertNotIn("private", repr(events[-1]).lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
