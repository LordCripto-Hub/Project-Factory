#!/usr/bin/env python3
"""Focused contract for a persistent Codex-backed MyPeople Boss."""
from __future__ import annotations

import argparse
import copy
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import shlex
import tempfile
import tomllib
import unittest
from unittest import mock


def load_runtime(path: str):
    loader = importlib.machinery.SourceFileLoader("mypeople_mp_codex_boss_under_test", path)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class Result:
    returncode = 0
    stdout = ""
    stderr = ""


class CodexBossContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mp = load_runtime(os.environ.get("MYPEOPLE_MP_BIN", "/home/mp/mypeople/bin/mp"))
        cls.agent_id = "node-1/main:Boss"
        cls.boss_dir = os.path.realpath(os.path.join(cls.mp.INSTALL_DIR, "run", "boss"))

    def test_codex_launch_is_native_and_autonomous(self):
        words = shlex.split(self.mp.build_launch(
            self.agent_id, self.boss_dir, "", True, "gpt-5.6-sol", "codex"
        ))
        self.assertEqual(words[0], "codex")
        self.assertEqual(words[words.index("--sandbox") + 1], "danger-full-access")
        self.assertEqual(words[words.index("--ask-for-approval") + 1], "never")
        self.assertEqual(words[words.index("-C") + 1], self.boss_dir)
        self.assertEqual(words[words.index("--model") + 1], "gpt-5.6-sol")
        self.assertNotIn("claude", words)
        self.assertNotIn("--plugin-dir", words)
        override = words[words.index("--config") + 1]
        self.assertEqual(
            tomllib.loads(override),
            {"projects": {self.boss_dir: {"trust_level": "trusted"}}},
        )

    def test_spawn_parser_accepts_codex(self):
        ns = self.mp.parser().parse_args([
            "spawn", self.agent_id, "--backend", "codex",
            "--model", "gpt-5.6-sol", "--master",
        ])
        self.assertEqual(ns.backend, "codex")
        self.assertEqual(ns.model, "gpt-5.6-sol")

    def test_spawn_exports_effective_provider_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bindings = root / "provider-bindings.json"
            profiles = root / "provider-profiles.json"
            provider_homes = root / "provider-homes"
            cwd = root / "boss"
            bindings.write_text(
                '{"globalProfile":"codex-primary","agentProfiles":{}}',
                encoding="utf-8",
            )
            profiles.write_text(
                '{"codex-primary":{"defaultModel":"gpt-5.6-luna",'
                '"roleModels":{"boss":"gpt-5.6-sol"}}}',
                encoding="utf-8",
            )
            launch_env = {}
            records = []

            def capture_env(environment):
                launch_env.update(environment)
                return "true"

            with mock.patch.dict(
                os.environ,
                {
                    "PROVIDER_BINDINGS_PATH": str(bindings),
                    "PROVIDER_PROFILES_PATH": str(profiles),
                    "PROVIDER_HOMES_DIR": str(provider_homes),
                },
                clear=False,
            ):
                with mock.patch.object(self.mp, "shell_export", capture_env), \
                     mock.patch.object(self.mp, "window_exists", return_value=False), \
                     mock.patch.object(self.mp, "run_tmux", return_value=Result()), \
                     mock.patch.object(self.mp, "load_roster", return_value=[]), \
                     mock.patch.object(self.mp, "update_roster", side_effect=records.append), \
                     mock.patch.object(self.mp, "queue_register"), \
                     mock.patch.object(self.mp, "recorder"), \
                     mock.patch.object(self.mp, "wait_for_composer", return_value=False), \
                     mock.patch.object(self.mp, "tmux_send_message"), \
                     mock.patch.object(self.mp, "ensure_codex_doctrine"):
                    self.mp.spawn(
                        argparse.Namespace(
                            agent_id=self.agent_id,
                            backend="codex",
                            cwd=str(cwd),
                            boss=None,
                            master=True,
                            model=None,
                            owner_task=None,
                            temporary=False,
                        )
                    )

            expected_home = str(provider_homes / "codex" / "codex-primary")
            self.assertEqual(launch_env["CODEX_HOME"], expected_home)
            self.assertEqual(records[0]["provider_profile"], "codex-primary")
            self.assertEqual(records[0]["model"], "gpt-5.6-sol")
            self.assertTrue(provider_homes.joinpath("codex", "codex-primary").is_dir())

    def test_switch_persists_desired_model_before_exact_revive(self):
        rec = {
            "agent_id": self.agent_id,
            "backend": "codex",
            "model": "gpt-5.6-luna",
            "provider_profile": "codex-primary",
            "session_profile": "codex-primary",
            "session_backend": "codex",
            "session_id": "session-1234",
            "session": "main",
            "tab": "Boss",
            "cwd": self.boss_dir,
            "is_master": True,
            "retired": False,
            "state": "alive",
        }
        events = []
        self.mp.load_roster = lambda: [copy.deepcopy(rec)]
        self.mp.update_roster = lambda row: events.append(("persist", copy.deepcopy(row)))
        self.mp.run_tmux = lambda argv, **kwargs: events.append(("tmux", list(argv))) or Result()
        self.mp.revive = lambda ns: events.append(("revive", ns.agent_id))
        self.mp.main = lambda argv=None: events.append(("legacy-main", list(argv or [])))

        self.mp.switch_backend(argparse.Namespace(
            agent_id=self.agent_id, backend="codex", model="gpt-5.6-sol"
        ))

        self.assertEqual(events[0][0], "persist")
        self.assertEqual(events[0][1]["backend"], "codex")
        self.assertEqual(events[0][1]["model"], "gpt-5.6-sol")
        self.assertEqual(events[0][1]["state"], "switching")
        self.assertFalse(events[0][1]["retired"])
        self.assertEqual(events[-1], ("revive", self.agent_id))
        self.assertNotIn("legacy-main", [event[0] for event in events])
        self.assertLess(
            events.index(events[0]),
            next(i for i, event in enumerate(events) if event[:2] == ("tmux", ["kill-window", "-t", "mc-main:Boss"])),
        )

    def test_switch_rejects_backend_change_without_fresh_handoff(self):
        rec = {
            "agent_id": self.agent_id,
            "backend": "claude",
            "model": "sonnet",
            "session": "main",
            "tab": "Boss",
            "cwd": self.boss_dir,
            "is_master": True,
            "retired": False,
            "state": "alive",
        }
        self.mp.load_roster = lambda: [copy.deepcopy(rec)]
        with self.assertRaisesRegex(SystemExit, "fresh_handoff_required"):
            self.mp.switch_backend(argparse.Namespace(
                agent_id=self.agent_id,
                backend="codex",
                model="gpt-5.6-sol",
            ))

    def test_switch_parser_requires_explicit_backend_and_model(self):
        ns = self.mp.parser().parse_args([
            "switch", self.agent_id, "--backend", "codex", "--model", "gpt-5.6-sol",
        ])
        self.assertEqual(ns.backend, "codex")
        self.assertEqual(ns.model, "gpt-5.6-sol")


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(CodexBossContract)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("PASS Codex Boss launch and atomic backend switch")
    raise SystemExit(0 if result.wasSuccessful() else 1)
