#!/usr/bin/env python3
"""Codex-native internal doctrine and composer readiness contract."""
from __future__ import annotations

import argparse
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest


def load_runtime(path: str):
    loader = importlib.machinery.SourceFileLoader(
        "mypeople_mp_codex_doctrine_under_test_" + os.urandom(4).hex(), path
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class Result:
    def __init__(self, stdout=""):
        self.returncode = 0
        self.stdout = stdout
        self.stderr = ""


class CodexDoctrineContract(unittest.TestCase):
    def setUp(self):
        self.mp = load_runtime(os.environ.get("MYPEOPLE_MP_BIN", "/home/mp/mypeople/bin/mp"))

    def test_doctrine_is_atomic_idempotent_and_codex_aware(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "boss-source.md"
            source.write_text("# Existing Boss doctrine\n\nUse the TODO board.\n", encoding="utf-8")
            cwd = Path(tmp) / "boss"
            self.mp.ensure_codex_doctrine(str(cwd), str(source))
            first = (cwd / "AGENTS.md").read_text(encoding="utf-8")
            self.mp.ensure_codex_doctrine(str(cwd), str(source))
            second = (cwd / "AGENTS.md").read_text(encoding="utf-8")

            self.assertEqual(first, second)
            self.assertIn("# Existing Boss doctrine", first)
            self.assertIn("--backend codex", first)
            self.assertIn("--backend codex --model gpt-5.6-luna", first)
            self.assertNotIn("gpt-5.4-mini", first)
            self.assertFalse(list(cwd.glob("AGENTS.md.*.tmp")))

    def test_codex_master_spawn_installs_doctrine(self):
        events = []
        with tempfile.TemporaryDirectory() as tmp:
            self.mp.ensure_codex_doctrine = lambda cwd, source=None: events.append((os.path.realpath(cwd), source))
            self._spawn(tmp, "node-1/main:Boss", "Boss", True)
            self.assertEqual(events, [(os.path.realpath(tmp), None)])

    def test_codex_nightwatch_spawn_installs_claude_doctrine_as_agents(self):
        events = []
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "CLAUDE.md"
            source.write_text("# Nightwatch doctrine\n", encoding="utf-8")
            self.mp.ensure_codex_doctrine = lambda cwd, source=None: events.append((os.path.realpath(cwd), source))
            self._spawn(tmp, "node-1/nightwatch:Nightwatch", "Nightwatch", False)
            self.assertEqual(events, [(os.path.realpath(tmp), str(source))])

    def _spawn(self, tmp, agent_id, tab, master):
        self.mp.window_exists = lambda _target: True
        self.mp.load_roster = lambda: []
        self.mp.update_roster = lambda _rec: None
        self.mp.write_status = lambda *_args, **_kwargs: None
        self.mp.queue_register = lambda _rec: None
        self.mp.recorder = lambda *_args: None
        self.mp.spawn(argparse.Namespace(
            agent_id=agent_id,
            backend="codex",
            cwd=tmp,
            boss=None if master else "node-1/main:Boss",
            master=master,
            model="gpt-5.6-sol" if master else "gpt-5.6-luna",
            owner_task=None,
            temporary=False,
        ))

    def test_wait_for_composer_accepts_codex_trust_gate(self):
        panes = iter([
            "Do you trust the contents of this directory?\\n1. Yes, continue",
            "OpenAI Codex v0.144.3\\n> ",
        ])
        events = []

        def run_tmux(args, **kwargs):
            events.append(list(args))
            if args[0] == "capture-pane":
                return Result(next(panes))
            return Result()

        self.mp.run_tmux = run_tmux
        self.mp.time.sleep = lambda _seconds: None
        self.assertTrue(self.mp.wait_for_composer("mc-nightwatch:Nightwatch", timeout=1))
        self.assertIn(
            ["send-keys", "-t", "mc-nightwatch:Nightwatch", "1", "Enter"],
            events,
        )

    def test_wait_for_composer_recognizes_codex_prompt(self):
        self.mp.run_tmux = lambda *_args, **_kwargs: Result("OpenAI Codex v0.144.3\n> ")
        self.assertTrue(self.mp.wait_for_composer("mc-main:Boss", timeout=0.1))


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(CodexDoctrineContract)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("PASS Codex internal doctrines, delegated backend policy, and composer readiness")
    raise SystemExit(0 if result.wasSuccessful() else 1)
