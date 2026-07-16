#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import copy
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

    def lifecycle_record(self, **overrides):
        record = {
            "agent_id": "node-1/main:Boss",
            "host": "node-1",
            "session": "main",
            "tab": "Boss",
            "backend": "codex",
            "model": "gpt-test",
            "provider_profile": "codex-primary",
            "cwd": str(self.cwd),
            "boss_id": "",
            "is_master": True,
            "lifecycle": "unclassified",
            "owner_task_id": "",
            "retired": True,
            "retired_reason": "operator-request",
            "state": "dead",
            "stop_intent": "deliberate",
            "recovery_state": "stopped",
            "session_id": "019f0000-0000-7000-8000-000000000222",
            "session_backend": "codex",
            "session_profile": "codex-primary",
            "session_cwd": os.path.realpath(self.cwd),
            "resume_state": "available",
        }
        record.update(overrides)
        return record

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

    def test_kill_persists_deliberate_stop_before_tmux_termination(self):
        record = self.lifecycle_record(retired=False, state="alive", stop_intent="")
        events = []

        def persist(row):
            events.append(("persist", copy.deepcopy(row)))

        def save(rows):
            events.append(("save", copy.deepcopy(rows)))

        def tmux(argv, **_kwargs):
            events.append(("tmux", list(argv)))
            return Result()

        with mock.patch.object(self.mp, "load_roster", return_value=[record]), \
             mock.patch.object(self.mp, "update_roster", side_effect=persist), \
             mock.patch.object(self.mp, "save_roster", side_effect=save), \
             mock.patch.object(self.mp, "run_tmux", side_effect=tmux), \
             mock.patch.object(self.mp, "atomic_json"), \
             mock.patch.object(self.mp, "window_exists", return_value=False), \
             mock.patch.object(self.mp, "http_json", return_value={}):
            self.mp.kill(
                argparse.Namespace(
                    agent_id=record["agent_id"],
                    reason="operator-request",
                )
            )

        self.assertEqual(events[0][0], "persist")
        first = events[0][1]
        self.assertTrue(first["retired"])
        self.assertEqual(first["state"], "stopping")
        self.assertEqual(first["stop_intent"], "deliberate")
        first_tmux = next(
            index for index, event in enumerate(events) if event[0] == "tmux"
        )
        self.assertGreater(first_tmux, 0)
        final = [event[1] for event in events if event[0] == "persist"][-1]
        self.assertEqual(final["state"], "dead")
        self.assertEqual(final["recovery_state"], "stopped")
        self.assertEqual(final["session_id"], record["session_id"])

    def test_revive_requires_session_and_matching_provider_identity(self):
        missing = self.lifecycle_record(session_id="", resume_state="unavailable")
        with mock.patch.object(self.mp, "load_roster", return_value=[missing]), \
             mock.patch.object(self.mp, "window_exists", return_value=False), \
             mock.patch.object(self.mp, "main"):
            with self.assertRaisesRegex(SystemExit, "session_missing"):
                self.mp.revive(argparse.Namespace(agent_id=missing["agent_id"]))

        mismatch = self.lifecycle_record(session_profile="codex-secondary")
        with mock.patch.dict(
            os.environ,
            {
                "PROVIDER_BINDINGS_PATH": str(self.bindings),
                "PROVIDER_PROFILES_PATH": str(self.profiles),
                "PROVIDER_HOMES_DIR": str(self.homes),
            },
            clear=False,
        ), mock.patch.object(self.mp, "load_roster", return_value=[mismatch]), \
             mock.patch.object(self.mp, "window_exists", return_value=False), \
             mock.patch.object(self.mp, "main"):
            with self.assertRaisesRegex(SystemExit, "session_identity_mismatch"):
                self.mp.revive(argparse.Namespace(agent_id=mismatch["agent_id"]))

    def test_valid_revive_passes_same_session_to_spawn_and_clears_stop(self):
        current = {"record": self.lifecycle_record()}
        spawned = []
        window = {"alive": False}

        def load():
            return [copy.deepcopy(current["record"])]

        def persist(row):
            current["record"] = copy.deepcopy(row)

        def spawn(ns, resume_session=""):
            spawned.append((ns, resume_session))
            current["record"].update(
                state="alive",
                retired=False,
                stop_intent="",
                recovery_state="healthy",
                session_id=resume_session,
            )
            window["alive"] = True

        with mock.patch.dict(
            os.environ,
            {
                "PROVIDER_BINDINGS_PATH": str(self.bindings),
                "PROVIDER_PROFILES_PATH": str(self.profiles),
                "PROVIDER_HOMES_DIR": str(self.homes),
            },
            clear=False,
        ), mock.patch.object(self.mp, "load_roster", side_effect=load), \
             mock.patch.object(self.mp, "update_roster", side_effect=persist), \
             mock.patch.object(self.mp, "window_exists", side_effect=lambda *_: window["alive"]), \
             mock.patch.object(self.mp, "spawn", side_effect=spawn, create=True), \
             mock.patch.object(
                 self.mp,
                 "validate_resume_evidence",
                 return_value="/private/session.jsonl",
                 create=True,
             ), \
             mock.patch.object(self.mp, "main") as old_main:
            self.mp.revive(
                argparse.Namespace(agent_id=current["record"]["agent_id"])
            )

        self.assertEqual(len(spawned), 1)
        self.assertEqual(
            spawned[0][1],
            "019f0000-0000-7000-8000-000000000222",
        )
        self.assertEqual(spawned[0][0].model, "gpt-test")
        self.assertEqual(current["record"]["stop_intent"], "")
        self.assertEqual(current["record"]["session_id"], spawned[0][1])
        old_main.assert_not_called()

    def test_failed_exact_revive_restores_deliberate_tombstone(self):
        original = self.lifecycle_record()
        persisted = []

        with mock.patch.dict(
            os.environ,
            {
                "PROVIDER_BINDINGS_PATH": str(self.bindings),
                "PROVIDER_PROFILES_PATH": str(self.profiles),
                "PROVIDER_HOMES_DIR": str(self.homes),
            },
            clear=False,
        ), mock.patch.object(self.mp, "load_roster", return_value=[copy.deepcopy(original)]), \
             mock.patch.object(self.mp, "update_roster", side_effect=lambda row: persisted.append(copy.deepcopy(row))), \
             mock.patch.object(self.mp, "window_exists", return_value=False), \
             mock.patch.object(
                 self.mp,
                 "validate_resume_evidence",
                 return_value="/private/session.jsonl",
                 create=True,
             ), \
             mock.patch.object(
                 self.mp,
                 "spawn",
                 side_effect=RuntimeError("provider failed"),
                 create=True,
             ), \
             mock.patch.object(self.mp, "main"):
            with self.assertRaisesRegex(RuntimeError, "provider failed"):
                self.mp.revive(
                    argparse.Namespace(agent_id=original["agent_id"])
                )

        self.assertGreaterEqual(len(persisted), 2)
        self.assertEqual(persisted[-1], original)

    def run_reconcile(
        self,
        record,
        *,
        now=1000.0,
        revive_error=None,
    ):
        self.assertTrue(hasattr(self.mp, "reconcile"), "reconcile is missing")
        current = {"record": copy.deepcopy(record)}
        events = []

        def load():
            return [copy.deepcopy(current["record"])]

        def persist(row):
            current["record"] = copy.deepcopy(row)
            events.append(("persist", copy.deepcopy(row)))

        def revive(ns):
            events.append(("revive", ns.agent_id))
            if revive_error:
                raise revive_error

        def spawn(ns, resume_session=""):
            events.append(("bootstrap_retry", ns.agent_id, resume_session))

        with mock.patch.object(self.mp, "load_roster", side_effect=load), \
             mock.patch.object(self.mp, "update_roster", side_effect=persist), \
             mock.patch.object(self.mp, "load_json", return_value={}), \
             mock.patch.object(self.mp, "window_exists", return_value=False), \
             mock.patch.object(self.mp, "revive", side_effect=revive), \
             mock.patch.object(self.mp, "spawn", side_effect=spawn), \
             mock.patch.object(self.mp.time, "time", return_value=now):
            self.mp.reconcile(argparse.Namespace(agent_id=""))
        return current["record"], events

    def test_reconcile_skips_deliberate_stop(self):
        record = self.lifecycle_record(
            retired=True,
            stop_intent="deliberate",
            recovery_state="stopped",
        )
        current, events = self.run_reconcile(record)
        self.assertEqual(events, [])
        self.assertEqual(current, record)

    def test_reconcile_uses_exact_revive_and_never_fresh_spawn(self):
        record = self.lifecycle_record(
            retired=False,
            stop_intent="",
            state="alive",
            recovery_state="healthy",
            recovery_attempts=0,
        )
        _current, events = self.run_reconcile(record)
        self.assertIn(("revive", record["agent_id"]), events)
        self.assertNotIn(
            "bootstrap_retry",
            [event[0] for event in events],
        )

    def test_reconcile_honors_cooldown_and_blocks_after_three_failures(self):
        cooldown = self.lifecycle_record(
            retired=False,
            stop_intent="",
            state="dead",
            recovery_state="cooldown",
            recovery_attempts=1,
            next_recovery_at=1010.0,
        )
        unchanged, cooldown_events = self.run_reconcile(cooldown, now=1000.0)
        self.assertEqual(cooldown_events, [])
        self.assertEqual(unchanged, cooldown)

        exhausted = self.lifecycle_record(
            retired=False,
            stop_intent="",
            state="dead",
            recovery_state="cooldown",
            recovery_attempts=3,
            next_recovery_at=0,
        )
        blocked, blocked_events = self.run_reconcile(exhausted)
        self.assertNotIn("revive", [event[0] for event in blocked_events])
        self.assertEqual(blocked["recovery_state"], "blocked")
        self.assertEqual(
            blocked["last_recovery_error"],
            "recovery_attempts_exhausted",
        )

    def test_third_exact_recovery_failure_becomes_blocked_without_fresh_spawn(self):
        record = self.lifecycle_record(
            retired=False,
            stop_intent="",
            state="dead",
            recovery_state="healthy",
            recovery_attempts=2,
            next_recovery_at=0,
        )
        blocked, events = self.run_reconcile(
            record,
            revive_error=RuntimeError("provider failed"),
        )
        self.assertEqual(blocked["recovery_attempts"], 3)
        self.assertEqual(blocked["recovery_state"], "blocked")
        self.assertEqual(blocked["last_recovery_error"], "resume_process_failed")
        self.assertNotIn("bootstrap_retry", [event[0] for event in events])

    def test_never_started_agent_has_at_most_three_bootstrap_retries(self):
        starting = self.lifecycle_record(
            retired=False,
            stop_intent="",
            state="starting",
            session_id="",
            resume_state="pending",
            recovery_attempts=2,
            created=800.0,
            next_recovery_at=0,
        )
        retried, events = self.run_reconcile(starting, now=1000.0)
        self.assertIn(
            ("bootstrap_retry", starting["agent_id"], ""),
            events,
        )
        self.assertEqual(retried["recovery_attempts"], 3)

        exhausted = {
            **starting,
            "recovery_attempts": 3,
        }
        blocked, events = self.run_reconcile(exhausted, now=1000.0)
        self.assertNotIn("bootstrap_retry", [event[0] for event in events])
        self.assertEqual(blocked["recovery_state"], "blocked")

    def test_fresh_handoff_requires_authorization_and_starts_without_resume(self):
        self.assertTrue(
            hasattr(self.mp, "fresh_handoff"),
            "fresh_handoff is missing",
        )
        record = self.lifecycle_record(
            retired=True,
            stop_intent="deliberate",
            state="dead",
            lifecycle="owner",
            owner_task_id="task-1234",
        )
        handoff = {
            "agent": {
                "agent_id": record["agent_id"],
                "summary": "continue the same task",
            },
            "terminalTail": "verified progress",
        }
        spawned = []

        def spawn(ns, resume_session="", initial_message=""):
            spawned.append((ns, resume_session, initial_message))

        namespace = argparse.Namespace(
            agent_id=record["agent_id"],
            transaction="tx-one",
            handoff=str(self.root / "handoff.json"),
        )
        with mock.patch.object(
            self.mp,
            "validate_fresh_handoff",
            return_value={
                "record": record,
                "handoff": handoff,
                "state": {
                    "targetBackend": "claude",
                    "targetModel": "claude-test",
                },
            },
            create=True,
        ), mock.patch.object(self.mp, "spawn", side_effect=spawn):
            self.mp.fresh_handoff(namespace)

        self.assertEqual(len(spawned), 1)
        self.assertEqual(spawned[0][1], "")
        self.assertIn("continue the same task", spawned[0][2])
        self.assertIn("verified progress", spawned[0][2])
        self.assertEqual(spawned[0][0].backend, "claude")
        self.assertEqual(spawned[0][0].model, "claude-test")
        self.assertEqual(spawned[0][0].owner_task, "task-1234")

        with mock.patch.object(
            self.mp,
            "validate_fresh_handoff",
            side_effect=SessionError("fresh_handoff_not_authorized"),
            create=True,
        ), mock.patch.object(self.mp, "spawn") as forbidden_spawn:
            with self.assertRaisesRegex(
                SystemExit,
                "fresh_handoff_not_authorized",
            ):
                self.mp.fresh_handoff(namespace)
        forbidden_spawn.assert_not_called()


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(
        ExactSessionSpawnContract
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("PASS exact session spawn capture contract")
    raise SystemExit(0 if result.wasSuccessful() else 1)
