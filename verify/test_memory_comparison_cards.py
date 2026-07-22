#!/usr/bin/env python3
from __future__ import annotations

import importlib.machinery
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]

if "fcntl" not in sys.modules:
    fcntl = types.ModuleType("fcntl")
    fcntl.LOCK_EX = 2
    fcntl.LOCK_UN = 8
    fcntl.flock = lambda *_args, **_kwargs: None
    sys.modules["fcntl"] = fcntl
if not hasattr(os, "uname"):
    os.uname = lambda: types.SimpleNamespace(nodename="verify-host")


def load_server(temp_dir: str, *, enabled: bool):
    sys.path.insert(0, str(ROOT / "bin"))
    env = {
        "INSTALL_DIR": str(ROOT),
        "BOARD_PATH": str(Path(temp_dir) / "board.json"),
        "PROJECT_PROFILES_DIR": str(Path(temp_dir) / "profiles"),
        "QUEUE_SECRET": "verify-secret",
        "HOST_ID": "verify-host",
        "NIGHTWATCH_IDLE_MIN": "9999",
        "MYPEOPLE_MEMORY_COMPARISON_ENABLED": "1" if enabled else "0",
    }
    loader = importlib.machinery.SourceFileLoader(
        f"todo_server_comparison_{enabled}_{time.time_ns()}",
        str(ROOT / "bin" / "todo-server.py"),
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    import mpcommon
    with patch.dict(os.environ, env, clear=False), patch.dict(mpcommon.ENV, env, clear=False):
        loader.exec_module(module)
    return module


class Response:
    def json(self, body, status=200):
        return status, body

    def close_reopen(self, *_args):
        return None


def comparison_payload(deadline: float, *, arm="memory"):
    return {
        "op": "add",
        "text": "Synthetic comparison task",
        "test": True,
        "projectSlug": "project-factory",
        "contextQuestion": "Which verified constraint applies?",
        "memoryCanary": arm == "memory",
        "experiment": {
            "memory_comparison": {
                "experiment_id": "gate-b-pilot-001",
                "case_alias": "cmp-exact-01",
                "arm": arm,
                "cleanup_deadline": deadline,
            }
        },
    }


class MemoryComparisonCardContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp.cleanup()

    def test_internal_enabled_request_creates_namespaced_test_card(self):
        server = load_server(self.temp.name, enabled=True)
        deadline = time.time() + 300
        status, body = server.Handler.update(Response(), "machine", comparison_payload(deadline))
        self.assertEqual((status, body["ok"]), (200, True))
        task = server.load_board()["tasks"][body["id"]]
        self.assertTrue(task["test"])
        self.assertEqual(task["projectSlug"], "project-factory")
        self.assertEqual(task.get("experiment", {}).get("memory_comparison", {}).get("arm"), "memory")
        status, duplicate = server.Handler.update(
            Response(), "machine", comparison_payload(time.time() + 300)
        )
        self.assertEqual(
            (status, duplicate.get("error")),
            (409, "duplicate_memory_comparison_card"),
        )

    def test_feature_flag_and_machine_auth_are_both_required(self):
        deadline = time.time() + 300
        disabled = load_server(self.temp.name, enabled=False)
        status, body = disabled.Handler.update(Response(), "machine", comparison_payload(deadline))
        self.assertEqual((status, body.get("error")), (403, "memory_comparison_disabled"))

        enabled = load_server(self.temp.name, enabled=True)
        status, body = enabled.Handler.update(Response(), "browser", comparison_payload(deadline))
        self.assertEqual((status, body.get("error")), (403, "memory_comparison_internal_only"))

    def test_invalid_scope_order_or_deadline_is_rejected(self):
        server = load_server(self.temp.name, enabled=True)
        mutations = []
        wrong_project = comparison_payload(time.time() + 300, arm="baseline")
        wrong_project["projectSlug"] = "other"
        mutations.append((wrong_project, "memory_comparison_requires_project_factory"))
        wrong_alias = comparison_payload(time.time() + 300)
        wrong_alias["experiment"]["memory_comparison"]["case_alias"] = "cmp-exact-02"
        mutations.append((wrong_alias, "invalid_memory_comparison_case"))
        expired = comparison_payload(time.time() - 1)
        mutations.append((expired, "invalid_memory_comparison_deadline"))
        mismatch = comparison_payload(time.time() + 300, arm="baseline")
        mismatch["memoryCanary"] = True
        mutations.append((mismatch, "memory_comparison_arm_mismatch"))
        for payload, error in mutations:
            with self.subTest(error=error):
                status, body = server.Handler.update(Response(), "machine", payload)
                self.assertEqual((status, body.get("error")), (400, error))

    def test_normal_cards_remain_unmarked_and_marker_is_immutable(self):
        server = load_server(self.temp.name, enabled=True)
        normal = {"op": "add", "text": "Normal", "test": True, "projectSlug": "project-factory"}
        status, body = server.Handler.update(Response(), "browser", normal)
        self.assertEqual(status, 200)
        task = server.load_board()["tasks"][body["id"]]
        self.assertNotIn("experiment", task)

        status, marked = server.Handler.update(
            Response(), "machine", comparison_payload(time.time() + 300)
        )
        self.assertEqual(status, 200)
        status, changed = server.Handler.update(
            Response(),
            "machine",
            {"op": "set", "id": marked["id"], "experiment": {}},
        )
        self.assertEqual((status, changed.get("error")), (400, "memory_comparison_immutable"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
