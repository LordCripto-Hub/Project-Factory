from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from memory_bench.history_fixture import load_history_fixture
from memory_bench.taskspec_gate import run_taskspec_gate, write_taskspec_evidence


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "datasets" / "project-factory-history-039a62988625"
LOCK = ROOT / "docker" / "history-hybrid-039a62988625.dataset-lock.json"


class FakeTaskSpec(dict):
    def __init__(self, value, metadata):
        super().__init__(value)
        self.memory_metadata = metadata


class FakeCompiler:
    def __init__(self, relevant_query):
        self.relevant_query = relevant_query
        self.calls = 0

    def __call__(self, task, profile, now):
        question = task["contextQuestion"]
        enabled = profile["memory"]["enabled"]
        claims = []
        status = "not_requested" if not question else "disabled"
        if enabled and question:
            self.calls += 1
            status = "ok"
            if question == self.relevant_query:
                claims = [{
                    "id": "commit-64927751185b",
                    "projectSlug": "project-factory",
                    "content": "Document bounded external memory MCP pilot",
                    "sourceUri": (
                        "git+repo://LordCripto-Hub/Project-Factory@"
                        "64927751185b16fefdca9254a1dc2d7653ff6614#commit"
                    ),
                    "sourceType": "commit",
                    "status": "canonical",
                }]
        value = {
            "schemaVersion": 1,
            "taskId": task["id"],
            "projectSlug": task["projectSlug"],
            "profileRevision": profile["revision"],
            "objective": task["text"],
            "acceptanceCriteria": task["doneCondition"],
            "repository": profile["repository"],
            "workingDirectory": profile["workingDirectory"],
            "contextFiles": profile["contextFiles"],
            "verificationCommands": profile["verificationCommands"],
            "allowedActions": profile["allowedActions"],
            "forbiddenActions": profile["forbiddenActions"],
            "evidencePolicy": task["evidencePolicy"],
            "routingHints": {},
            "memoryQuestion": question,
            "memoryClaims": claims,
            "memoryStatus": status,
            "compiledAt": now(),
        }
        return FakeTaskSpec(value, {
            "requestedClaimCount": 3 if enabled and question else 0,
            "returnedClaimCount": len(claims),
            "embeddedClaimCount": len(claims),
            "responseCharacters": sum(len(item["content"]) for item in claims),
            "aiUsage": "not_measured",
        })


class TaskSpecGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loaded = load_history_fixture(DATASET, LOCK)
        cls.question = next(
            item
            for item in cls.loaded.fixture.questions
            if item.question_id == "hist-exact-003"
        )

    def execute(self):
        compiler = FakeCompiler(self.question.query)
        return run_taskspec_gate(
            self.loaded,
            compiler=compiler,
            server_url="https://127.0.0.1:18443/mcp",
            ledger_count=lambda: compiler.calls,
            fixed_time=1784473171,
        )

    def test_cases_preserve_local_contract_and_bound_memory(self):
        result = self.execute()
        self.assertTrue(all(result["promotion_gates"].values()))
        self.assertTrue(result["promotion_gates"]["relevant_gold_hit"])
        self.assertEqual(result["cases"]["relevant"]["claim_count"], 1)
        self.assertEqual(result["cases"]["irrelevant"]["claim_count"], 0)
        self.assertEqual(result["cases"]["no_question"]["memory_status"], "not_requested")
        self.assertEqual(result["gateway_request_count"], 2)
        self.assertEqual(result["actual_provider_tokens"], "not_measured")
        self.assertEqual(
            result["cases"]["relevant"]["estimated_tokens_formula"],
            "ceil(canonical_json_characters/4)",
        )
        self.assertNotIn("compiledAt", json.dumps(result))

    def test_evidence_is_logically_and_byte_deterministic(self):
        first = self.execute()
        second = self.execute()
        self.assertEqual(first, second)
        with tempfile.TemporaryDirectory() as temp:
            first_output = Path(temp) / "first"
            second_output = Path(temp) / "second"
            write_taskspec_evidence(first, first_output)
            write_taskspec_evidence(second, second_output)
            for name in (
                "taskspec-memory-result.json",
                "taskspec-memory-report.md",
            ):
                self.assertEqual(
                    (first_output / name).read_bytes(),
                    (second_output / name).read_bytes(),
                )
                evidence = (first_output / name).read_text(encoding="utf-8")
                self.assertNotIn("/home/mp/", evidence)
                self.assertNotIn("C:\\Users\\", evidence)
            report = (
                first_output / "taskspec-memory-report.md"
            ).read_text(encoding="utf-8")
            self.assertIn(
                (
                    f"Estimated memory delta: "
                    f"{first['memory_delta']['characters']} characters / "
                    f"{first['memory_delta']['estimated_tokens']} tokens"
                ),
                report,
            )


if __name__ == "__main__":
    unittest.main()
