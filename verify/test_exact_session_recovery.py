#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from agent_session import SessionError
import mpcommon


ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))


def load_mp():
    loader = importlib.machinery.SourceFileLoader(
        "mp_exact_session_under_test",
        str(BIN / "mp"),
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class Result:
    returncode = 0
    stdout = ""
    stderr = ""


class ExactSessionSpawnContract(unittest.TestCase):
    def setUp(self):
        self.mp = load_mp()
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.cwd = self.root / "boss"
        self.cwd.mkdir()
        self.bindings = self.root / "provider-bindings.json"
        self.profiles = self.root / "provider-profiles.json"
        self.homes = self.root / "provider-homes"
        self.bindings.write_text(
            json.dumps(
                {
                    "globalProfile": "codex-primary",
                    "agentProfiles": {},
                }
            ),
            encoding="utf-8",
        )
        self.profiles.write_text(
            json.dumps(
                {
                    "codex-primary": {
                        "defaultModel": "gpt-test",
                        "roleModels": {"boss": "gpt-test"},
                    }
                }
            ),
            encoding="utf-8",
        )
        self.records = []
        self.statuses = []
        self.events = []
        self.exported = {}

    def tearDown(self):
        self.temporary.cleanup()

    def namespace(self):
        return argparse.Namespace(
            agent_id="node-1/main:Boss",
            backend="codex",
            cwd=str(self.cwd),
            boss=None,
            master=True,
            model="gpt-test",
            owner_task=None,
            temporary=False,
        )

    @contextlib.contextmanager
    def fake_lock(self, *_args, **_kwargs):
        self.events.append(("lock-enter",))
        try:
            yield "capture.lock"
        finally:
            self.events.append(("lock-exit",))

    def fake_tmux(self, argv, **_kwargs):
        self.events.append(("tmux", list(argv)))
        return Result()

    def capture_environment(self, values):
        self.exported.update(values)
        return "true"

    def run_spawn(self, discover):
        discovery_error = discover if isinstance(discover, BaseException) else None
        discovery_value = discover if isinstance(discover, dict) else None
        environment = {
            "PROVIDER_BINDINGS_PATH": str(self.bindings),
            "PROVIDER_PROFILES_PATH": str(self.profiles),
            "PROVIDER_HOMES_DIR": str(self.homes),
            "MYPEOPLE_SESSION_CAPTURE_DIR": str(self.root / "capture-locks"),
        }
        with mock.patch.dict(os.environ, environment, clear=False), \
             mock.patch.object(self.mp, "window_exists", return_value=False), \
             mock.patch.object(self.mp, "run_tmux", side_effect=self.fake_tmux), \
             mock.patch.object(self.mp, "load_roster", return_value=[]), \
             mock.patch.object(self.mp, "update_roster", side_effect=lambda row: self.records.append(dict(row))), \
             mock.patch.object(self.mp, "write_status", side_effect=lambda *args, **kwargs: self.statuses.append((args, kwargs))), \
             mock.patch.object(self.mp, "queue_register"), \
             mock.patch.object(self.mp, "recorder"), \
             mock.patch.object(self.mp, "wait_for_composer", return_value=True), \
             mock.patch.object(self.mp, "tmux_send_message"), \
             mock.patch.object(self.mp, "ensure_codex_doctrine"), \
             mock.patch.object(self.mp, "shell_export", side_effect=self.capture_environment), \
             mock.patch.object(self.mp, "capture_lock", side_effect=self.fake_lock, create=True), \
             mock.patch.object(self.mp, "snapshot_codex_sessions", return_value={"old"}, create=True), \
             mock.patch.object(
                 self.mp,
                 "discover_codex_session",
                 side_effect=discovery_error,
                 return_value=discovery_value,
                 create=True,
             ):
            self.mp.spawn(self.namespace())

    def test_fresh_codex_spawn_locks_before_tmux_and_persists_session(self):
        session_id = "019f0000-0000-7000-8000-000000000111"
        self.run_spawn(
            {
                "session_id": session_id,
                "cwd": os.path.realpath(self.cwd),
                "path": str(self.root / "rollout.jsonl"),
            }
        )

        record = self.records[-1]
        self.assertEqual(record.get("session_id"), session_id)
        self.assertEqual(record.get("session_backend"), "codex")
        self.assertEqual(record.get("session_profile"), "codex-primary")
        self.assertEqual(record.get("session_cwd"), os.path.realpath(self.cwd))
        self.assertEqual(record.get("resume_state"), "available")
        self.assertEqual(record.get("last_recovery_error"), "")
        self.assertEqual(
            self.exported.get("MYPEOPLE_PROVIDER_PROFILE"),
            "codex-primary",
        )
        lock_enter = self.events.index(("lock-enter",))
        first_tmux = next(
            index for index, event in enumerate(self.events) if event[0] == "tmux"
        )
        lock_exit = self.events.index(("lock-exit",))
        self.assertLess(lock_enter, first_tmux)
        self.assertLess(first_tmux, lock_exit)

    def test_capture_timeout_keeps_window_without_guessing_session(self):
        self.run_spawn(SessionError("session_capture_timeout"))

        record = self.records[-1]
        self.assertEqual(record.get("session_id"), "")
        self.assertEqual(record.get("resume_state"), "unavailable")
        self.assertEqual(
            record.get("last_recovery_error"),
            "session_capture_timeout",
        )
        self.assertTrue(any(event[0] == "tmux" for event in self.events))
        self.assertEqual(self.events[-1], ("lock-exit",))

    def test_roster_identity_update_changes_only_the_selected_agent(self):
        roster_path = self.root / "roster.json"
        roster_path.write_text(
            json.dumps(
                [
                    {"agent_id": "node-1/main:Boss", "session_id": ""},
                    {"agent_id": "node-1/main:Other", "session_id": "keep-me"},
                ]
            ),
            encoding="utf-8",
        )
        self.assertTrue(
            hasattr(mpcommon, "record_session_identity"),
            "record_session_identity is missing",
        )
        with mock.patch.object(
            mpcommon,
            "roster_path",
            return_value=str(roster_path),
        ):
            updated = mpcommon.record_session_identity(
                "node-1/main:Boss",
                {
                    "session_id": "session-1234",
                    "resume_state": "available",
                },
            )
        rows = json.loads(roster_path.read_text(encoding="utf-8"))
        self.assertEqual(updated["session_id"], "session-1234")
        self.assertEqual(rows[0]["session_id"], "session-1234")
        self.assertEqual(rows[1]["session_id"], "keep-me")


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(
        ExactSessionSpawnContract
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("PASS exact session spawn capture contract")
    raise SystemExit(0 if result.wasSuccessful() else 1)
