#!/usr/bin/env python3
"""Safety contract for the disposable full verifier."""
from pathlib import Path
import os
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "verify"


class IsolatedVerifierContract(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_public_shell_entrypoint_only_orchestrates_disposable_compose(self):
        text = self.read("verify/verify.sh")
        self.assertIn("compose.isolated.yml", text)
        self.assertIn("--project-name", text)
        self.assertIn("timeout", text)
        self.assertIn("down --remove-orphans", text)
        self.assertIn("MP_VERIFY_EVIDENCE_DIR", text)
        self.assertNotIn(".config/mypeople/queue.env", text)
        self.assertNotIn('python3 "$VERIFY/core_verify.py"', text)
        suite = self.read("verify/run-suite.sh")
        self.assertIn('python3 "$VERIFY/test_isolated_verifier.py"', suite)

    def test_compose_has_no_route_to_live_state_or_credentials(self):
        text = self.read("verify/compose.isolated.yml")
        required = [
            "network_mode: none",
            "read_only: true",
            "no-new-privileges:true",
            "cap_drop:",
            "- ALL",
            "MP_VERIFY_ISOLATED: \"1\"",
            "source: ${MP_VERIFY_SOURCE:?set MP_VERIFY_SOURCE}",
            "target: /workspace",
            "read_only: true",
            "/home/mp/.config",
            "/home/mp/.codex",
            "/home/mp/.claude",
            "/home/mp/recordings",
            "/home/mp/workspaces",
        ]
        for value in required:
            self.assertIn(value, text)
        forbidden = [
            "container_name:",
            "ports:",
            "devices:",
            "cap_add:",
            "env_file:",
            "/var/run/docker.sock",
            "mypeople-todos",
            "mypeople-run",
            "mypeople-config",
        ]
        for value in forbidden:
            self.assertNotIn(value, text)

    def test_in_container_entrypoints_fail_closed(self):
        if os.name == "nt":
            for script in ("container-entrypoint.sh", "run-suite.sh"):
                text = (VERIFY / script).read_text(encoding="utf-8")
                guard = 'if [[ ${MP_VERIFY_ISOLATED:-} != 1 ]]; then'
                self.assertIn(guard, text)
                self.assertIn("exit 125", text)
                self.assertLess(text.index(guard), text.index("ROOT="))
            return
        bash = shutil.which("bash")
        self.assertTrue(bash, "bash is required for the shell contract")
        for script in ("container-entrypoint.sh", "run-suite.sh"):
            path = VERIFY / script
            result = subprocess.run(
                [bash, str(path)],
                cwd=ROOT,
                env={"PATH": os.environ.get("PATH", "")},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(result.returncode, 125, (script, result.stdout, result.stderr))
            self.assertIn("isolated", (result.stdout + result.stderr).lower())

    def test_core_verifier_requires_isolation_marker_before_loading_runtime(self):
        text = self.read("verify/core_verify.py")
        guard = 'if os.environ.get("MP_VERIFY_ISOLATED") != "1":'
        self.assertIn(guard, text)
        self.assertLess(text.index(guard), text.index("LIVE_ENV = read_env()"))

    def test_entrypoint_creates_only_synthetic_config_and_scrubs_environment(self):
        text = self.read("verify/container-entrypoint.sh")
        self.assertIn("synthetic-verify-secret", text)
        self.assertIn("synthetic-nightwatch-token", text)
        self.assertIn("env -i", text)
        for name in (
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "CODEX_API_KEY",
            "GH_TOKEN",
            "TAILSCALE_AUTHKEY",
            "MYPEOPLE_MEMORY_TOKEN",
        ):
            self.assertIn(name, text)
        self.assertNotIn('cp -a "$SOURCE/." "$ROOT/"', text)
        for excluded in (
            "--exclude=.env",
            "--exclude=run",
            "--exclude=status",
            "--exclude=todos",
            "--exclude=recordings",
            "--exclude=.codex",
            "--exclude=.claude",
        ):
            self.assertIn(excluded, text)

    def test_smoke_override_requires_an_explicit_host_launcher_mode(self):
        compose = self.read("verify/compose.isolated.yml")
        entrypoint = self.read("verify/container-entrypoint.sh")
        windows = self.read("verify/Invoke-IsolatedVerify.ps1")
        shell = self.read("verify/verify.sh")
        for text in (compose, entrypoint, windows, shell):
            self.assertNotIn("MP_VERIFY_SUITE_COMMAND", text)
        self.assertIn("MP_VERIFY_MODE: ${MP_VERIFY_MODE:?set MP_VERIFY_MODE}", compose)
        self.assertIn("MP_VERIFY_SMOKE_COMMAND: ${MP_VERIFY_SMOKE_COMMAND:-}", compose)
        self.assertIn("[string]$SmokeCommand", windows)
        self.assertIn("MP_VERIFY_MODE = 'full'", windows)
        self.assertIn("--smoke-command", shell)
        self.assertIn('case "${MP_VERIFY_MODE:-}" in', entrypoint)
        self.assertIn("full)", entrypoint)
        self.assertIn("smoke)", entrypoint)

    def test_core_owner_fixtures_use_a_synthetic_memory_disabled_project(self):
        text = self.read("verify/core_verify.py")
        self.assertIn('SANDBOX_PROJECT_SLUG = "verify-project"', text)
        self.assertIn('"PROJECT_PROFILES_DIR": str(self.project_profiles)', text)
        self.assertIn('"memory": {"enabled": False', text)
        self.assertIn('"projectSlug": project_slug', text)
        self.assertIn(
            'add_sandbox_task("owner fixture", test=True, project_slug=SANDBOX_PROJECT_SLUG)',
            text,
        )
        self.assertIn(
            'add_sandbox_task("owner browser fixture", test=True, project_slug=SANDBOX_PROJECT_SLUG)',
            text,
        )

    def test_windows_entrypoint_is_bounded_and_preserves_failure_evidence(self):
        text = self.read("verify/Invoke-IsolatedVerify.ps1")
        required = [
            "[int]$TimeoutSeconds",
            "mypeople-verify-",
            "--project-name",
            "Wait-Job",
            "124",
            "125",
            "down",
            "--remove-orphans",
            "Evidence retained",
        ]
        for value in required:
            self.assertIn(value, text)
        self.assertNotIn("queue.env", text)
        self.assertNotIn("docker exec mypeople", text)
        self.assertIn("Get-Command docker -ErrorAction SilentlyContinue", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
