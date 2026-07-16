#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "memory_profile", ROOT / "bin" / "memory_profile.py"
)
memory_profile = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(memory_profile)


def profile(**overrides):
    value = {
        "schemaVersion": 1,
        "revision": 7,
        "slug": "project-factory",
        "repository": "https://github.com/example/project.git",
        "workingDirectory": "/workspace/project",
        "allowedBranches": ["main"],
        "contextFiles": ["README.md"],
        "verificationCommands": ["python3 verify.py"],
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
            "serverUrl": "https://old.example.invalid/mcp",
            "credentialRef": "env://MYPEOPLE_MEMORY_TOKEN",
        },
    }
    value.update(overrides)
    return value


class MemoryProfileActivation(unittest.TestCase):
    def write_profile(self, root, value=None, filename="project-factory.json"):
        path = Path(root) / filename
        path.write_text(json.dumps(value or profile()), encoding="utf-8")
        return path

    def test_enable_increments_revision_preserves_contract_and_writes_privately(self):
        with tempfile.TemporaryDirectory() as temp:
            profiles = Path(temp) / "profiles"
            profiles.mkdir()
            path = self.write_profile(profiles)
            secret = Path(temp) / "MYPEOPLE_MEMORY_TOKEN"
            secret.write_text("fixture-secret", encoding="utf-8")
            before = json.loads(path.read_text(encoding="utf-8"))

            metadata = memory_profile.update_memory_profile(
                "enable",
                project="project-factory",
                server_url="https://memory.example.invalid/mcp",
                profiles_dir=profiles,
                secret_path=secret,
            )

            after = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(after["revision"], 8)
            self.assertEqual(after["memory"], {
                "enabled": True,
                "serverUrl": "https://memory.example.invalid/mcp",
                "credentialRef": (
                    "file:///run/mypeople-secrets/MYPEOPLE_MEMORY_TOKEN"
                ),
            })
            for key in set(before) - {"revision", "memory"}:
                self.assertEqual(after[key], before[key])
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            self.assertEqual(list(profiles.glob("*.tmp")), [])
            self.assertEqual(metadata, {
                "project": "project-factory",
                "revision": 8,
                "memoryEnabled": True,
            })
            self.assertNotIn("fixture-secret", json.dumps(metadata))

    def test_enable_refuses_missing_or_empty_runtime_secret(self):
        with tempfile.TemporaryDirectory() as temp:
            profiles = Path(temp) / "profiles"
            profiles.mkdir()
            path = self.write_profile(profiles)
            secret = Path(temp) / "MYPEOPLE_MEMORY_TOKEN"
            for contents in (None, ""):
                if contents is None:
                    secret.unlink(missing_ok=True)
                else:
                    secret.write_text(contents, encoding="utf-8")
                with self.subTest(contents=contents), self.assertRaisesRegex(
                    memory_profile.MemoryProfileError, "memory_secret_unavailable"
                ):
                    memory_profile.update_memory_profile(
                        "enable",
                        project="project-factory",
                        server_url="https://memory.example.invalid/mcp",
                        profiles_dir=profiles,
                        secret_path=secret,
                    )
                self.assertEqual(
                    json.loads(path.read_text(encoding="utf-8"))["revision"], 7
                )

    def test_disable_does_not_require_secret_and_preserves_server(self):
        with tempfile.TemporaryDirectory() as temp:
            profiles = Path(temp) / "profiles"
            profiles.mkdir()
            enabled = profile()
            enabled["memory"] = {
                "enabled": True,
                "serverUrl": "https://memory.example.invalid/mcp",
                "credentialRef": (
                    "file:///run/mypeople-secrets/MYPEOPLE_MEMORY_TOKEN"
                ),
            }
            path = self.write_profile(profiles, enabled)
            metadata = memory_profile.update_memory_profile(
                "disable",
                project="project-factory",
                profiles_dir=profiles,
                secret_path=Path(temp) / "absent",
            )
            after = json.loads(path.read_text(encoding="utf-8"))
            self.assertFalse(after["memory"]["enabled"])
            self.assertEqual(after["memory"]["serverUrl"], enabled["memory"]["serverUrl"])
            self.assertEqual(after["revision"], 8)
            self.assertFalse(metadata["memoryEnabled"])

    def test_reapplying_same_state_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            profiles = Path(temp) / "profiles"
            profiles.mkdir()
            secret = Path(temp) / "MYPEOPLE_MEMORY_TOKEN"
            secret.write_text("fixture-secret", encoding="utf-8")
            path = self.write_profile(profiles)

            first_disable = memory_profile.update_memory_profile(
                "disable",
                project="project-factory",
                profiles_dir=profiles,
                secret_path=secret,
            )
            self.assertEqual(first_disable["revision"], 7)
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8"))["revision"], 7
            )

            memory_profile.update_memory_profile(
                "enable",
                project="project-factory",
                server_url="https://memory.example.invalid/mcp",
                profiles_dir=profiles,
                secret_path=secret,
            )
            enabled_revision = json.loads(
                path.read_text(encoding="utf-8")
            )["revision"]
            second_enable = memory_profile.update_memory_profile(
                "enable",
                project="project-factory",
                server_url="https://memory.example.invalid/mcp",
                profiles_dir=profiles,
                secret_path=secret,
            )
            self.assertEqual(second_enable["revision"], enabled_revision)
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8"))["revision"],
                enabled_revision,
            )

    def test_profile_filename_body_slug_and_https_are_validated_before_write(self):
        with tempfile.TemporaryDirectory() as temp:
            profiles = Path(temp) / "profiles"
            profiles.mkdir()
            path = self.write_profile(profiles, profile(slug="different"))
            secret = Path(temp) / "MYPEOPLE_MEMORY_TOKEN"
            secret.write_text("fixture-secret", encoding="utf-8")
            with self.assertRaisesRegex(
                memory_profile.MemoryProfileError, "profile_slug_mismatch"
            ):
                memory_profile.update_memory_profile(
                    "enable",
                    project="project-factory",
                    server_url="https://memory.example.invalid/mcp",
                    profiles_dir=profiles,
                    secret_path=secret,
                )
            self.write_profile(profiles)
            with self.assertRaisesRegex(
                memory_profile.MemoryProfileError, "memory_https_required"
            ):
                memory_profile.update_memory_profile(
                    "enable",
                    project="project-factory",
                    server_url="http://memory.example.invalid/mcp",
                    profiles_dir=profiles,
                    secret_path=secret,
                )
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8"))["revision"], 7
            )

    def test_cli_prints_metadata_only_and_installer_exposes_command(self):
        with tempfile.TemporaryDirectory() as temp:
            profiles = Path(temp) / "profiles"
            profiles.mkdir()
            self.write_profile(profiles)
            secret = Path(temp) / "MYPEOPLE_MEMORY_TOKEN"
            secret.write_text("fixture-secret", encoding="utf-8")
            completed = subprocess.run(
                [
                    str(ROOT / "bin" / "memory-profile"),
                    "enable",
                    "--project", "project-factory",
                    "--server-url", "https://memory.example.invalid/mcp",
                    "--profiles-dir", str(profiles),
                    "--secret-path", str(secret),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            output = json.loads(completed.stdout)
            self.assertEqual(output["project"], "project-factory")
            self.assertNotIn("fixture-secret", completed.stdout + completed.stderr)
            install = (ROOT / "install.sh").read_text(encoding="utf-8")
            self.assertIn('"$ROOT/bin/memory-profile"', install)


if __name__ == "__main__":
    unittest.main(verbosity=2)
