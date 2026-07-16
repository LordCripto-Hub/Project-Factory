#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "project_context_gateway", ROOT / "bin" / "project_context.py"
)
project_context = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(project_context)


def enabled_profile():
    return {
        "schemaVersion": 1,
        "revision": 1,
        "slug": "mypeople",
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
            "enabled": True,
            "serverUrl": "https://memory.example.invalid/mcp",
            "credentialRef": "env://MYPEOPLE_MEMORY_TOKEN",
        },
    }


class MemoryGatewayBoundary(unittest.TestCase):
    def test_secret_is_only_in_child_environment(self):
        observed = {}

        def runner(command, **kwargs):
            observed.update(command=command, **kwargs)
            response = {
                "ok": True,
                "claims": [],
                "truncated": False,
                "responseChars": 0,
                "aiUsage": "not_measured",
            }
            return subprocess.CompletedProcess(command, 0, json.dumps(response), "")

        with patch.dict(os.environ, {
            "MYPEOPLE_MEMORY_TOKEN": "fixture-secret",
            "UNRELATED_PROVIDER_SECRET": "must-not-cross-boundary",
        }):
            result = project_context.call_memory_gateway(
                enabled_profile(), "Which constraint applies?", runner=runner, max_chars=1200
            )
        request = json.loads(observed["input"])
        self.assertEqual(request["credentialEnv"], "MYPEOPLE_MEMORY_TOKEN")
        self.assertNotIn("fixture-secret", observed["input"])
        self.assertEqual(observed["env"]["MYPEOPLE_MEMORY_TOKEN"], "fixture-secret")
        self.assertNotIn("UNRELATED_PROVIDER_SECRET", observed["env"])
        self.assertEqual(observed["command"][0], "node")
        self.assertTrue(observed["command"][1].endswith("memory-gateway.mjs"))
        self.assertEqual(observed["timeout"], 10)
        self.assertFalse(observed["shell"])
        self.assertEqual(result["claims"], [])

    def test_runtime_config_cannot_replace_the_trusted_gateway(self):
        observed = {}
        def runner(command, **kwargs):
            observed["command"] = command
            response = {"ok": True, "claims": [], "truncated": False,
                        "responseChars": 0, "aiUsage": "not_measured"}
            return subprocess.CompletedProcess(command, 0, json.dumps(response), "")
        with patch.dict(project_context.RUNTIME_ENV, {
            "MEMORY_GATEWAY_PATH": "/configured/memory-gateway.mjs"
        }, clear=True), patch.dict(os.environ, {
            "MYPEOPLE_MEMORY_TOKEN": "fixture-secret"
        }, clear=True):
            project_context.call_memory_gateway(
                enabled_profile(), "Question", runner=runner
            )
        self.assertNotEqual(observed["command"][1], "/configured/memory-gateway.mjs")
        self.assertEqual(
            Path(observed["command"][1]).resolve(),
            (ROOT / "memory-gateway" / "memory-gateway.mjs").resolve(),
        )

    def test_missing_token_is_typed_unauthorized(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(project_context.MemoryError, "unauthorized"):
                project_context.call_memory_gateway(enabled_profile(), "Question")

    def test_empty_or_oversized_environment_token_is_unauthorized(self):
        for token in ("", "   ", "x" * 4097):
            with self.subTest(size=len(token)), patch.dict(
                os.environ, {"MYPEOPLE_MEMORY_TOKEN": token}, clear=True
            ):
                with self.assertRaisesRegex(
                    project_context.MemoryError, "unauthorized"
                ):
                    project_context.call_memory_gateway(enabled_profile(), "Question")

    def test_secret_file_is_resolved_only_into_child_environment(self):
        observed = {}

        def runner(command, **kwargs):
            observed.update(command=command, **kwargs)
            response = {
                "ok": True,
                "claims": [],
                "truncated": False,
                "responseChars": 0,
                "aiUsage": "not_measured",
            }
            return subprocess.CompletedProcess(command, 0, json.dumps(response), "")

        with tempfile.TemporaryDirectory() as temp:
            secret_path = Path(temp) / "MYPEOPLE_MEMORY_TOKEN"
            secret_path.write_text("fixture-file-secret\n", encoding="utf-8")
            value = enabled_profile()
            value["memory"]["credentialRef"] = (
                "file:///run/mypeople-secrets/MYPEOPLE_MEMORY_TOKEN"
            )
            with patch.object(
                project_context,
                "MEMORY_SECRET_ROOT",
                Path(temp),
            ):
                project_context.call_memory_gateway(
                    value, "Question", runner=runner, max_chars=1200
                )

        request = json.loads(observed["input"])
        self.assertEqual(request["credentialEnv"], "MYPEOPLE_MEMORY_TOKEN")
        self.assertNotIn("credentialRef", request)
        self.assertNotIn("fixture-file-secret", observed["input"])
        self.assertEqual(
            observed["env"]["MYPEOPLE_MEMORY_TOKEN"], "fixture-file-secret"
        )
        self.assertNotIn(
            "file:///run/mypeople-secrets/MYPEOPLE_MEMORY_TOKEN", observed["input"]
        )

    def test_missing_empty_and_oversized_secret_files_are_unauthorized(self):
        value = enabled_profile()
        value["memory"]["credentialRef"] = (
            "file:///run/mypeople-secrets/MYPEOPLE_MEMORY_TOKEN"
        )
        with tempfile.TemporaryDirectory() as temp, patch.object(
            project_context, "MEMORY_SECRET_ROOT", Path(temp)
        ):
            secret_path = Path(temp) / "MYPEOPLE_MEMORY_TOKEN"
            for contents in (None, b"", b"x" * 4097):
                if contents is None:
                    secret_path.unlink(missing_ok=True)
                else:
                    secret_path.write_bytes(contents)
                with self.subTest(size=None if contents is None else len(contents)):
                    with self.assertRaisesRegex(
                        project_context.MemoryError, "unauthorized"
                    ):
                        project_context.call_memory_gateway(value, "Question")

    def test_secret_file_symlinks_are_unauthorized(self):
        value = enabled_profile()
        value["memory"]["credentialRef"] = (
            "file:///run/mypeople-secrets/MYPEOPLE_MEMORY_TOKEN"
        )
        with tempfile.TemporaryDirectory() as temp, patch.object(
            project_context, "MEMORY_SECRET_ROOT", Path(temp)
        ):
            target = Path(temp) / "target"
            target.write_text("fixture-file-secret", encoding="utf-8")
            (Path(temp) / "MYPEOPLE_MEMORY_TOKEN").symlink_to(target)
            with self.assertRaisesRegex(
                project_context.MemoryError, "unauthorized"
            ):
                project_context.call_memory_gateway(value, "Question")

    def test_timeout_and_raw_stderr_are_not_exposed(self):
        def runner(*args, **kwargs):
            raise subprocess.TimeoutExpired(args[0], 10, stderr="private response body")

        with patch.dict(os.environ, {"MYPEOPLE_MEMORY_TOKEN": "fixture-secret"}):
            with self.assertRaises(project_context.MemoryError) as caught:
                project_context.call_memory_gateway(
                    enabled_profile(), "Question", runner=runner
                )
        self.assertEqual(str(caught.exception), "timeout")
        self.assertNotIn("private", str(caught.exception))

    def test_malformed_or_extra_stdout_is_invalid_response(self):
        for stdout in ("not-json", '{"ok":true}\n{"ok":true}'):
            def runner(command, **kwargs):
                return subprocess.CompletedProcess(command, 0, stdout, "private stderr")

            with self.subTest(stdout=stdout), patch.dict(
                os.environ, {"MYPEOPLE_MEMORY_TOKEN": "fixture-secret"}
            ):
                with self.assertRaisesRegex(
                    project_context.MemoryError, "invalid_response"
                ):
                    project_context.call_memory_gateway(
                        enabled_profile(), "Question", runner=runner
                    )


if __name__ == "__main__":
    unittest.main(verbosity=2)
