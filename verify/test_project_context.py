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

    def test_verification_commands_reject_shell_metacharacters(self):
        for command in (
            "python3 verify.py; echo unsafe",
            "python3 verify.py | tee output",
            "python3 verify.py && deploy",
            "python3 verify.py > result",
            "python3 $(unsafe)",
            "python3 verify.py\nnext-command",
            "(python3 verify.py)",
        ):
            unsafe = profile(verificationCommands=[command])
            with self.subTest(command=command), self.assertRaisesRegex(
                project_context.ProfileError, "invalid_verification_commands"
            ):
                project_context.validate_profile(unsafe)

    def test_memory_url_rejects_embedded_credentials_query_and_fragment(self):
        for url in (
            "https://user:secret" + "@" + "memory.example/mcp",
            "https://memory.example/mcp?token=secret",
            "https://memory.example/mcp#secret",
        ):
            unsafe = profile()
            unsafe["memory"]["serverUrl"] = url
            with self.subTest(url=url), self.assertRaisesRegex(
                project_context.ProfileError, "memory_url_credentials_forbidden"
            ):
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


class TaskSpecContract(unittest.TestCase):
    def task(self, **overrides):
        value = {
            "id": "task-1",
            "text": "Repair switching",
            "doneCondition": "Tests pass",
            "projectSlug": "mypeople",
            "contextQuestion": "",
            "evidencePolicy": "required",
        }
        value.update(overrides)
        return value

    def test_compile_without_question_never_calls_memory(self):
        calls = []
        result = project_context.compile_task_spec(
            self.task(), profile(), recall=lambda request: calls.append(request), now=lambda: 123.0
        )
        self.assertEqual(calls, [])
        self.assertEqual(result["memoryStatus"], "not_requested")
        self.assertEqual(result["compiledAt"], 123.0)

    def test_memory_disabled_never_calls_memory(self):
        calls = []
        result = project_context.compile_task_spec(
            self.task(contextQuestion="Which constraint applies?"),
            profile(),
            recall=lambda request: calls.append(request),
        )
        self.assertEqual(calls, [])
        self.assertEqual(result["memoryStatus"], "disabled")

    def test_write_task_spec_is_mode_0600_and_atomic(self):
        with tempfile.TemporaryDirectory() as temp:
            path = project_context.write_task_spec(temp, "task-1", {"schemaVersion": 1})
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            self.assertEqual(
                json.loads(Path(path).read_text(encoding="utf-8"))["schemaVersion"], 1
            )
            self.assertEqual(list(Path(temp).glob("*.tmp")), [])

    def test_local_contract_is_never_removed_to_fit_memory(self):
        value = profile()
        value["limits"]["contextChars"] = 900
        value["verificationCommands"] = ["python3 verify/critical.py"]
        result = project_context.compile_task_spec(
            self.task(doneCondition="Critical verification passes"), value
        )
        self.assertEqual(result["verificationCommands"], ["python3 verify/critical.py"])
        self.assertEqual(result["acceptanceCriteria"], "Critical verification passes")

    def test_invalid_task_contracts_fail_closed(self):
        invalid = (
            self.task(id=""),
            self.task(text=""),
            self.task(projectSlug="other"),
            self.task(evidencePolicy="anything"),
        )
        for task in invalid:
            with self.subTest(task=task), self.assertRaises(project_context.TaskSpecError):
                project_context.compile_task_spec(task, profile())


