#!/usr/bin/env python3
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
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


def load_server(temp_dir: str):
    sys.path.insert(0, str(ROOT / "bin"))
    env = {
        "INSTALL_DIR": str(ROOT),
        "BOARD_PATH": str(Path(temp_dir) / "board.json"),
        "PROJECT_PROFILES_DIR": str(Path(temp_dir) / "profiles"),
        "QUEUE_SECRET": "verify-secret",
        "HOST_ID": "verify-host",
        "NIGHTWATCH_IDLE_MIN": "9999",
    }
    loader = importlib.machinery.SourceFileLoader(
        "todo_server_projects", str(ROOT / "bin" / "todo-server.py")
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    import mpcommon
    with patch.dict(os.environ, env, clear=False), patch.dict(
        mpcommon.ENV, env, clear=False
    ):
        loader.exec_module(module)
    return module


class TaskProjectFieldsContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.server = load_server(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_missing_env_file_still_accepts_process_overrides(self):
        missing = str(Path(self.temp.name) / "missing.env")
        with patch.dict(os.environ, {"QUEUE_SECRET": "override-secret"}, clear=False):
            result = self.server.read_env(missing)
        self.assertEqual(result["QUEUE_SECRET"], "override-secret")

    def test_legacy_task_migrates_without_inventing_project(self):
        task = {"id": "legacy", "text": "Legacy task"}
        self.server.normalize_task(task)
        self.assertEqual(task["projectSlug"], "")
        self.assertEqual(task["contextQuestion"], "")
        self.assertIs(task["memoryCanary"], False)

    def test_project_slug_contract(self):
        self.assertEqual(self.server.validate_project_slug("my-project"), "my-project")
        for value in ("", "Upper", "two--hyphens", "../bad", "bad space", "a" * 65):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.server.validate_project_slug(value)

    def test_context_question_is_clean_and_bounded(self):
        self.assertEqual(
            self.server.validate_context_question("What\nchanged?"), "What changed?"
        )
        with self.assertRaises(ValueError):
            self.server.validate_context_question("x" * 501)

    def test_profile_directory_uses_merged_runtime_configuration(self):
        source = (ROOT / "bin" / "todo-server.py").read_text(encoding="utf-8")
        self.assertIn('ENV.get("PROJECT_PROFILES_DIR"', source)
        self.assertNotIn('os.environ.get("PROJECT_PROFILES_DIR"', source)

    def test_profile_discovery_returns_only_matching_valid_slugs(self):
        directory = Path(self.temp.name) / "profiles"
        directory.mkdir()
        (directory / "mypeople.json").write_text(
            json.dumps({"slug": "mypeople"}), encoding="utf-8"
        )
        (directory / "mismatch.json").write_text(
            json.dumps({"slug": "other"}), encoding="utf-8"
        )
        (directory / "Bad Name.json").write_text("{}", encoding="utf-8")
        self.assertEqual(self.server.available_project_slugs(), ["mypeople"])

    def test_partial_update_preserves_project_context(self):
        board = self.server.default_board()
        board["tasks"]["task-1"] = self.server.normalize_task({
            "id": "task-1",
            "text": "Original",
            "projectSlug": "mypeople",
            "contextQuestion": "Which constraint applies?",
        })
        board["order"] = ["task-1"]
        self.server.save_board(board, allow_shrink=True)

        class Response:
            def json(self, body, status=200):
                return status, body
            def close_reopen(self, *_args):
                return None

        status, body = self.server.Handler.update(
            Response(), "boss", {"op": "set", "id": "task-1", "text": "Changed"}
        )
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        task = self.server.load_board()["tasks"]["task-1"]
        self.assertEqual(task["projectSlug"], "mypeople")
        self.assertEqual(task["contextQuestion"], "Which constraint applies?")

    def test_memory_canary_requires_the_project_factory_contract(self):
        with self.assertRaisesRegex(
            ValueError, "memory_canary_requires_project_factory"
        ):
            self.server.validate_memory_canary(True, "other", "Question?")
        with self.assertRaisesRegex(ValueError, "memory_canary_requires_question"):
            self.server.validate_memory_canary(True, "project-factory", "")
        with self.assertRaisesRegex(ValueError, "invalid_memory_canary"):
            self.server.validate_memory_canary("true", "project-factory", "Question?")
        self.assertTrue(
            self.server.validate_memory_canary(
                True,
                "project-factory",
                "Which verified constraint applies?",
            )
        )
        self.assertFalse(self.server.validate_memory_canary(False, "", ""))

    def test_memory_canary_update_is_explicit_preserved_and_privileged(self):
        board = self.server.default_board()
        board["tasks"]["task-1"] = self.server.normalize_task({
            "id": "task-1",
            "text": "Canary",
            "projectSlug": "project-factory",
            "contextQuestion": "Which verified constraint applies?",
            "memoryCanary": True,
        })
        board["order"] = ["task-1"]
        self.server.save_board(board, allow_shrink=True)

        class Response:
            def json(self, body, status=200):
                return status, body
            def close_reopen(self, *_args):
                return None

        status, _ = self.server.Handler.update(
            Response(),
            "browser",
            {"op": "set", "id": "task-1", "text": "Changed"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(
            self.server.load_board()["tasks"]["task-1"]["memoryCanary"]
        )

        status, body = self.server.Handler.update(
            Response(),
            "nightwatch",
            {"op": "set", "id": "task-1", "memoryCanary": False},
        )
        self.assertEqual((status, body["error"]), (403, "memory_canary_control_forbidden"))

        status, _ = self.server.Handler.update(
            Response(),
            "machine",
            {"op": "set", "id": "task-1", "memoryCanary": False},
        )
        self.assertEqual(status, 200)
        self.assertFalse(
            self.server.load_board()["tasks"]["task-1"]["memoryCanary"]
        )

    def test_memory_canary_validates_the_combined_final_card(self):
        board = self.server.default_board()
        board["tasks"]["task-1"] = self.server.normalize_task({
            "id": "task-1",
            "text": "Canary",
            "projectSlug": "project-factory",
            "contextQuestion": "Question?",
            "memoryCanary": True,
        })
        board["order"] = ["task-1"]
        self.server.save_board(board, allow_shrink=True)

        class Response:
            def json(self, body, status=200):
                return status, body
            def close_reopen(self, *_args):
                return None

        status, body = self.server.Handler.update(
            Response(),
            "browser",
            {"op": "set", "id": "task-1", "projectSlug": "other"},
        )
        self.assertEqual((status, body["error"]), (
            400,
            "memory_canary_requires_project_factory",
        ))

    def test_priorities_exposes_project_and_context_controls(self):
        html = (ROOT / "bin" / "todos.html").read_text(encoding="utf-8")
        for marker in (
            "projectSlug",
            "projectSlugs",
            "contextQuestion",
            "memoryCanary",
            "Use Memory Gate B canary for this task",
            "Project",
            "Context question",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
