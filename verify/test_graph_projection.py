#!/usr/bin/env python3
from __future__ import annotations

import importlib.machinery
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_server(temp_dir: str):
    if not hasattr(os, "uname"):
        os.uname = lambda: types.SimpleNamespace(nodename="verify-host")
    if "fcntl" not in sys.modules:
        try:
            import fcntl  # noqa: F401
        except ModuleNotFoundError:
            fake_fcntl = types.ModuleType("fcntl")
            fake_fcntl.LOCK_EX = 2
            fake_fcntl.LOCK_UN = 8
            fake_fcntl.flock = lambda *_args: None
            sys.modules["fcntl"] = fake_fcntl
    sys.path.insert(0, str(ROOT / "bin"))
    env = {
        "INSTALL_DIR": str(ROOT),
        "BOARD_PATH": str(Path(temp_dir) / "board.json"),
        "PROJECT_PROFILES_DIR": str(Path(temp_dir) / "profiles"),
        "QUEUE_SECRET": "verify-secret",
        "HOST_ID": "node-1",
        "NIGHTWATCH_AGENT": "node-1/nightwatch:Nightwatch",
        "NIGHTWATCH_IDLE_MIN": "9999",
    }
    loader = importlib.machinery.SourceFileLoader(
        "todo_server_graph_projection", str(ROOT / "bin" / "todo-server.py")
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    import mpcommon

    with patch.dict(os.environ, env, clear=False), patch.dict(
        mpcommon.ENV, env, clear=False
    ):
        loader.exec_module(module)
    return module


class GraphProjectionContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.server = load_server(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_graph_projection_exposes_roles_and_typed_edges(self):
        board = self.server.default_board()
        board["tasks"] = {}
        board["order"] = []
        self.server.save_board(board, allow_shrink=True)
        agents = [
            {
                "agent_id": "node-1/main:Boss",
                "boss_id": "",
                "is_master": True,
                "state": "alive",
                "status": "working",
                "tmux_target": "mc-main:Boss",
                "summary": "command",
                "backend": "codex",
            },
            {
                "agent_id": "node-1/nightwatch:Nightwatch",
                "boss_id": "node-1/main:Boss",
                "is_master": False,
                "state": "alive",
                "status": "idle",
                "tmux_target": "mc-nightwatch:Nightwatch",
                "summary": "oversight",
                "backend": "codex",
            },
            {
                "agent_id": "node-1/eng:Worker",
                "boss_id": "node-1/main:Boss",
                "is_master": False,
                "state": "alive",
                "status": "working",
                "tmux_target": "mc-eng:Worker",
                "summary": "build",
                "backend": "codex",
            },
        ]
        with patch.object(self.server, "queue_get", return_value=agents), patch.object(
            self.server, "roster_map", return_value={}
        ), patch.object(
            self.server,
            "geometry",
            return_value={
                "mc-main:Boss": (120, 36),
                "mc-nightwatch:Nightwatch": (120, 36),
                "mc-eng:Worker": (120, 36),
            },
        ):
            data = self.server.wall_data(True)

        roles = {row["agent_id"]: row["role"] for row in data["agents"]}
        self.assertEqual(roles["node-1/main:Boss"], "boss")
        self.assertEqual(roles["node-1/nightwatch:Nightwatch"], "nightwatch")
        self.assertEqual(roles["node-1/eng:Worker"], "worker")
        self.assertEqual(
            {
                (edge["parent"], edge["child"], edge["kind"])
                for edge in data["edges"]
            },
            {
                (
                    "node-1/main:Boss",
                    "node-1/nightwatch:Nightwatch",
                    "OBSERVES",
                ),
                ("node-1/main:Boss", "node-1/eng:Worker", "ASSIGNS"),
            },
        )

    def test_task_projection_exposes_card_kind_and_evidence_summary(self):
        board = self.server.default_board()
        task = self.server.normalize_task(
            {
                "id": "graph-task",
                "text": "Review release evidence",
                "state": "blocked",
                "assignee": "node-1/eng:Worker",
                "projectSlug": "graph",
                "evidencePolicy": "required",
                "doneCondition": "Evidence reviewed",
                "proofs": [{"kind": "text", "body": "blocked by fixture"}],
            }
        )
        board["tasks"] = {"graph-task": task}
        board["order"] = ["graph-task"]
        self.server.save_board(board, allow_shrink=True)
        agents = [
            {
                "agent_id": "node-1/main:Boss",
                "boss_id": "",
                "is_master": True,
                "state": "alive",
                "status": "working",
                "tmux_target": "mc-main:Boss",
            },
            {
                "agent_id": "node-1/eng:Worker",
                "boss_id": "node-1/main:Boss",
                "is_master": False,
                "state": "alive",
                "status": "working",
                "tmux_target": "mc-eng:Worker",
            },
        ]
        with patch.object(self.server, "queue_get", return_value=agents), patch.object(
            self.server, "roster_map", return_value={}
        ), patch.object(
            self.server,
            "geometry",
            return_value={"mc-main:Boss": (120, 36), "mc-eng:Worker": (120, 36)},
        ):
            data = self.server.wall_data(True)

        projected = data["tasks"][0]
        self.assertEqual(projected["card_kind"], "BLOCKED")
        self.assertEqual(projected["proof_count"], 1)
        self.assertEqual(projected["evidence_policy"], "required")
        self.assertEqual(projected["project_slug"], "graph")
        self.assertEqual(projected["done_condition"], "Evidence reviewed")
        self.assertEqual(projected["href"], "/terminal-graph?task=graph-task")


if __name__ == "__main__":
    unittest.main(verbosity=2)
