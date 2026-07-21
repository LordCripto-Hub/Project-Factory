#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "memory_canary", ROOT / "bin" / "memory_canary.py"
)
memory_canary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(memory_canary)


class MemoryCanaryControlContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, value):
        path = self.root / "memory-canary-control.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_missing_control_defaults_disabled(self):
        control = memory_canary.load_control(self.root)
        self.assertFalse(control["enabled"])
        self.assertEqual(control["allowedProjects"], ["project-factory"])
        self.assertEqual(control["revision"], 1)

    def test_enable_is_atomic_private_and_idempotent(self):
        enabled = memory_canary.set_control(
            self.root,
            enabled=True,
            project="project-factory",
            now=lambda: 100.0,
        )
        self.assertTrue(enabled["enabled"])
        self.assertEqual(enabled["revision"], 2)
        path = self.root / "memory-canary-control.json"
        if os.name != "nt":
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        self.assertEqual(list(self.root.glob("*.tmp")), [])

        same = memory_canary.set_control(
            self.root,
            enabled=True,
            project="project-factory",
            now=lambda: 200.0,
        )
        self.assertEqual(same, enabled)

        disabled = memory_canary.set_control(
            self.root,
            enabled=False,
            now=lambda: 300.0,
        )
        self.assertFalse(disabled["enabled"])
        self.assertEqual(disabled["revision"], 3)
        self.assertEqual(disabled["updatedAt"], 300.0)

    def test_corrupt_unknown_and_invalid_types_fail_closed(self):
        path = self.root / "memory-canary-control.json"
        invalid_values = (
            "{broken",
            {
                "schemaVersion": 1,
                "enabled": False,
                "allowedProjects": ["project-factory"],
                "revision": 1,
                "updatedAt": 0,
                "extra": True,
            },
            {
                "schemaVersion": 1,
                "enabled": "yes",
                "allowedProjects": ["project-factory"],
                "revision": 1,
                "updatedAt": 0,
            },
            {
                "schemaVersion": 1,
                "enabled": False,
                "allowedProjects": ["project-factory", "project-factory"],
                "revision": 1,
                "updatedAt": 0,
            },
            {
                "schemaVersion": 1,
                "enabled": False,
                "allowedProjects": ["other"],
                "revision": 1,
                "updatedAt": 0,
            },
            {
                "schemaVersion": 1,
                "enabled": False,
                "allowedProjects": ["project-factory"],
                "revision": 0,
                "updatedAt": 0,
            },
        )
        for value in invalid_values:
            with self.subTest(value=value):
                path.write_text(
                    value if isinstance(value, str) else json.dumps(value),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(
                    memory_canary.MemoryCanaryError,
                    "canary_control_invalid",
                ):
                    memory_canary.load_control(self.root)

    def test_symlink_and_unapproved_project_fail_closed(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlink unavailable")
        target = self.root / "target.json"
        target.write_text(json.dumps(memory_canary.DEFAULT_CONTROL), encoding="utf-8")
        link = self.root / "memory-canary-control.json"
        try:
            os.symlink(target, link)
        except OSError as error:
            self.skipTest(f"symlink unavailable: {error}")
        with self.assertRaisesRegex(
            memory_canary.MemoryCanaryError,
            "canary_control_invalid",
        ):
            memory_canary.load_control(self.root)

        link.unlink()
        with self.assertRaisesRegex(
            memory_canary.MemoryCanaryError,
            "canary_project_denied",
        ):
            memory_canary.set_control(self.root, enabled=True, project="other")

    def test_task_authorization_is_explicit(self):
        control = {
            **memory_canary.DEFAULT_CONTROL,
            "enabled": True,
            "revision": 2,
        }
        memory_canary.assert_task_allowed(
            {
                "memoryCanary": True,
                "projectSlug": "project-factory",
                "contextQuestion": "Which verified constraint applies?",
            },
            control,
        )
        failures = (
            ({**control, "enabled": False}, "canary_disabled"),
            (control, "canary_not_requested"),
        )
        for candidate, code in failures:
            task = {
                "memoryCanary": code != "canary_not_requested",
                "projectSlug": "project-factory",
                "contextQuestion": "Question?",
            }
            with self.subTest(code=code), self.assertRaisesRegex(
                memory_canary.MemoryCanaryError, code
            ):
                memory_canary.assert_task_allowed(task, candidate)

        for task, code in (
            (
                {
                    "memoryCanary": True,
                    "projectSlug": "other",
                    "contextQuestion": "Question?",
                },
                "canary_project_denied",
            ),
            (
                {
                    "memoryCanary": True,
                    "projectSlug": "project-factory",
                    "contextQuestion": "",
                },
                "canary_question_required",
            ),
        ):
            with self.subTest(code=code), self.assertRaisesRegex(
                memory_canary.MemoryCanaryError, code
            ):
                memory_canary.assert_task_allowed(task, control)

    def test_mp_registers_the_bounded_control_cli(self):
        source = (ROOT / "bin" / "mp").read_text(encoding="utf-8")
        for marker in (
            "from memory_canary import",
            "def memory_canary_command(",
            'sub.add_parser("memory-canary")',
            'canary_sub.add_parser("status")',
            'canary_sub.add_parser("enable")',
            'canary_sub.add_parser("disable")',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
