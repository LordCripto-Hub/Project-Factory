from __future__ import annotations

import importlib.machinery
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(ROOT / "bin" / path))
    module = loader.load_module()
    return module


class Response:
    def json(self, body, status=200, **_kwargs):
        return status, body


class HudTodoLifecycleTests(unittest.TestCase):
    def test_owner_assignment_moves_ceo_review_to_working_and_persists(self):
        with tempfile.TemporaryDirectory() as temp:
            env = {"BOARD_PATH": str(Path(temp) / "board.json"), "QUEUE_SECRET": "x",
                   "HOST_ID": "verify-host", "NIGHTWATCH_IDLE_MIN": "9999"}
            with patch.dict(os.environ, env, clear=False):
                todo = load("hud_todo_lifecycle", "todo-server.py")
            task = todo.normalize_task({"id": "task-1", "text": "lifecycle", "state": "review", "test": True})
            board = todo.default_board(); board["tasks"]["task-1"] = task; board["order"] = ["task-1"]
            todo.save_board(board, allow_shrink=True)
            owner = "verify-host/main:worker"
            todo.roster_map = lambda: {owner: {"agent_id": owner, "state": "alive", "retired": False,
                                                "boss_id": todo.BOSS_FULL, "lifecycle": "owner",
                                                "owner_task_id": "task-1"}}
            status, body = todo.Handler.owner(Response(), "machine", {
                "action": "assign", "task_id": "task-1", "agent_id": owner, "by": todo.BOSS_FULL})
            self.assertEqual(status, 200)
            self.assertEqual(body["state"], "working")
            saved = todo.load_board()["tasks"]["task-1"]
            self.assertEqual(saved["state"], "working")
            self.assertEqual(saved["assignee"], owner)

    def test_exporter_requires_explicit_provenance_for_stale_baseline_recovery(self):
        exporter = load("hud_board_export", "board-export.py")
        old = {"version": 2, "tasks": {str(i): {"id": str(i)} for i in range(50)}, "order": [str(i) for i in range(50)]}
        current = {"version": 2, "tasks": {"new": {"id": "new"}}, "order": ["new"],
                   "deletedTasks": {"old": {"id": "old"}}}
        with tempfile.TemporaryDirectory() as temp:
            live = Path(temp) / "board.json"; repo = Path(temp) / "repo"
            live.write_text(json.dumps(old), encoding="utf-8")
            self.assertEqual(exporter.export_once(str(live), str(repo)), "committed")
            live.write_text(json.dumps(current), encoding="utf-8")
            self.assertTrue(exporter.lineage_proven(old, current))
            self.assertEqual(exporter.export_once(str(live), str(repo)), "quarantined")
            self.assertEqual(exporter.recover_baseline(str(live), str(repo), "live deletedTasks archive and zero shared IDs"), "baseline_recovered")
            head = subprocess.check_output(["git", "-C", str(repo), "show", "HEAD:board.v2.json"], text=True)
            self.assertEqual(len(json.loads(head)["tasks"]), 1)
            audit = json.loads((repo / "board.v2.json.BASELINE_RECOVERY.json").read_text())
            self.assertEqual(audit["previousTaskCount"], 50)
            with self.assertRaisesRegex(RuntimeError, "baseline_provenance_insufficient"):
                exporter.recover_baseline(str(live), str(repo), "unsafe")


if __name__ == "__main__":
    unittest.main(verbosity=2)