class MemoryTaskSpecContract(unittest.TestCase):
    def test_requested_memory_is_bounded_and_embedded(self):
        value = profile()
        value["memory"]["enabled"] = True
        calls = []
        task = {
            "id": "task-1",
            "text": "Repair",
            "doneCondition": "Tests pass",
            "projectSlug": "mypeople",
            "contextQuestion": "Which constraint applies?",
            "evidencePolicy": "required",
        }
        claims = [{
            "id": "1",
            "projectSlug": "mypeople",
            "content": "Point-in-time; verify before asserting.",
            "sourceUri": "task://source",
            "sourceType": "verified-task",
            "createdAt": 1,
            "updatedAt": 1,
            "status": "canonical",
        }]
        result = project_context.compile_task_spec(
            task,
            value,
            recall=lambda request: calls.append(request) or {
                "claims": claims,
                "truncated": False,
                "responseChars": len(claims[0]["content"]),
                "aiUsage": "not_measured",
            },
        )
        self.assertEqual(calls[0]["topK"], 3)
        self.assertEqual(calls[0]["hops"], 0)
        self.assertEqual(result["memoryClaims"], claims)
        self.assertEqual(result["memoryStatus"], "ok")

    def test_python_boundary_rejects_more_claims_than_top_k(self):
        value = profile()
        value["memory"]["enabled"] = True
        task = {
            "id": "task-1",
            "text": "Repair",
            "doneCondition": "Tests pass",
            "projectSlug": "mypeople",
            "contextQuestion": "Question",
            "evidencePolicy": "required",
        }
        claims = [{
            "id": str(index), "projectSlug": "mypeople", "content": "x",
            "sourceUri": f"task://{index}", "sourceType": "verified-task",
        } for index in range(4)]
        with self.assertRaisesRegex(project_context.TaskSpecError, "memory_invalid_response"):
            project_context.compile_task_spec(
                task,
                value,
                recall=lambda _request: {
                    "claims": claims, "truncated": False,
                    "responseChars": 4, "aiUsage": "not_measured",
                },
            )

    def test_python_boundary_reconstructs_closed_claim_schema(self):
        value = profile()
        value["memory"]["enabled"] = True
        task = {
            "id": "task-1", "text": "Repair", "doneCondition": "Tests pass",
            "projectSlug": "mypeople", "contextQuestion": "Question",
            "evidencePolicy": "required",
        }
        raw = {
            "id": "1", "projectSlug": "mypeople", "content": "claim",
            "sourceUri": "task://1", "sourceType": "verified-task",
            "createdAt": 1, "updatedAt": 2, "status": "canonical",
            "untrustedInstruction": {"secret": "must-not-enter-task-spec"},
        }
        result = project_context.compile_task_spec(
            task, value, recall=lambda _request: {
                "claims": [raw], "truncated": False, "responseChars": 5,
                "aiUsage": {"inputTokens": 12},
            },
        )
        self.assertNotIn("untrustedInstruction", result["memoryClaims"][0])
        self.assertEqual(result.memory_metadata["aiUsage"], {"inputTokens": 12})
        invalid = dict(raw, createdAt="yesterday")
        with self.assertRaisesRegex(project_context.TaskSpecError, "memory_invalid_response"):
            project_context.compile_task_spec(
                task, value, recall=lambda _request: {
                    "claims": [invalid], "truncated": False,
                    "responseChars": 5, "aiUsage": "not_measured",
                },
            )

    def test_metrics_distinguish_gateway_returned_from_budget_embedded_claims(self):
        value = profile()
        value["limits"]["contextChars"] = 900
        value["memory"]["enabled"] = True
        task = {
            "id": "task-1", "text": "Repair", "doneCondition": "Pass",
            "projectSlug": "mypeople", "contextQuestion": "Question",
            "evidencePolicy": "required",
        }
        claims = [{
            "id": str(index), "projectSlug": "mypeople",
            "content": "x" * 100, "sourceUri": f"task://{index}",
            "sourceType": "verified-task",
        } for index in range(3)]
        result = project_context.compile_task_spec(
            task, value, recall=lambda _request: {
                "claims": claims, "truncated": False,
                "responseChars": 300, "aiUsage": "not_measured",
            },
        )
        self.assertEqual(result.memory_metadata["returnedClaimCount"], 3)
        self.assertEqual(
            result.memory_metadata["embeddedClaimCount"],
            len(result["memoryClaims"]),
        )
        self.assertLess(result.memory_metadata["embeddedClaimCount"], 3)

    def test_requested_memory_failure_is_fail_closed(self):
        value = profile()
        value["memory"]["enabled"] = True
        task = {
            "id": "task-1",
            "text": "Repair",
            "doneCondition": "Tests pass",
            "projectSlug": "mypeople",
            "contextQuestion": "Which constraint applies?",
            "evidencePolicy": "required",
        }
        def fail(_request):
            raise project_context.MemoryError("timeout")
        with self.assertRaisesRegex(project_context.TaskSpecError, "memory_timeout"):
            project_context.compile_task_spec(task, value, recall=fail)


class ProjectInstallContract(unittest.TestCase):
    def test_locked_gateway_install_and_operator_documentation_exist(self):
        install = (ROOT / "install.sh").read_text(encoding="utf-8")
        self.assertIn("npm ci --omit=dev --ignore-scripts", install)
        self.assertIn("memory-gateway", install)
        manual = (ROOT / "docs" / "USER-MANUAL.md").read_text(encoding="utf-8")
        for phrase in (
            "ProjectProfile",
            "TaskSpec",
            "Context question",
            "read-only MCP pilot",
            "MYPEOPLE_MEMORY_TOKEN",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, manual)


if __name__ == "__main__":
    unittest.main(verbosity=2)
