#!/usr/bin/env python3
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "windows" / "Start-MyPeopleMemoryComparison.ps1"


class WindowsMemoryComparisonContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SCRIPT.read_text(encoding="utf-8") if SCRIPT.exists() else ""

    def test_launcher_exists_and_defaults_to_safe_preflight(self):
        self.assertTrue(SCRIPT.is_file(), "Windows comparison launcher is missing")
        self.assertRegex(self.text, r"\[ValidateSet\([^]]*'Preflight'[^]]*'Paired'[^]]*\)\]")
        self.assertRegex(self.text, r"\$Action\s*=\s*'Preflight'")
        self.assertIn("[switch]$Execute", self.text)
        self.assertIn("[switch]$ConfirmLiveRun", self.text)
        self.assertIn("$ConfirmedRunId", self.text)
        self.assertIn("execution_confirmation_mismatch", self.text)

    def test_preflight_binds_runtime_dataset_fixture_and_offline_receipt(self):
        for marker in (
            "Get-ContainerSnapshot",
            "RestartCount",
            "MYPEOPLE_MEMORY_COMPARISON_ENABLED",
            "project-factory-history-039a62988625",
            "039a62988625369f3f86c055cd476b0080395daa",
            "comparison-offline-039a62988625.json",
            "fixture_sha256",
            "offline_digest",
            "offline_qualified",
            "git rev-parse HEAD",
            "workspace_source_mismatch",
            "git status --porcelain",
            "workspace_dirty",
            "provider_unavailable",
            "comparison_resources_present",
            "memory_sidecar_unavailable",
            "memory-comparison",
            "http://127.0.0.1:9933/",
            "http://127.0.0.1:9900/",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.text)

    def test_exact_counterbalanced_schedule_uses_fresh_luna_workers(self):
        for alias, first, second in (
            ("cmp-exact-01", "baseline", "memory"),
            ("cmp-temporal-01", "memory", "baseline"),
            ("cmp-contradiction-01", "baseline", "memory"),
        ):
            pattern = rf"alias\s*=\s*'{alias}'.*?arms\s*=\s*@\('{first}','{second}'\)"
            with self.subTest(alias=alias):
                self.assertRegex(self.text, pattern)
        self.assertIn("gpt-5.6-luna", self.text)
        self.assertIn("mp spawn", self.text)
        self.assertIn("--backend codex", self.text)
        self.assertIn("--owner-task", self.text)
        self.assertIn("--without-memory", self.text)
        self.assertIn("[guid]::NewGuid()", self.text)
        self.assertIn("questions.jsonl", self.text)
        self.assertIn("question_id", self.text)
        self.assertIn(".query", self.text)

    def test_waits_for_closed_result_and_records_honest_metrics(self):
        for marker in (
            "result-envelope.json",
            "score_receipt",
            "wall_time_ms",
            "retrieval_latency_ms",
            "memory_context_tokens_estimated",
            "provider_tokens",
            "not_measured",
            "Wait-ComparisonResult",
            "result_timeout",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.text)
        self.assertNotIn("fabricated_result", self.text.lower())

    def test_cleanup_and_fail_closed_paths_are_explicit(self):
        for marker in (
            "mp kill",
            "operator-request",
            "'op' = 'del'",
            "Remove-Item",
            "worker_absent",
            "card_absent",
            "conversation_retired",
            "temp_artifacts_absent",
            "memory-comparison abort",
            "wrong_project",
            "provider_error",
            "restart_detected",
            "score_refused",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.text)

    def test_launcher_has_no_publication_or_global_memory_mutation(self):
        lowered = self.text.lower()
        for forbidden in (
            "git push",
            "git merge",
            "gh pr",
            "mp publish",
            "memory-canary enable",
            "memory-profile enable",
            "write-memory",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, lowered)


if __name__ == "__main__":
    unittest.main(verbosity=2)
