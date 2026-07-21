#!/usr/bin/env python3
"""Synthetic end-to-end contract for the reversible live memory canary."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

memory_canary = load("memory_canary_e2e", ROOT / "bin" / "memory_canary.py")
project_context = load("project_context_e2e", ROOT / "bin" / "project_context.py")

def profile():
    return {
        "schemaVersion": 1, "revision": 9, "slug": "project-factory",
        "repository": "https://github.com/example/project-factory.git",
        "workingDirectory": "/workspace/project-factory",
        "allowedBranches": ["main"], "contextFiles": ["README.md", "AGENTS.md"],
        "verificationCommands": ["python3 verify/test_memory_canary_e2e.py"],
        "allowedActions": ["read", "edit", "test"],
        "forbiddenActions": ["deploy", "push", "delete"],
        "limits": {"contextChars": 8000, "memoryTopK": 3, "memoryHops": 0, "memoryTimeoutSeconds": 8},
        "memory": {"enabled": True, "serverUrl": "https://memory.example.invalid/mcp", "credentialRef": "env://MYPEOPLE_MEMORY_TOKEN"},
    }

def task(*, canary=True, project="project-factory"):
    return {
        "id": "synthetic-card-1", "text": "Verify the bounded memory canary",
        "doneCondition": "The synthetic contract passes", "projectSlug": project,
        "contextQuestion": "Which verified constraints apply?", "memoryCanary": canary,
        "evidencePolicy": "required",
    }

def response():
    claims = [{
        "id": f"claim-{index}", "projectSlug": "project-factory",
        "content": f"Grounded public constraint {index}",
        "sourceUri": f"git://project-factory/commit-{index}",
        "sourceType": "git_commit", "status": "verified",
    } for index in range(1, 4)]
    return {"claims": claims, "truncated": False,
            "responseChars": sum(len(claim["content"]) for claim in claims),
            "aiUsage": "not_measured"}

class MemoryCanaryE2E(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = Path(self.temp.name)
        memory_canary.set_control(self.runtime, enabled=True, now=lambda: 10.0)
        self.gateway_calls, self.workers, self.taskspecs = [], [], []

    def tearDown(self):
        self.temp.cleanup()

    def recall(self, request):
        self.gateway_calls.append(request)
        return response()

    def compile_and_spawn(self, card, *, bypass=False, recall=None):
        result = memory_canary.compile_attempt(
            task=card, profile=profile(), control=memory_canary.load_control(self.runtime),
            compile_spec=project_context.compile_task_spec,
            recall=self.recall if recall is None else recall, bypass=bypass, now=lambda: 20.0,
        )
        memory_canary.append_receipt(self.runtime, result["receipt"])
        self.taskspecs.append(result["candidate"])
        self.workers.append(card["id"])
        return result

    def test_positive_non_canary_cross_project_and_timeout_are_isolated(self):
        positive = self.compile_and_spawn(task())
        self.assertLessEqual(len(positive["candidate"]["memoryClaims"]), 3)
        self.assertTrue(all(claim["sourceUri"].startswith("git://project-factory/") and claim["status"] == "verified" for claim in positive["candidate"]["memoryClaims"]))
        before = len(self.gateway_calls)
        plain = self.compile_and_spawn(task(canary=False))
        self.assertEqual(len(self.gateway_calls), before)
        self.assertEqual(plain["candidate"]["memoryClaims"], [])
        for card, recall, code in (
            (task(project="another-project"), self.recall, "canary_project_denied"),
            (task(), lambda _request: (_ for _ in ()).throw(project_context.MemoryError("timeout")), "memory_timeout"),
        ):
            worker_count, spec_count, calls_before = len(self.workers), len(self.taskspecs), len(self.gateway_calls)
            with self.subTest(code=code), self.assertRaisesRegex(Exception, code):
                self.compile_and_spawn(card, recall=recall)
            self.assertEqual(len(self.workers), worker_count)
            self.assertEqual(len(self.taskspecs), spec_count)
            if code == "canary_project_denied":
                self.assertEqual(len(self.gateway_calls), calls_before)

    def test_same_card_bypass_disable_and_receipt_are_reversible_and_clean(self):
        active = self.compile_and_spawn(task())
        receipt = active["receipt"]
        self.assertEqual(receipt["memoryProviderUsage"], "not_measured")
        self.assertIsInstance(receipt["memoryDeltaTokensEstimated"], int)
        self.assertGreater(receipt["memoryDeltaTokensEstimated"], 0)
        completion = memory_canary.complete_attempt(
            self.runtime,
            attempt_id=receipt["attemptId"], task_id=task()["id"],
            runtime_record={"backend": "codex", "session_id": "session-1234567890", "model": "gpt-5.6-luna", "provider_profile": "shared", "recovery_attempts": 0},
            outcome="review", evidence_count=1,
            usage_before={"provider": "codex", "sessionId": "session-1234567890", "usage": {"inputTokens": 100, "outputTokens": 20}},
            usage_after={"provider": "codex", "sessionId": "session-1234567890", "usage": {"inputTokens": 140, "outputTokens": 30}},
            completed_at=24.0,
        )
        self.assertEqual(completion["providerUsage"], {"inputTokens": 40, "outputTokens": 10})
        projection = memory_canary.receipt_projection(self.runtime, task()["id"])
        self.assertEqual(projection["memoryDeltaTokensEstimated"], receipt["memoryDeltaTokensEstimated"])
        self.assertEqual(projection["providerUsage"], completion["providerUsage"])
        bypass = self.compile_and_spawn(task(), bypass=True)
        self.assertEqual(bypass["candidate"]["taskId"], task()["id"])
        self.assertEqual(bypass["candidate"]["memoryClaims"], [])
        self.assertEqual(bypass["receipt"]["memoryStatus"], "rolled_back")
        disabled = memory_canary.set_control(self.runtime, enabled=False, now=lambda: 30.0)
        self.assertFalse(disabled["enabled"])
        with self.assertRaisesRegex(memory_canary.MemoryCanaryError, "canary_disabled"):
            self.compile_and_spawn(task())
        ledger = (self.runtime / memory_canary.RECEIPT_NAME).read_text(encoding="utf-8")
        for forbidden in ("Which verified constraints apply?", "Grounded public constraint", "MYPEOPLE_MEMORY_TOKEN", "memory.example.invalid"):
            self.assertNotIn(forbidden, ledger)

    def test_default_entrypoints_never_activate_live_canary(self):
        checked = [ROOT / "install.sh"]
        checked.extend((ROOT / "docker").rglob("*"))
        checked.extend(path for path in (ROOT / "windows").rglob("*") if path.name != "Start-MyPeopleMemoryCanary.ps1")
        for path in checked:
            if path.is_file():
                text = path.read_text(encoding="utf-8", errors="ignore")
                self.assertNotIn("Start-MyPeopleMemoryCanary", text, path)
                self.assertNotIn("compose.live-canary.yml", text, path)

    def test_isolated_suite_registers_every_canary_contract_once(self):
        suite = (ROOT / "verify" / "run-suite.sh").read_text(encoding="utf-8")
        for name in (
            "test_memory_canary_control.py",
            "test_memory_canary_runtime.py",
            "test_memory_canary_telemetry.py",
            "test_memory_canary_sidecar.py",
            "test_windows_memory_canary.py",
            "test_memory_canary_priorities.py",
            "test_memory_canary_e2e.py",
        ):
            self.assertEqual(suite.count(name), 1, name)

    def test_launcher_cleanup_removes_sidecar_network_and_token(self):
        launcher = (ROOT / "windows" / "Start-MyPeopleMemoryCanary.ps1").read_text(encoding="utf-8")
        disable = launcher[launcher.index("function Disable-Canary"):launcher.index("if ($Action -eq 'Status')")]
        for marker in ("memory-canary disable", "memory-profile disable", "rm -rf $secretDirectory", "docker network disconnect", "down --volumes"):
            self.assertIn(marker, disable)

    def test_real_disposable_docker_lifecycle_when_requested(self):
        image = os.environ.get("MYPEOPLE_MEMORY_CANARY_E2E_IMAGE", "").strip()
        if not image:
            self.skipTest("set MYPEOPLE_MEMORY_CANARY_E2E_IMAGE for the host Docker lifecycle")
        container = f"memory-canary-e2e-main-{os.getpid()}"
        launcher = ROOT / "windows" / "Start-MyPeopleMemoryCanary.ps1"
        source = ROOT / "experiments" / "memory-gate-b"
        dataset = source / "datasets" / "project-factory-history-80dce6f86632"
        run = lambda arguments, check=True: subprocess.run(
            arguments, cwd=ROOT, capture_output=True, text=True,
            timeout=180, check=check,
        )
        for resource in ("memory-gate-b-live-canary-memory-gate-b-1", "mypeople-memory-canary-internal", "mypeople-memory-canary-secret"):
            found = run(["docker", "inspect", resource], check=False)
            self.assertNotEqual(found.returncode, 0, f"existing canary resource: {resource}")
        try:
            port_args = []
            for port in (7681, 7682, 7699, 9900, 9933):
                port_args.extend(["-p", f"127.0.0.1::{port}"])
            run(["docker", "run", "-d", "--network", "bridge", *port_args, "--name", container, "--entrypoint", "sleep", image, "infinity"])
            fixture = self.runtime / "project-factory.json"
            fixture.write_text(json.dumps(profile()), encoding="utf-8")
            run(["docker", "exec", container, "mkdir", "-p", "/home/mp/mypeople/run/project-profiles"])
            run(["docker", "cp", str(fixture), f"{container}:/home/mp/mypeople/run/project-profiles/project-factory.json"])
            run(["docker", "exec", "--user", "0:0", container, "chown", "1000:1000", "/home/mp/mypeople/run/project-profiles/project-factory.json"])
            base = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(launcher)]
            run(base + ["-Action", "Enable", "-MemorySource", str(source), "-Dataset", str(dataset), "-Image", image, "-Container", container])
            status = run(base + ["-Action", "Status", "-Container", container])
            self.assertIn("running", status.stdout.lower())
            self.assertEqual(run(["docker", "exec", container, "test", "-s", "/run/mypeople-secrets/MYPEOPLE_MEMORY_CANARY_TOKEN"], check=False).returncode, 0)
            run(base + ["-Action", "Disable", "-Container", container])
            self.assertNotEqual(run(["docker", "inspect", "memory-gate-b-live-canary-memory-gate-b-1"], check=False).returncode, 0)
            self.assertNotEqual(run(["docker", "network", "inspect", "mypeople-memory-canary-internal"], check=False).returncode, 0)
            self.assertNotEqual(run(["docker", "volume", "inspect", "mypeople-memory-canary-secret"], check=False).returncode, 0)
            self.assertNotEqual(run(["docker", "exec", container, "test", "-e", "/run/mypeople-secrets/MYPEOPLE_MEMORY_CANARY_TOKEN"], check=False).returncode, 0)
        finally:
            run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(launcher), "-Action", "Disable", "-Container", container], check=False)
            run(["docker", "rm", "-f", container], check=False)

if __name__ == "__main__":
    unittest.main(verbosity=2)
