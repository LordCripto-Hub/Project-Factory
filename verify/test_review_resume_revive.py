from __future__ import annotations

import importlib.machinery
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    import sys
    sys.path.insert(0, str(ROOT / "bin"))
    return importlib.machinery.SourceFileLoader(name, str(ROOT / "bin" / path)).load_module()


class ReviewResumeAndReviveTests(unittest.TestCase):
    def test_boss_approval_resumes_review_task_to_working(self):
        publisher = load("review_resume_publisher", "project_publisher.py")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); profiles = root / "profiles"; profiles.mkdir()
            workspace = root / "workspace"; workspace.mkdir()
            (profiles / "project-factory.json").write_text(json.dumps({
                "schemaVersion": 1, "revision": 1, "slug": "project-factory",
                "repository": "https://github.com/example/project-factory.git",
                "workingDirectory": str(workspace), "allowedBranches": ["main"],
            }), encoding="utf-8")
            calls = []
            def api(path, method="GET", body=None, **_kwargs):
                calls.append((path, method, body))
                if path == "/todo/board":
                    return {"tasks": {"task-1": {"projectSlug": "project-factory", "state": "review", "updated": 123.0, "proofs": [{"kind": "text"}]}}}
                return {"ok": True}
            with patch.dict(os.environ, {"PROJECT_PROFILES_DIR": str(profiles), "PUBLISH_APPROVALS_DIR": str(root / "approvals"), "AGENT_ID": "node-1/main:Boss", "QUEUE_SECRET": "test"}, clear=False), patch.object(publisher, "http_json", side_effect=api), patch.object(publisher, "load_roster", return_value=[{"agent_id": "node-1/main:Boss", "is_master": True, "state": "alive", "retired": False}]):
                record = publisher.approve_runtime("task-1", "project-factory", "a" * 40, "main", 900)
            self.assertEqual(record["status"], "pending")
            self.assertIn(("/todo/status", "POST", {"task_id": "task-1", "state": "working", "verified": False, "by": "node-1/main:Boss", "expected_updated": 123.0}), calls)

    def test_failed_review_resume_removes_pending_approval(self):
        publisher = load("review_resume_rollback", "project_publisher.py")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); profiles = root / "profiles"; profiles.mkdir()
            workspace = root / "workspace"; workspace.mkdir()
            (profiles / "project-factory.json").write_text(json.dumps({
                "schemaVersion": 1, "revision": 1, "slug": "project-factory",
                "repository": "https://github.com/example/project-factory.git",
                "workingDirectory": str(workspace), "allowedBranches": ["main"],
            }), encoding="utf-8")
            def api(path, method="GET", **_kwargs):
                if path == "/todo/board":
                    return {"tasks": {"task-1": {"projectSlug": "project-factory", "state": "review", "updated": 123.0, "proofs": [{"kind": "text"}]}}}
                raise RuntimeError("status persistence unavailable")
            with patch.dict(os.environ, {"PROJECT_PROFILES_DIR": str(profiles), "PUBLISH_APPROVALS_DIR": str(root / "approvals"), "AGENT_ID": "node-1/main:Boss", "QUEUE_SECRET": "test"}, clear=False), patch.object(publisher, "http_json", side_effect=api), patch.object(publisher, "load_roster", return_value=[{"agent_id": "node-1/main:Boss", "is_master": True, "state": "alive", "retired": False}]):
                with self.assertRaisesRegex(publisher.PublisherError, "approval_resume_failed"):
                    publisher.approve_runtime("task-1", "project-factory", "a" * 40, "main", 900)
            self.assertFalse(list((root / "approvals").glob("*.json")))

    def test_revive_reuses_owner_configuration_for_live_task(self):
        mp = load("revive_mp", "mp")
        aid = "node-1/main:worker"
        session_id = "session-owner-1234"
        record = {"agent_id": aid, "state": "dead", "retired": True, "lifecycle": "owner", "owner_task_id": "task-1", "backend": "codex", "cwd": "/tmp/worker", "boss_id": "node-1/main:Boss", "model": "gpt-5.6-luna", "session_id": session_id, "session_backend": "codex", "session_profile": "", "session_cwd": "/tmp/worker", "resume_state": "available", "stop_intent": "deliberate"}
        current = {"record": record}
        alive = {"value": False}
        sent = []
        mp.load_roster = lambda: [current["record"]]
        mp.update_roster = lambda row: current.update(record=dict(row))
        mp.window_exists = lambda _target: alive["value"]
        mp.http_json = lambda *_args, **_kwargs: {"tasks": {"task-1": {"state": "working", "assignee": aid}}, "deletedTasks": {}}
        mp.validate_resume_evidence = lambda *_args, **_kwargs: "/private/session.jsonl"
        def spawn(ns, resume_session=""):
            sent.append((ns, resume_session))
            current["record"] = {**current["record"], "state": "alive", "retired": False, "stop_intent": "", "session_id": resume_session}
            alive["value"] = True
        mp.spawn = spawn
        mp.revive(type("Args", (), {"agent_id": aid})())
        self.assertEqual(sent[0][0].owner_task, "task-1")
        self.assertEqual(sent[0][0].backend, "codex")
        self.assertEqual(sent[0][1], session_id)

    def test_revive_refuses_active_agent_and_closed_owner_task(self):
        mp = load("revive_mp_guards", "mp")
        aid = "node-1/main:worker"
        active = {"agent_id": aid, "state": "alive", "retired": False}
        mp.load_roster = lambda: [active]
        mp.window_exists = lambda _target: True
        with self.assertRaisesRegex(SystemExit, "agent_already_alive"):
            mp.revive(type("Args", (), {"agent_id": aid})())

        closed = {"agent_id": aid, "state": "dead", "retired": True, "lifecycle": "owner", "owner_task_id": "task-1"}
        mp.load_roster = lambda: [closed]
        mp.window_exists = lambda _target: False
        mp.http_json = lambda *_args, **_kwargs: {"tasks": {"task-1": {"state": "done", "assignee": aid}}, "deletedTasks": {}}
        with self.assertRaisesRegex(SystemExit, "owner_task_closed"):
            mp.revive(type("Args", (), {"agent_id": aid})())

    def test_revive_rehydrates_stale_alive_record_without_tmux_window(self):
        mp = load("revive_mp_stale_alive", "mp")
        aid = "node-1/main:Boss"
        record = {
            "agent_id": aid,
            "state": "alive",
            "retired": False,
            "backend": "codex",
            "cwd": "/tmp/boss",
            "is_master": True,
            "model": "gpt-5.6-sol",
            "session_id": "session-boss-1234",
            "session_backend": "codex",
            "session_profile": "",
            "session_cwd": "/tmp/boss",
            "resume_state": "available",
        }
        current = {"record": record}
        alive = {"value": False}
        sent = []
        mp.load_roster = lambda: [current["record"]]
        mp.update_roster = lambda row: current.update(record=dict(row))
        mp.window_exists = lambda _target: alive["value"]
        mp.validate_resume_evidence = lambda *_args, **_kwargs: "/private/session.jsonl"
        def spawn(ns, resume_session=""):
            sent.append((ns, resume_session))
            current["record"] = {**current["record"], "state": "alive", "retired": False, "session_id": resume_session}
            alive["value"] = True
        mp.spawn = spawn
        mp.revive(type("Args", (), {"agent_id": aid})())
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][0].agent_id, aid)
        self.assertEqual(sent[0][0].backend, "codex")
        self.assertTrue(sent[0][0].master)
        self.assertEqual(sent[0][0].model, "gpt-5.6-sol")
        self.assertEqual(sent[0][1], "session-boss-1234")

    def test_git_failure_detail_redacts_remote_and_secret_shapes(self):
        publisher = load("publisher_failure_detail", "project_publisher.py")
        detail = publisher.safe_failure_detail("fatal: https://user:password=secret@github.com/repo.git token=abc")
        self.assertNotIn("github.com", detail)
        self.assertNotIn("secret", detail)
        self.assertIn("<remote>", detail)


if __name__ == "__main__":
    unittest.main(verbosity=2)
