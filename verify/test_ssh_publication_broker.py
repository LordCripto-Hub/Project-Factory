#!/usr/bin/env python3
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "windows" / "Invoke-MyPeopleSshPublication.ps1").read_text(encoding="utf-8")


class SshPublicationBrokerContract(unittest.TestCase):
    def test_broker_uses_closed_ssh_and_docker_bridge(self):
        self.assertIn("ValidatePattern('^[0-9a-f]{24}$')", SCRIPT)
        self.assertIn("git@github.com:$($preflight.repositorySlug).git", SCRIPT)
        self.assertIn("refs/heads/$($preflight.headBranch)", SCRIPT)
        self.assertIn("publish-branch-complete", SCRIPT)
        self.assertIn("publish-pr-complete", SCRIPT)
        self.assertIn("publish-checks", SCRIPT)
        self.assertIn("publish-merge-complete", SCRIPT)
        self.assertIn("--match-head-commit", SCRIPT)
        self.assertIn("--delete-branch=false", SCRIPT)
        self.assertIn("GIT_TERMINAL_PROMPT = '0'", SCRIPT)
        self.assertNotIn("--force", SCRIPT)
        self.assertNotIn("StrictHostKeyChecking=no", SCRIPT)
        self.assertNotIn("Invoke-Expression", SCRIPT)
        self.assertNotIn("GH_TOKEN", SCRIPT)

    def test_broker_cleans_transient_material_and_fail_closes_bindings(self):
        self.assertIn("Remove-Item -LiteralPath $tempRoot -Recurse -Force", SCRIPT)
        self.assertIn("github_pr_binding_mismatch", SCRIPT)
        self.assertIn("required_checks_failed", SCRIPT)
        self.assertIn("required_checks_timeout", SCRIPT)
        self.assertIn("$pr.headRefOid -ne $preflight.commit", SCRIPT)
        self.assertIn("$pr.baseRefName -ne 'main'", SCRIPT)
        self.assertIn("Assert-SafeSlug", SCRIPT)
        self.assertIn("Assert-SafeBranch", SCRIPT)


if __name__ == "__main__":
    unittest.main()
