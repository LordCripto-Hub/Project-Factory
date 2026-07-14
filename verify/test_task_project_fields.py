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
    with patch.dict(os.environ, env, clear=False):
        loader.exec_module(module)
    return module


class TaskProjectFieldsContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.server = load_server(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_legacy_task_migrates_without_inventing_project(self):
        task = {"id": "legacy", "text": "Legacy task"}
        self.server.normalize_task(task)
        self.assertEqual(task["projectSlug"], "")
        self.assertEqual(task["contextQuestion"], "")

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

    def test_priorities_exposes_project_and_context_controls(self):
        html = (ROOT / "bin" / "todos.html").read_text(encoding="utf-8")
        for marker in (
            "projectSlug",
            "projectSlugs",
            "contextQuestion",
            "Project",
            "Context question",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
