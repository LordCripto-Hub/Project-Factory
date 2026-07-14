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
    "project_context", ROOT / "bin" / "project_context.py"
)
project_context = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(project_context)


def profile(**overrides):
    value = {
        "schemaVersion": 1,
        "revision": 1,
        "slug": "mypeople",
        "repository": "https://github.com/example/project.git",
        "workingDirectory": "/workspace/project",
        "allowedBranches": ["main"],
        "contextFiles": ["README.md", "AGENTS.md"],
        "verificationCommands": ["python3 -m unittest discover -s verify"],
        "allowedActions": ["read", "edit", "test"],
        "forbiddenActions": ["deploy", "push", "delete"],
        "limits": {
            "contextChars": 6000,
            "memoryTopK": 3,
            "memoryHops": 0,
            "memoryTimeoutSeconds": 8,
        },
        "memory": {
            "enabled": False,
            "serverUrl": "https://memory.example.invalid/mcp",
            "credentialRef": "env://MYPEOPLE_MEMORY_TOKEN",
        },
    }
    value.update(overrides)
    return value


class ProjectProfileContract(unittest.TestCase):
    def test_valid_profile_is_normalized(self):
        value = project_context.validate_profile(profile())
        self.assertEqual(value["slug"], "mypeople")
        self.assertEqual(value["limits"]["memoryTopK"], 3)

    def test_rejects_unknown_schema_and_fields(self):
        with self.assertRaisesRegex(
            project_context.ProfileError, "unsupported_schema_version"
        ):
            project_context.validate_profile(profile(schemaVersion=2))
        with self.assertRaisesRegex(project_context.ProfileError, "unknown_field"):
            project_context.validate_profile(profile(surprise=True))

    def test_rejects_plaintext_secrets_recursively(self):
        unsafe = profile()
        unsafe["memory"]["token"] = "secret"
        with self.assertRaisesRegex(
            project_context.ProfileError, "plaintext_secret_forbidden"
        ):
            project_context.validate_profile(unsafe)

    def test_read_only_bounds_are_hard_limits(self):
        for key, value in (
            ("memoryTopK", 4),
            ("memoryHops", 1),
            ("contextChars", 20001),
            ("memoryTimeoutSeconds", 16),
        ):
            unsafe = profile()
            unsafe["limits"][key] = value
            with self.subTest(key=key), self.assertRaises(project_context.ProfileError):
                project_context.validate_profile(unsafe)

    def test_remote_memory_requires_https_and_env_reference(self):
        unsafe = profile()
        unsafe["memory"] = {
            "enabled": True,
            "serverUrl": "http://remote.example/mcp",
            "credentialRef": "raw-secret",
        }
        with self.assertRaises(project_context.ProfileError):
            project_context.validate_profile(unsafe)

    def test_working_directory_must_be_absolute(self):
        with self.assertRaisesRegex(project_context.ProfileError, "working_directory"):
            project_context.validate_profile(profile(workingDirectory="relative/path"))

    def test_load_profile_requires_filename_and_body_slug_match(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "mypeople.json"
            path.write_text(json.dumps(profile(slug="other")), encoding="utf-8")
            with self.assertRaisesRegex(
                project_context.ProfileError, "profile_slug_mismatch"
            ):
                project_context.load_profile(temp, "mypeople")

    def test_profile_path_cannot_escape_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(project_context.ProfileError):
                project_context.load_profile(temp, "../outside")


if __name__ == "__main__":
    unittest.main(verbosity=2)
