#!/usr/bin/env python3
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_server(temp_dir):
    sys.path.insert(0, str(ROOT / "bin"))
    env = {
        "INSTALL_DIR": str(ROOT),
        "BOARD_PATH": str(Path(temp_dir) / "board.json"),
        "QUEUE_SECRET": "verify-secret",
        "HOST_ID": "verify-host",
        "NIGHTWATCH_IDLE_MIN": "9999",
    }
    import mpcommon
    loader = importlib.machinery.SourceFileLoader(
        "todo_server_canary_priorities", str(ROOT / "bin" / "todo-server.py")
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(os.environ, env, clear=False), patch.dict(
        mpcommon.ENV, env, clear=False
    ):
        loader.exec_module(module)
    module.ROOT = temp_dir
    return module


class Response:
    def json(self, body, status=200, **_kwargs):
        return status, body


class MemoryCanaryPrioritiesContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.server = load_server(self.temp.name)
        board = self.server.default_board()
        board["tasks"]["task-1"] = self.server.normalize_task({
            "id": "task-1",
            "text": "Synthetic canary",
            "projectSlug": "project-factory",
            "contextQuestion": "Which constraint applies?",
            "memoryCanary": True,
            "test": True,
        })
        board["order"] = ["task-1"]
        self.server.save_board(board, allow_shrink=True)

    def tearDown(self):
        self.temp.cleanup()

    def test_assessment_contract_is_closed_clean_and_bounded(self):
        self.assertEqual(
            self.server.validate_canary_assessment(
                "useful", "Verified\nconstraint prevented rework."
            ),
            ("useful", "Verified constraint prevented rework."),
        )
        for value in ("good", "", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.server.validate_canary_assessment(value, "reason")
        with self.assertRaises(ValueError):
            self.server.validate_canary_assessment("neutral", "x" * 501)

    def test_run_and_retry_notify_boss_without_invoking_a_shell(self):
        messages = []
        self.server.mp_send = lambda agent, message, **_kwargs: (
            messages.append((agent, message)) or 0
        )
        status, body = self.server.Handler.memory_canary(
            Response(), "browser", {"op": "run", "taskId": "task-1"}
        )
        self.assertEqual((status, body["ok"]), (200, True))
        self.assertNotIn("--without-memory", messages[-1][1])

        status, body = self.server.Handler.memory_canary(
            Response(),
            "machine",
            {"op": "retry_without_memory", "taskId": "task-1"},
        )
        self.assertEqual((status, body["ok"]), (200, True))
        self.assertIn("--owner-task task-1 --without-memory", messages[-1][1])
        source = (ROOT / "bin" / "todo-server.py").read_text(encoding="utf-8")
        block = source[source.index("def memory_canary(self"):source.index(
            "def update(self", source.index("def memory_canary(self")
        )]
        self.assertNotIn("subprocess", block)

    def test_disable_and_assess_are_privileged_and_append_only(self):
        status, body = self.server.Handler.memory_canary(
            Response(), "nightwatch", {"op": "disable"}
        )
        self.assertEqual((status, body["error"]), (
            403, "memory_canary_control_forbidden"
        ))

        controls = []
        self.server.set_memory_canary_control = (
            lambda *_args, **kwargs: controls.append(kwargs) or {
                "enabled": False, "allowedProjects": [], "revision": 2
            }
        )
        status, body = self.server.Handler.memory_canary(
            Response(), "browser", {"op": "disable"}
        )
        self.assertEqual((status, body["control"]["enabled"]), (200, False))
        self.assertFalse(controls[0]["enabled"])

        events = []
        self.server.latest_memory_canary_receipt = lambda *_args: {
            "attemptId": "attempt-1", "taskId": "task-1"
        }
        self.server.append_memory_canary_receipt = (
            lambda _root, event: events.append(event)
        )
        status, body = self.server.Handler.memory_canary(
            Response(), "browser", {
                "op": "assess",
                "taskId": "task-1",
                "assessment": "useful",
                "rationale": "Verified\nconstraint prevented rework.",
            }
        )
        self.assertEqual((status, body["ok"]), (200, True))
        self.assertEqual(events[0]["assessment"], "useful")
        self.assertEqual(
            events[0]["rationale"],
            "Verified constraint prevented rework.",
        )

    def test_priorities_renders_compact_metrics_and_controls(self):
        html = (ROOT / "bin" / "todos.html").read_text(encoding="utf-8")
        for marker in (
            "memory-canary-strip",
            "retry_without_memory",
            "not measured",
            "sessionAlias",
            "memoryDeltaTokensEstimated",
            "Disable canary",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
