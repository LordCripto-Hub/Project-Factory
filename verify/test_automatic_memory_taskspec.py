#!/usr/bin/env python3
"""TaskSpec contracts for automatic bounded memory and typed fail-open."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "project_context_automatic", ROOT / "bin" / "project_context.py"
)
project_context = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(project_context)


def profile(enabled=True):
    return {
        "schemaVersion": 1,
        "revision": 7,
        "slug": "project-factory",
        "repository": "https://github.com/LordCripto-Hub/Project-Factory.git",
        "workingDirectory": "/workspace/project-factory",
        "allowedBranches": ["main"],
        "contextFiles": ["README.md", "AGENTS.md"],
        "verificationCommands": ["python3 verify/test_automatic_memory_taskspec.py"],
        "allowedActions": ["read", "edit", "test"],
        "forbiddenActions": ["deploy", "push", "delete"],
        "limits": {
            "contextChars": 6000,
            "memoryTopK": 3,
            "memoryHops": 0,
            "memoryTimeoutSeconds": 2,
        },
        "memory": {
            "enabled": enabled,
            "serverUrl": "https://memory.example.invalid/mcp",
            "credentialRef": "env://MYPEOPLE_MEMORY_TOKEN",
        },
    }


def task(**overrides):
    value = {
        "id": "task-1",
        "projectSlug": "project-factory",
        "text": "Repair publisher continuity",
        "doneCondition": "Preserve ownership",
        "contextQuestion": "",
        "evidencePolicy": "required",
    }
    value.update(overrides)
    return value


def grounded_claim(name="commit-a"):
    return {
        "id": name,
        "projectSlug": "project-factory",
        "content": "Verified publisher rule",
        "sourceUri": f"git+repo://Project-Factory#{name}",
        "sourceType": "commit",
        "status": "canonical",
    }


def applied_response():
    return {
        "status": "memory_applied",
        "selectedLevel": "fast",
        "levelsAttempted": ["fast"],
        "claims": [grounded_claim()],
        "elapsedMilliseconds": 4,
        "examinedCount": 1,
        "returnedCount": 1,
        "estimatedTokens": 40,
        "provenanceComplete": True,
        "reasonCode": None,
        "aiUsage": "not_measured",
    }


class AutomaticMemoryTaskSpecTests(unittest.TestCase):
    def test_live_gateway_boundary_preserves_typed_automatic_metadata(self):
        response = applied_response()

        def runner(*_args, **_kwargs):
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({
                    "ok": True,
                    "claims": response["claims"],
                    "truncated": False,
                    "responseChars": 180,
                    **{key: response[key] for key in (
                        "status", "selectedLevel", "levelsAttempted",
                        "elapsedMilliseconds", "examinedCount", "returnedCount",
                        "estimatedTokens", "provenanceComplete", "reasonCode",
                        "aiUsage",
                    )},
                }),
            )

        previous = os.environ.get("MYPEOPLE_MEMORY_TOKEN")
        os.environ["MYPEOPLE_MEMORY_TOKEN"] = "synthetic-test-token"
        try:
            result = project_context.call_memory_gateway(
                profile(), "Repair publisher continuity", runner=runner
            )
        finally:
            if previous is None:
                os.environ.pop("MYPEOPLE_MEMORY_TOKEN", None)
            else:
                os.environ["MYPEOPLE_MEMORY_TOKEN"] = previous

        self.assertEqual(result["status"], "memory_applied")
        self.assertEqual(result["selectedLevel"], "fast")
        self.assertEqual(result["levelsAttempted"], ["fast"])
        self.assertEqual(result["estimatedTokens"], 40)

    def test_automatic_mode_uses_derived_query_without_explicit_question(self):
        requests = []
        spec = project_context.compile_task_spec(
            task(), profile(),
            recall=lambda request: requests.append(request) or applied_response(),
            memory_query="Repair publisher continuity | Preserve ownership",
            memory_mode="automatic",
            now=lambda: 100,
        )
        self.assertEqual(len(requests), 1)
        self.assertEqual(
            requests[0]["question"],
            "Repair publisher continuity | Preserve ownership",
        )
        self.assertEqual(spec["memoryStatus"], "memory_applied")
        self.assertEqual(len(spec["memoryClaims"]), 1)
        self.assertEqual(spec.memory_metadata["selectedLevel"], "fast")
        self.assertEqual(spec.memory_metadata["estimatedTokens"], 40)

    def test_automatic_transport_failure_is_typed_and_does_not_block(self):
        def unavailable(_request):
            raise project_context.MemoryError("timeout")
        spec = project_context.compile_task_spec(
            task(), profile(), recall=unavailable,
            memory_query="Repair publisher continuity",
            memory_mode="automatic",
        )
        self.assertEqual(spec["memoryClaims"], [])
        self.assertEqual(spec["memoryStatus"], "memory_unavailable")
        self.assertEqual(spec.memory_metadata["reasonCode"], "timeout")

    def test_typed_empty_and_invalid_outcomes_fail_open(self):
        for status in (
            "insufficient_evidence", "memory_unavailable",
            "memory_budget_exceeded", "memory_invalid_response",
        ):
            response = applied_response()
            response.update({
                "status": status,
                "selectedLevel": None,
                "claims": [],
                "returnedCount": 0,
                "estimatedTokens": 0,
                "provenanceComplete": False,
                "reasonCode": "typed_empty_outcome",
            })
            spec = project_context.compile_task_spec(
                task(), profile(), recall=lambda _request, value=response: value,
                memory_query="Repair publisher continuity",
                memory_mode="automatic",
            )
            with self.subTest(status=status):
                self.assertEqual(spec["memoryStatus"], status)
                self.assertEqual(spec["memoryClaims"], [])

    def test_off_mode_never_calls_recall_or_mutates_task(self):
        original = task(contextQuestion="Explicit diagnostic question")
        before = dict(original)
        spec = project_context.compile_task_spec(
            original, profile(),
            recall=lambda _request: self.fail("recall must not run"),
            memory_mode="off",
        )
        self.assertEqual(spec["memoryStatus"], "not_requested")
        self.assertEqual(original, before)

    def test_automatic_response_must_respect_claim_and_token_bounds(self):
        for mutation in (
            {"claims": [grounded_claim(str(index)) for index in range(4)]},
            {"estimatedTokens": 301},
            {"provenanceComplete": False},
        ):
            response = applied_response()
            response.update(mutation)
            spec = project_context.compile_task_spec(
                task(), profile(), recall=lambda _request, value=response: value,
                memory_query="Repair publisher continuity",
                memory_mode="automatic",
            )
            with self.subTest(mutation=mutation):
                self.assertEqual(spec["memoryStatus"], "memory_invalid_response")
                self.assertEqual(spec["memoryClaims"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
