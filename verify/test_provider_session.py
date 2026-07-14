#!/usr/bin/env python3
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load_runtime(path: str):
    loader = importlib.machinery.SourceFileLoader(
        "mypeople_provider_session_under_test", path
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


module = load_runtime(str(ROOT / "bin" / "provider-session"))


class ProviderSessionContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.lock = str(self.root / "provider-switch.lock")

    def tearDown(self):
        self.temp.cleanup()

    def test_handoff_is_bounded_and_redacts_secrets(self):
        handoff = module.build_handoff(
            {
                "agent_id": "node-1/main:Boss",
                "summary": "working",
                "credential": "must-not-be-copied",
            },
            "Author" + "ization: Bearer " + "secret-example-value\n"
            + "token "
            + "tskey"
            + "-auth-example\n"
            + ("x" * 20000),
            limit=4000,
        )
        rendered = json.dumps(handoff)
        self.assertNotIn("tskey" + "-auth-example", rendered)
        self.assertNotIn("secret-example-value", rendered)
        self.assertNotIn("must-not-be-copied", rendered)
        self.assertLessEqual(len(handoff["terminalTail"]), 4000)

    def test_lock_rejects_concurrent_switches(self):
        module.acquire_lock(self.lock, "tx-one")
        with self.assertRaises(module.SwitchBusy):
            module.acquire_lock(self.lock, "tx-two")

    def test_release_lock_only_removes_owned_lock(self):
        module.acquire_lock(self.lock, "tx-one")
        module.release_lock(self.lock, "tx-two")
        self.assertTrue(Path(self.lock).exists())
        module.release_lock(self.lock, "tx-one")
        self.assertFalse(Path(self.lock).exists())

    def test_active_provider_roster_excludes_retired_and_dead_agents(self):
        roster = [
            {"agent_id": "node-1/main:Boss", "backend": "codex", "state": "alive", "retired": False},
            {"agent_id": "node-1/main:Old", "backend": "codex", "state": "dead", "retired": True},
            {"agent_id": "node-1/main:Dead", "backend": "codex", "state": "dead", "retired": False},
            {"agent_id": "node-1/main:Claude", "backend": "claude", "state": "alive", "retired": False},
            {"agent_id": "node-1/main:Other", "backend": "manual", "state": "alive", "retired": False},
        ]
        self.assertEqual(
            [row["agent_id"] for row in module.active_provider_roster(roster)],
            ["node-1/main:Boss", "node-1/main:Claude"],
        )

    def test_revival_order_is_boss_nightwatch_then_workers(self):
        roster = [
            {"agent_id": "node-1/main:Engineer-1", "lifecycle": "owner"},
            {"agent_id": "node-1/nightwatch:Nightwatch"},
            {"agent_id": "node-1/main:Boss", "is_master": True},
        ]
        self.assertEqual(
            [row["agent_id"] for row in module.revival_order(roster)],
            [
                "node-1/main:Boss",
                "node-1/nightwatch:Nightwatch",
                "node-1/main:Engineer-1",
            ],
        )

    def test_snapshot_is_atomic_private_and_round_trips(self):
        transaction_dir = self.root / "tx"
        roster = [{"agent_id": "node-1/main:Boss", "is_master": True}]
        bindings = {"globalProfile": "codex-primary", "agentProfiles": {}}
        module.snapshot(str(transaction_dir), roster, bindings)
        for name, expected in (("roster.json", roster), ("bindings.json", bindings)):
            path = transaction_dir / name
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), expected)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_stop_and_revive_honor_selected_agent_and_order(self):
        roster = [
            {"agent_id": "node-1/main:Engineer-1"},
            {"agent_id": "node-1/nightwatch:Nightwatch"},
            {"agent_id": "node-1/main:Boss", "is_master": True},
        ]
        calls = []
        with mock.patch.object(module, "run_mp", side_effect=lambda argv: calls.append(argv)):
            module.stop_agents(roster, "node-1/main:Engineer-1")
            module.revive_agents(roster)
        self.assertEqual(
            calls,
            [
                ["kill", "node-1/main:Engineer-1", "--reason", "provider-profile-switch"],
                ["revive", "node-1/main:Boss"],
                ["revive", "node-1/nightwatch:Nightwatch"],
                ["revive", "node-1/main:Engineer-1"],
            ],
        )

    def test_verify_roles_requires_live_matching_roster(self):
        expected = [
            {
                "agent_id": "node-1/main:Boss",
                "is_master": True,
                "backend": "codex",
            }
        ]
        actual = [{**expected[0], "state": "alive"}]
        with mock.patch.object(module, "load_roster", return_value=actual), \
             mock.patch.object(module, "window_exists", return_value=True):
            module.verify_roles(expected)
        with mock.patch.object(module, "load_roster", return_value=actual), \
             mock.patch.object(module, "window_exists", return_value=False):
            with self.assertRaises(RuntimeError):
                module.verify_roles(expected)

    def test_rollback_restores_bindings_and_revival_snapshot(self):
        transaction_dir = self.root / "tx-rollback"
        roster = [{"agent_id": "node-1/main:Boss", "is_master": True}]
        bindings = {"globalProfile": "codex-primary", "agentProfiles": {}}
        module.snapshot(str(transaction_dir), roster, bindings)
        module.atomic_json(
            str(transaction_dir / "state.json"),
            {"transaction": "tx-rollback", "selectedAgent": ""},
        )
        bindings_path = str(self.root / "provider-bindings.json")
        module.atomic_json(bindings_path, {"globalProfile": "broken"})
        module.acquire_lock(self.lock, "tx-rollback")
        with mock.patch.object(module, "BINDINGS_PATH", bindings_path), \
             mock.patch.object(module, "LOCK_PATH", self.lock), \
             mock.patch.object(module, "load_roster", return_value=roster), \
             mock.patch.object(module, "stop_agents") as stop, \
             mock.patch.object(module, "save_roster") as save, \
             mock.patch.object(module, "revive_agents") as revive:
            module.rollback(str(transaction_dir))
        self.assertEqual(module.load_json(bindings_path, {}), bindings)
        stop.assert_called_once_with(roster, "")
        save.assert_called_once_with(roster)
        revive.assert_called_once_with(roster, "")
        self.assertFalse(Path(self.lock).exists())

    def test_rollback_restores_selected_agent_missing_from_current_roster(self):
        transaction_dir = self.root / "tx-missing"
        agent_id = "node-1/main:Engineer-1"
        roster = [{"agent_id": agent_id, "backend": "codex"}]
        bindings = {
            "globalProfile": "codex-primary",
            "agentProfiles": {agent_id: "codex-secondary"},
        }
        module.snapshot(str(transaction_dir), roster, bindings)
        module.atomic_json(
            str(transaction_dir / "state.json"),
            {"transaction": "tx-missing", "selectedAgent": agent_id},
        )
        bindings_path = str(self.root / "provider-bindings.json")
        module.atomic_json(bindings_path, {"globalProfile": "broken"})
        module.acquire_lock(self.lock, "tx-missing")
        with mock.patch.object(module, "BINDINGS_PATH", bindings_path), \
             mock.patch.object(module, "LOCK_PATH", self.lock), \
             mock.patch.object(module, "load_roster", return_value=[]), \
             mock.patch.object(module, "save_roster") as save, \
             mock.patch.object(module, "revive_agents") as revive:
            module.rollback(str(transaction_dir))
        self.assertEqual(module.load_json(bindings_path, {}), bindings)
        save.assert_called_once_with(roster)
        revive.assert_called_once_with(roster, agent_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
