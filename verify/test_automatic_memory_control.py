#!/usr/bin/env python3
"""Contracts for reversible project-scoped automatic memory modes."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "memory_canary_modes", ROOT / "bin" / "memory_canary.py"
)
memory_control = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(memory_control)


class AutomaticMemoryControlContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, value):
        (self.root / memory_control.CONTROL_NAME).write_text(
            json.dumps(value), encoding="utf-8"
        )

    def test_legacy_controls_migrate_without_revision_change(self):
        for enabled, expected in ((True, "manual_canary"), (False, "off")):
            with self.subTest(enabled=enabled):
                self.write({
                    "schemaVersion": 1,
                    "enabled": enabled,
                    "allowedProjects": ["project-factory"],
                    "revision": 7,
                    "updatedAt": 10,
                })
                control = memory_control.load_control(self.root)
                self.assertEqual(control["schemaVersion"], 2)
                self.assertEqual(control["mode"], expected)
                self.assertEqual(control["revision"], 7)

    def test_automatic_to_off_is_atomic_private_and_revisioned(self):
        automatic = memory_control.set_control(
            self.root, mode="automatic", now=lambda: 20
        )
        disabled = memory_control.set_control(
            self.root, mode="off", now=lambda: 21
        )
        self.assertEqual(automatic["mode"], "automatic")
        self.assertEqual(disabled["mode"], "off")
        self.assertEqual(disabled["revision"], automatic["revision"] + 1)
        path = self.root / memory_control.CONTROL_NAME
        stored = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(set(stored), memory_control.CONTROL_FIELDS)
        self.assertNotIn("enabled", stored)
        if os.name != "nt":
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_invalid_mode_and_project_fail_closed(self):
        for mode, project, code in (
            ("expensive", "project-factory", "memory_mode_invalid"),
            ("automatic", "other", "canary_project_denied"),
        ):
            with self.subTest(mode=mode, project=project):
                with self.assertRaisesRegex(memory_control.MemoryCanaryError, code):
                    memory_control.set_control(self.root, mode=mode, project=project)

    def test_mp_registers_new_mode_cli_and_preserves_canary_cli(self):
        source = (ROOT / "bin" / "mp").read_text(encoding="utf-8")
        for marker in (
            "def memory_mode_command(",
            'memory=sub.add_parser("memory")',
            'memory_sub.add_parser("mode")',
            'choices=["status","off","automatic","manual-canary"]',
            'sub.add_parser("memory-canary")',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
