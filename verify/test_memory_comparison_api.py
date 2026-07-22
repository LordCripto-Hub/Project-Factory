#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin"
sys.path.insert(0, str(BIN))
if "fcntl" not in sys.modules:
    fcntl = types.ModuleType("fcntl")
    fcntl.LOCK_EX = 2
    fcntl.LOCK_UN = 8
    fcntl.flock = lambda *_args, **_kwargs: None
    sys.modules["fcntl"] = fcntl
if not hasattr(os, "uname"):
    os.uname = lambda: types.SimpleNamespace(nodename="verify-host")


class Response:
    def json(self, body, status=200):
        return status, body


def load_server(temp, enabled=True):
    env = {
        "INSTALL_DIR": str(ROOT),
        "BOARD_PATH": str(Path(temp) / "board.json"),
        "PROJECT_PROFILES_DIR": str(Path(temp) / "profiles"),
        "MEMORY_COMPARISON_RUNTIME_DIR": str(Path(temp) / "runtime"),
        "QUEUE_SECRET": "verify-secret",
        "HOST_ID": "verify-host",
        "NIGHTWATCH_IDLE_MIN": "9999",
        "MYPEOPLE_MEMORY_COMPARISON_ENABLED": "1" if enabled else "0",
    }
    loader = importlib.machinery.SourceFileLoader(
        f"todo_server_comparison_api_{time.time_ns()}", str(BIN / "todo-server.py")
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    import mpcommon
    with patch.dict(os.environ, env, clear=False), patch.dict(mpcommon.ENV, env, clear=False):
        loader.exec_module(module)
    return module


def load_mp():
    loader = importlib.machinery.SourceFileLoader(
        f"mp_comparison_api_{time.time_ns()}", str(BIN / "mp")
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def cases():
    return [
        {"alias": "cmp-exact-01", "arm_order": ["baseline", "memory"]},
        {"alias": "cmp-temporal-01", "arm_order": ["memory", "baseline"]},
        {"alias": "cmp-contradiction-01", "arm_order": ["baseline", "memory"]},
    ]


def score_result():
    return {
        "score_receipt": {
            "schema_version": 1,
            "case_alias": "cmp-exact-01",
            "components": {
                "correctness": 40,
                "provenance": 25,
                "verification": 20,
                "contradiction_avoidance": 10,
                "discipline": 5,
            },
            "score": 100,
            "successful": True,
            "harmful": False,
            "violations": [],
        },
        "metrics": {
            "wall_time_ms": 250,
            "retrieval_latency_ms": "not_applicable",
            "memory_context_tokens_estimated": 0,
            "provider_tokens": "not_measured",
            "rework_count": 0,
        },
    }


class MemoryComparisonApiContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.server = load_server(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def call(self, payload, kind="machine", host="127.0.0.1"):
        if not hasattr(self.server.Handler, "memory_comparison"):
            self.skipTest("comparison API missing")
        return self.server.Handler.memory_comparison(Response(), kind, payload, host)

    def create_card(self, arm="baseline"):
        payload = {
            "op": "add",
            "text": "Synthetic comparison task",
            "test": True,
            "projectSlug": "project-factory",
            "contextQuestion": "Which verified constraint applies?",
            "memoryCanary": arm == "memory",
            "experiment": {
                "memory_comparison": {
                    "experiment_id": "pilot-001",
                    "case_alias": "cmp-exact-01",
                    "arm": arm,
                    "cleanup_deadline": time.time() + 300,
                }
            },
        }
        status, body = self.server.Handler.update(Response(), "machine", payload)
        self.assertEqual(status, 200)
        return body["id"]

    def initialize(self):
        return self.call({
            "op": "initialize",
            "run_id": "pilot-001",
            "cases": cases(),
            "fixture_sha256": "a" * 64,
            "offline_digest": "b" * 64,
        })

    def test_api_surface_exists(self):
        self.assertTrue(
            hasattr(self.server.Handler, "memory_comparison"),
            "authenticated comparison API is missing",
        )
        self.assertEqual(
            self.server.MEMORY_COMPARISON_RUNTIME_DIR,
            str(Path(self.temp.name) / "runtime"),
        )

    def test_machine_localhost_and_feature_flag_are_required(self):
        payload = {
            "op": "initialize",
            "run_id": "pilot-001",
            "cases": cases(),
            "fixture_sha256": "a" * 64,
            "offline_digest": "b" * 64,
        }
        self.assertEqual(self.call(payload, kind="browser")[0:2], (403, {"ok": False, "error": "memory_comparison_internal_only"}))
        self.assertEqual(self.call(payload, host="10.0.0.2")[0:2], (403, {"ok": False, "error": "memory_comparison_localhost_only"}))
        disabled = load_server(self.temp.name, enabled=False)
        if not hasattr(disabled.Handler, "memory_comparison"):
            self.skipTest("comparison API missing")
        status, body = disabled.Handler.memory_comparison(Response(), "machine", payload, "127.0.0.1")
        self.assertEqual((status, body["error"]), (403, "memory_comparison_disabled"))

    def test_full_api_path_returns_only_safe_status_and_summary(self):
        status, body = self.initialize()
        self.assertEqual((status, body["ok"], body["status"]["status"]), (200, True, "offline_qualified"))
        card_id = self.create_card("baseline")
        start = {
            "op": "start_arm",
            "run_id": "pilot-001",
            "case_alias": "cmp-exact-01",
            "arm": "baseline",
            "worker_id": "worker-private",
            "card_id": card_id,
            "conversation_id": "conversation-private",
        }
        self.assertEqual(self.call(start)[0], 200)
        submit = {
            "op": "submit_result",
            "run_id": "pilot-001",
            "case_alias": "cmp-exact-01",
            "arm": "baseline",
            "result": score_result(),
        }
        self.assertEqual(self.call(submit)[0], 200)
        cleanup = {"op": "cleanup", "run_id": "pilot-001", "evidence": {
            "worker_absent": True,
            "card_absent": True,
            "conversation_retired": True,
            "temp_artifacts_absent": True,
        }}
        self.assertEqual(self.call(cleanup)[0], 200)
        status, body = self.call({"op": "status", "run_id": "pilot-001"})
        serialized = json.dumps(body, sort_keys=True)
        self.assertEqual((status, body["status"]["status"]), (200, "arm_cleaned"))
        self.assertNotIn("worker-private", serialized)
        self.assertNotIn("conversation-private", serialized)
        status, body = self.call({"op": "summary", "run_id": "pilot-001"})
        self.assertEqual((status, body["summary"]["arm_count"]), (200, 1))
        status, body = self.call(
            {"op": "abort", "run_id": "pilot-001", "code": "operator_test"}
        )
        self.assertEqual((status, body["status"]["status"]), (200, "aborted"))
        self.assertFalse(body["status"]["cleanup_complete"])

    def test_normal_cards_unknown_operations_and_memory_writes_are_denied(self):
        self.initialize()
        status, normal = self.server.Handler.update(
            Response(), "machine", {"op": "add", "text": "Normal", "test": True}
        )
        self.assertEqual(status, 200)
        payload = {
            "op": "start_arm",
            "run_id": "pilot-001",
            "case_alias": "cmp-exact-01",
            "arm": "baseline",
            "worker_id": "worker-1",
            "card_id": normal["id"],
            "conversation_id": "conversation-1",
        }
        status, body = self.call(payload)
        self.assertEqual((status, body["error"]), (400, "memory_comparison_card_required"))
        for forbidden in (
            {"op": "enable"},
            {"op": "write_memory", "content": "do not store"},
            {**payload, "global_activation": True},
        ):
            with self.subTest(payload=forbidden):
                status, body = self.call(forbidden)
                self.assertEqual(status, 400)

    def test_cli_has_compact_json_commands_and_propagates_refusal(self):
        self.assertIn(
            'sub.add_parser("memory-comparison")',
            (BIN / "mp").read_text(encoding="utf-8"),
            "memory comparison CLI is missing",
        )
        mp = load_mp()
        calls = []
        mp.http_json = lambda path, method="GET", data=None, **_kw: (
            calls.append((path, method, data)) or {"ok": True, "status": {"status": "offline_qualified"}}
        )
        ns = mp.parser().parse_args(["memory-comparison", "status", "pilot-001"])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            ns.fn(ns)
        self.assertEqual(calls, [("/todo/memory-comparison", "POST", {"op": "status", "run_id": "pilot-001"})])
        self.assertEqual(output.getvalue(), '{"ok":true,"status":{"status":"offline_qualified"}}\n')

        mp.http_json = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("refused"))
        with self.assertRaisesRegex(SystemExit, "refused"):
            ns.fn(ns)


if __name__ == "__main__":
    unittest.main(verbosity=2)
