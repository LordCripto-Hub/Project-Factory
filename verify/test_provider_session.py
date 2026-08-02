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

    def test_handoff_redacts_common_assignments_jwt_pem_and_credential_paths(self):
        tail = "\n".join(
            (
                "QUEUE_SECRET=queue-example-value",
                "password: password-example-value",
                "access_token=access-example-value",
                "Cookie: session=cookie-example-value",
                "jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.signature",
                "-----BEGIN PRIVATE KEY-----",
                "private-key-material",
                "-----END PRIVATE KEY-----",
                "/home/mp/.codex/auth.json",
                "MYPEOPLE_MEMORY_TOKEN=memory-example-value",
                "/home/mp/mypeople/run/provider-homes/codex/profile/auth.json",
            )
        )
        rendered = json.dumps(module.build_handoff({}, tail))
        for secret in (
            "queue-example-value",
            "password-example-value",
            "access-example-value",
            "cookie-example-value",
            "eyJhbGciOiJIUzI1NiJ9",
            "private-key-material",
            "/home/mp/.codex/auth.json",
            "memory-example-value",
            "/home/mp/mypeople/run/provider-homes/codex/profile/auth.json",
        ):
            self.assertNotIn(secret, rendered)

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

    def test_prepare_writes_one_private_handoff_per_selected_agent(self):
        agent_id = "node-1/main:Engineer-1"
        roster = [
            {
                "agent_id": agent_id,
                "backend": "codex",
                "model": "gpt-test",
                "provider_profile": "codex-primary",
                "cwd": "/workspace/project",
                "state": "alive",
                "retired": False,
                "lifecycle": "owner",
                "owner_task_id": "task-1234",
                "taskspec_sha256": "a" * 64,
                "role_contract_sha256": "b" * 64,
            }
        ]
        transactions = self.root / "transactions"
        bindings = self.root / "provider-bindings.json"
        module.atomic_json(
            str(bindings),
            {"globalProfile": "codex-primary", "agentProfiles": {}},
        )
        args = module.argparse.Namespace(
            transaction="tx-prepare",
            agent=agent_id,
            backend="",
            model="",
            profile="codex-secondary",
        )
        with mock.patch.object(module, "TRANSACTIONS_ROOT", str(transactions)), \
             mock.patch.object(module, "LOCK_PATH", self.lock), \
             mock.patch.object(module, "BINDINGS_PATH", str(bindings)), \
             mock.patch.object(module, "load_roster", return_value=roster), \
             mock.patch.object(module, "_capture_tail", return_value="progress"):
            module.command_prepare(args)
        handoffs = list((transactions / "tx-prepare" / "handoffs").glob("*.json"))
        self.assertEqual(len(handoffs), 1)
        payload = json.loads(handoffs[0].read_text(encoding="utf-8"))
        self.assertEqual(payload["snapshot"]["agent_id"], agent_id)
        self.assertEqual(payload["snapshot"]["cwd"], "/workspace/project")
        self.assertEqual(stat.S_IMODE(handoffs[0].stat().st_mode), 0o600)
        state = module.load_json(
            str(transactions / "tx-prepare" / "state.json"),
            {},
        )
        self.assertEqual(state["targetProfile"], "codex-secondary")
        self.assertEqual(state["targetProfiles"], {agent_id: "codex-secondary"})

    def test_global_profile_switch_preserves_agent_overrides_and_excludes_other_providers(self):
        boss = {"agent_id": "node-1/main:Boss", "backend": "codex", "state": "alive", "retired": False}
        nightwatch = {"agent_id": "node-1/nightwatch:Nightwatch", "backend": "codex", "state": "alive", "retired": False}
        claude = {"agent_id": "node-1/main:Claude", "backend": "claude", "state": "alive", "retired": False}
        transactions = self.root / "transactions"
        bindings = self.root / "provider-bindings.json"
        module.atomic_json(str(bindings), {"globalProfile": "codex-old", "agentProfiles": {boss["agent_id"]: "codex-primary"}})
        args = module.argparse.Namespace(transaction="tx-global", agent="", backend="", model="", profile="codex-current")
        with mock.patch.object(module, "TRANSACTIONS_ROOT", str(transactions)), \
             mock.patch.object(module, "LOCK_PATH", self.lock), \
             mock.patch.object(module, "BINDINGS_PATH", str(bindings)), \
             mock.patch.object(module, "load_roster", return_value=[boss, nightwatch, claude]), \
             mock.patch.object(module, "_capture_tail", return_value=""):
            module.command_prepare(args)
        state = module.load_json(str(transactions / "tx-global" / "state.json"), {})
        active = module.load_json(str(transactions / "tx-global" / "active-roster.json"), [])
        self.assertEqual(state["targetProfiles"], {boss["agent_id"]: "codex-primary", nightwatch["agent_id"]: "codex-current"})
        self.assertEqual([row["agent_id"] for row in active], [boss["agent_id"], nightwatch["agent_id"]])

    def test_forward_revive_uses_transaction_authorized_fresh_handoff(self):
        transaction_dir = self.root / "transactions" / "tx-forward"
        transaction_dir.mkdir(parents=True)
        agent_id = "node-1/main:Engineer-1"
        roster = [{"agent_id": agent_id, "is_master": False}]
        module.atomic_json(
            str(transaction_dir / "state.json"),
            {
                "transaction": "tx-forward",
                "selectedAgent": agent_id,
                "phase": "stopped",
            },
        )
        module.atomic_json(
            str(transaction_dir / "active-roster.json"),
            roster,
        )
        handoff_dir = transaction_dir / "handoffs"
        handoff_dir.mkdir(mode=0o700)
        handoff = handoff_dir / "agent.json"
        module.atomic_json(str(handoff), {"agent": {"agent_id": agent_id}})
        calls = []
        with mock.patch.object(module, "TRANSACTIONS_ROOT", str(self.root / "transactions")), \
             mock.patch.object(module, "run_mp", side_effect=lambda argv: calls.append(argv)), \
             mock.patch.object(module, "handoff_path_for_agent", return_value=str(handoff)):
            module.command_revive(
                module.argparse.Namespace(transaction="tx-forward")
            )
        self.assertEqual(
            calls,
            [[
                "fresh-handoff",
                agent_id,
                "--transaction",
                "tx-forward",
                "--handoff",
                str(handoff),
            ]],
        )
        state = module.load_json(str(transaction_dir / "state.json"), {})
        self.assertEqual(state["phase"], "revived")

    def test_verify_roles_requires_live_matching_roster(self):
        expected = [
            {
                "agent_id": "node-1/main:Boss",
                "is_master": True,
                "backend": "codex",
                "cwd": "/workspace/boss",
            }
        ]
        actual = [{
            **expected[0],
            "state": "alive",
            "session_id": "session-1234",
            "session_backend": "codex",
            "session_profile": "",
            "session_cwd": "/workspace/boss",
            "resume_state": "available",
        }]
        with mock.patch.object(module, "load_roster", return_value=actual), \
             mock.patch.object(module, "window_exists", return_value=True):
            module.verify_roles(expected)
        with mock.patch.object(module, "load_roster", return_value=actual), \
             mock.patch.object(module, "window_exists", return_value=False):
            with self.assertRaises(RuntimeError):
                module.verify_roles(expected)

    def test_verify_roles_checks_target_backend_model_and_bound_profile(self):
        agent_id = "node-1/main:Boss"
        expected = [
            {
                "agent_id": agent_id,
                "is_master": True,
                "backend": "codex",
                "model": "gpt-old",
                "provider_profile": "codex-primary",
                "session_id": "session-old-1234",
            }
        ]
        current = [
            {
                **expected[0],
                "state": "alive",
                "model": "gpt-new",
                "provider_profile": "codex-secondary",
                "cwd": "/workspace/boss",
                "session_id": "session-new-1234",
                "session_backend": "codex",
                "session_profile": "codex-secondary",
                "session_cwd": "/workspace/boss",
                "resume_state": "available",
            }
        ]
        bindings = self.root / "provider-bindings.json"
        module.atomic_json(
            str(bindings),
            {
                "globalProfile": "codex-primary",
                "agentProfiles": {agent_id: "codex-secondary"},
            },
        )
        with mock.patch.object(module, "BINDINGS_PATH", str(bindings)), \
             mock.patch.object(module, "load_roster", return_value=current), \
             mock.patch.object(module, "window_exists", return_value=True):
            module.verify_roles(
                expected,
                target_backend="codex",
                target_model="gpt-new",
            )

        reused = [{**current[0], "session_id": "session-old-1234"}]
        with mock.patch.object(module, "BINDINGS_PATH", str(bindings)), \
             mock.patch.object(module, "load_roster", return_value=reused), \
             mock.patch.object(module, "window_exists", return_value=True):
            with self.assertRaises(RuntimeError):
                module.verify_roles(
                    expected,
                    target_backend="codex",
                    target_model="gpt-new",
                )

        wrong = [{**current[0], "model": "gpt-wrong"}]
        with mock.patch.object(module, "BINDINGS_PATH", str(bindings)), \
             mock.patch.object(module, "load_roster", return_value=wrong), \
             mock.patch.object(module, "window_exists", return_value=True):
            with self.assertRaisesRegex(
                RuntimeError,
                r"node-1/main:Boss:model_mismatch",
            ):
                module.verify_roles(
                    expected,
                    target_backend="codex",
                    target_model="gpt-new",
                )

    def test_verify_roles_rejects_fresh_agent_without_captured_session(self):
        agent_id = "node-1/main:Boss"
        expected = [{
            "agent_id": agent_id,
            "is_master": True,
            "backend": "claude",
            "cwd": "/workspace/boss",
        }]
        unavailable = [{
            **expected[0],
            "state": "alive",
            "session_id": "",
            "session_backend": "claude",
            "session_profile": "",
            "session_cwd": "/workspace/boss",
            "resume_state": "unavailable",
        }]
        bindings = self.root / "provider-bindings.json"
        module.atomic_json(
            str(bindings),
            {},
        )
        with mock.patch.object(module, "BINDINGS_PATH", str(bindings)), \
             mock.patch.object(module, "load_roster", return_value=unavailable), \
             mock.patch.object(module, "window_exists", return_value=True):
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

    def test_global_codex_rollback_preserves_unrelated_claude_runtime(self):
        transaction_dir = self.root / "tx-hybrid"
        codex_old = {"agent_id": "node-1/main:Boss", "backend": "codex", "state": "alive", "model": "old"}
        claude_old = {"agent_id": "node-1/main:Claude", "backend": "claude", "state": "alive", "model": "old-claude"}
        codex_current = {**codex_old, "model": "new"}
        claude_current = {**claude_old, "model": "current-claude", "runtime_note": "preserve"}
        bindings = {"globalProfile": "codex-old", "agentProfiles": {}}
        module.snapshot(str(transaction_dir), [codex_old, claude_old], bindings)
        module.atomic_json(str(transaction_dir / "active-roster.json"), [codex_old])
        module.atomic_json(str(transaction_dir / "state.json"), {"transaction": "tx-hybrid", "selectedAgent": ""})
        bindings_path = str(self.root / "provider-bindings.json")
        module.atomic_json(bindings_path, {"globalProfile": "broken"})
        module.acquire_lock(self.lock, "tx-hybrid")
        with mock.patch.object(module, "BINDINGS_PATH", bindings_path), \
             mock.patch.object(module, "LOCK_PATH", self.lock), \
             mock.patch.object(module, "load_roster", return_value=[codex_current, claude_current]), \
             mock.patch.object(module, "stop_agents") as stop, \
             mock.patch.object(module, "save_roster") as save, \
             mock.patch.object(module, "revive_agents") as revive:
            module.rollback(str(transaction_dir))
        stop.assert_called_once_with([codex_current], "")
        save.assert_called_once_with([codex_old, claude_current])
        revive.assert_called_once_with([codex_old], "")

    def test_corrupt_rollback_snapshot_fails_before_any_mutation(self):
        transaction_dir = self.root / "tx-corrupt"
        ghost = {"agent_id": "node-1/main:Ghost", "backend": "codex", "state": "alive"}
        module.snapshot(str(transaction_dir), [], {"globalProfile": "codex-old"})
        module.atomic_json(str(transaction_dir / "active-roster.json"), [ghost])
        module.atomic_json(str(transaction_dir / "state.json"), {"transaction": "tx-corrupt", "selectedAgent": ""})
        bindings_path = str(self.root / "provider-bindings.json")
        broken = {"globalProfile": "broken"}
        module.atomic_json(bindings_path, broken)
        module.acquire_lock(self.lock, "tx-corrupt")
        with mock.patch.object(module, "BINDINGS_PATH", bindings_path), \
             mock.patch.object(module, "LOCK_PATH", self.lock), \
             mock.patch.object(module, "load_roster", return_value=[ghost]), \
             mock.patch.object(module, "stop_agents") as stop, \
             mock.patch.object(module, "save_roster") as save, \
             mock.patch.object(module, "revive_agents") as revive:
            with self.assertRaisesRegex(RuntimeError, "snapshot is incomplete"):
                module.rollback(str(transaction_dir))
        stop.assert_not_called();save.assert_not_called();revive.assert_not_called()
        self.assertEqual(module.load_json(bindings_path, {}), broken)


if __name__ == "__main__":
    unittest.main(verbosity=2)
