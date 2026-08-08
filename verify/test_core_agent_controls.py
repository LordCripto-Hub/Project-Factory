#!/usr/bin/env python3
import json
import pathlib
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import core_agent_controls as controls


class CoreAgentControlsContract(unittest.TestCase):
    def setUp(self):
        self.roster = [
            {"agent_id": "node-1/main:Boss", "backend": "codex", "state": "alive", "retired": False, "model": "gpt-5.6-sol"},
            {"agent_id": "node-1/nightwatch:Nightwatch", "backend": "codex", "state": "dead", "retired": True, "model": "gpt-5.6-luna"},
        ]

    def test_capabilities_are_closed_and_ordered(self):
        self.assertEqual(controls.capabilities(), {"agents": ["node-1/main:Boss", "node-1/nightwatch:Nightwatch"], "models": ["gpt-5.6-sol", "gpt-5.6-luna"]})

    def test_rejects_engineer_model_backend_and_ambiguous_roster(self):
        cases = [
            ("kill", {"agent_id": "node-1/main:eng-1"}, self.roster, "unsupported_agent"),
            ("switch", {"agent_id": "node-1/main:Boss", "model": "custom-model"}, self.roster, "unsupported_model"),
            ("kill", {"agent_id": "node-1/main:Boss"}, [dict(self.roster[0], backend="claude")], "backend_mismatch"),
            ("kill", {"agent_id": "node-1/main:Boss"}, [], "roster_record_missing"),
            ("kill", {"agent_id": "node-1/main:Boss"}, [self.roster[0], self.roster[0]], "roster_record_ambiguous"),
        ]
        for action, body, roster, code in cases:
            with self.subTest(code=code), self.assertRaisesRegex(controls.ControlError, code):
                controls.build_command(action, body, roster)

    def test_state_compatibility_and_fixed_argument_vectors(self):
        self.assertEqual(controls.build_command("kill", {"agent_id": "node-1/main:Boss"}, self.roster), [str(ROOT / "bin" / "mp"), "kill", "node-1/main:Boss", "--reason", "hud-operator"])
        self.assertEqual(controls.build_command("revive", {"agent_id": "node-1/nightwatch:Nightwatch"}, self.roster), [str(ROOT / "bin" / "mp"), "revive", "node-1/nightwatch:Nightwatch"])
        self.assertEqual(controls.build_command("switch", {"agent_id": "node-1/main:Boss", "model": "gpt-5.6-luna"}, self.roster), [str(ROOT / "bin" / "mp"), "switch", "node-1/main:Boss", "--backend", "codex", "--model", "gpt-5.6-luna"])
        with self.assertRaisesRegex(controls.ControlError, "agent_already_alive"):
            controls.build_command("revive", {"agent_id": "node-1/main:Boss"}, self.roster)
        with self.assertRaisesRegex(controls.ControlError, "agent_not_alive"):
            controls.build_command("kill", {"agent_id": "node-1/nightwatch:Nightwatch"}, self.roster)

    def test_execute_confirms_roster_and_returns_bounded_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            path = pathlib.Path(td) / "roster.json"
            path.write_text(json.dumps(self.roster), encoding="utf-8")
            def runner(command, **kwargs):
                rows = json.loads(path.read_text(encoding="utf-8"))
                rows[0].update(state="dead", retired=True)
                path.write_text(json.dumps(rows), encoding="utf-8")
                self.assertFalse(kwargs["shell"])
                return subprocess.CompletedProcess(command, 0, "provider secret", "raw stderr")
            result = controls.execute("kill", {"agent_id": "node-1/main:Boss"}, path, runner=runner)
            self.assertEqual(result, {"ok": True, "agent_id": "node-1/main:Boss", "state": "dead", "model": "gpt-5.6-sol"})
            self.assertNotIn("secret", json.dumps(result))

    def test_concurrent_same_agent_fails_closed(self):
        entered = threading.Event()
        release = threading.Event()
        with controls.agent_operation("node-1/main:Boss"):
            with self.assertRaisesRegex(controls.ControlError, "operation_in_progress"):
                with controls.agent_operation("node-1/main:Boss"):
                    pass


if __name__ == "__main__":
    unittest.main(verbosity=2)

