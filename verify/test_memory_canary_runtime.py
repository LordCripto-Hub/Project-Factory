#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


memory_canary = load("memory_canary_runtime", ROOT / "bin" / "memory_canary.py")
project_context = load("project_context_runtime", ROOT / "bin" / "project_context.py")


def profile(enabled=True):
    return {
        "schemaVersion": 1,
        "revision": 4,
        "slug": "project-factory",
        "repository": "https://github.com/example/project-factory.git",
        "workingDirectory": "/workspace/project-factory",
        "allowedBranches": ["main"],
        "contextFiles": ["README.md", "AGENTS.md"],
        "verificationCommands": ["python3 verify/test_memory_canary_runtime.py"],
        "allowedActions": ["read", "edit", "test"],
        "forbiddenActions": ["deploy", "push", "delete"],
        "limits": {
            "contextChars": 8000,
            "memoryTopK": 3,
            "memoryHops": 0,
            "memoryTimeoutSeconds": 8,
        },
        "memory": {
            "enabled": enabled,
            "serverUrl": "https://memory.example.invalid/mcp",
            "credentialRef": "env://MYPEOPLE_MEMORY_TOKEN",
        },
    }


def task(canary=True, project="project-factory", question="Which constraint applies?"):
    return {
        "id": "task-1",
        "text": "Repair provider switching",
        "doneCondition": "Focused tests pass",
        "projectSlug": project,
        "contextQuestion": question,
        "memoryCanary": canary,
        "evidencePolicy": "required",
    }


def enabled_control():
    return {
        **memory_canary.DEFAULT_CONTROL,
        "enabled": True,
        "revision": 2,
        "updatedAt": 50.0,
    }


def claims_response(count=3):
    claims = [
        {
            "id": f"claim-{index}",
            "projectSlug": "project-factory",
            "content": f"Verified constraint {index}",
            "sourceUri": f"git://project-factory/commit-{index}",
            "sourceType": "git_commit",
            "status": "verified",
        }
        for index in range(1, count + 1)
    ]
    return {
        "claims": claims,
        "truncated": False,
        "responseChars": sum(len(item["content"]) for item in claims),
        "aiUsage": "not_measured",
    }


class MemoryCanaryRuntimeContract(unittest.TestCase):
    def test_active_attempt_compiles_baseline_candidate_and_exact_delta(self):
        calls = []

        def recall(request):
            calls.append(request)
            return claims_response()

        result = memory_canary.compile_attempt(
            task=task(),
            profile=profile(),
            control=enabled_control(),
            compile_spec=project_context.compile_task_spec,
            recall=recall,
            now=lambda: 100.0,
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["baseline"]["memoryStatus"], "disabled")
        self.assertEqual(result["baseline"]["memoryClaims"], [])
        self.assertEqual(result["candidate"]["memoryStatus"], "ok")
        self.assertEqual(len(result["candidate"]["memoryClaims"]), 3)
        receipt = result["receipt"]
        self.assertEqual(receipt["memoryStatus"], "ok")
        self.assertEqual(receipt["embeddedClaimCount"], 3)
        self.assertEqual(
            receipt["memoryDeltaCharacters"],
            memory_canary.canonical_char_count(result["candidate"])
            - memory_canary.canonical_char_count(result["baseline"]),
        )
        self.assertEqual(
            receipt["memoryDeltaTokensEstimated"],
            (receipt["memoryDeltaCharacters"] + 3) // 4,
        )
        self.assertNotIn("memoryClaims", receipt)
        self.assertNotIn("contextQuestion", receipt)

    def test_non_canary_never_calls_recall(self):
        calls = []
        result = memory_canary.compile_attempt(
            task=task(canary=False),
            profile=profile(),
            control=enabled_control(),
            compile_spec=project_context.compile_task_spec,
            recall=lambda request: calls.append(request),
            now=lambda: 100.0,
        )
        self.assertEqual(calls, [])
        self.assertEqual(result["candidate"]["memoryStatus"], "disabled")
        self.assertEqual(result["receipt"]["memoryStatus"], "not_requested")

    def test_disabled_and_wrong_project_fail_before_recall(self):
        for candidate_task, control, code in (
            (
                task(),
                {**enabled_control(), "enabled": False},
                "canary_disabled",
            ),
            (
                task(project="other"),
                enabled_control(),
                "canary_project_denied",
            ),
        ):
            calls = []
            with self.subTest(code=code), self.assertRaisesRegex(
                memory_canary.MemoryCanaryError, code
            ):
                memory_canary.compile_attempt(
                    task=candidate_task,
                    profile=profile(),
                    control=control,
                    compile_spec=project_context.compile_task_spec,
                    recall=lambda request: calls.append(request),
                )
            self.assertEqual(calls, [])

    def test_explicit_bypass_compiles_same_task_without_recall(self):
        calls = []
        result = memory_canary.compile_attempt(
            task=task(),
            profile=profile(),
            control={**enabled_control(), "enabled": False},
            compile_spec=project_context.compile_task_spec,
            recall=lambda request: calls.append(request),
            bypass=True,
            now=lambda: 100.0,
        )
        self.assertEqual(calls, [])
        self.assertEqual(result["candidate"]["taskId"], "task-1")
        self.assertEqual(result["candidate"]["memoryClaims"], [])
        self.assertEqual(result["receipt"]["memoryStatus"], "rolled_back")

    def test_receipts_are_private_append_only_and_content_free(self):
        with tempfile.TemporaryDirectory() as temp:
            first = {
                "schemaVersion": 1,
                "attemptId": "attempt-1",
                "taskId": "task-1",
                "projectSlug": "project-factory",
                "memoryStatus": "ok",
                "embeddedClaimCount": 3,
            }
            memory_canary.append_receipt(temp, first)
            memory_canary.append_receipt(temp, {**first, "memoryStatus": "completed"})
            path = Path(temp) / "memory-canary-events.jsonl"
            values = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(values), 2)
            self.assertEqual(
                memory_canary.latest_receipt(temp, "task-1")["memoryStatus"],
                "completed",
            )
            if os.name != "nt":
                self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

            for forbidden in (
                {"contextQuestion": "secret"},
                {"memoryClaims": [{"content": "secret"}]},
                {"question": "secret"},
                {"claimText": "secret"},
            ):
                with self.subTest(forbidden=forbidden), self.assertRaisesRegex(
                    memory_canary.MemoryCanaryError, "canary_receipt_content_forbidden"
                ):
                    memory_canary.append_receipt(temp, {**first, **forbidden})


if __name__ == "__main__":
    unittest.main(verbosity=2)
