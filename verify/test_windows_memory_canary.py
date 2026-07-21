#!/usr/bin/env python3
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WindowsMemoryCanaryContract(unittest.TestCase):
    def test_launcher_has_bounded_reversible_lifecycle(self):
        text = (ROOT / "windows/Start-MyPeopleMemoryCanary.ps1").read_text(encoding="utf-8")
        for marker in (
            "ValidateSet('Enable', 'Disable', 'Status')",
            "memory-gate-b-live-canary",
            "docker inspect",
            "docker compose",
            "docker network connect",
            "docker network disconnect",
            "/run/mypeople-secrets",
            "finally",
            "Set-ComposeParseDefaults",
            "memory-canary-cleanup-only",
            "Memory Gate B cleanup incomplete:",
            "$failures.Add('runtime-control')",
            "$failures.Add('project-profile')",
            "$failures.Add('main-container-token')",
            "$failures.Add('network-disconnect')",
            "$failures.Add('compose-resources')",
            "RandomNumberGenerator]::Create()",
            ".GetBytes($tokenBytes)",
            "[BitConverter]::ToString($tokenBytes)",
            "'--user','0:0'",
            "chown 1000:1000",
            "docker exec --user 0:0",
            "mkdir -p $secretDirectory",
        ):
            self.assertIn(marker, text)
        self.assertNotIn("Write-Output $token", text)
        self.assertNotIn("Write-Host $token", text)
        self.assertNotIn("docker restart mypeople", text)
        self.assertNotIn("RandomNumberGenerator]::Fill", text)
        self.assertNotIn("[Convert]::ToHexString", text)
        self.assertNotIn("finally { Write-Output 'Memory Gate B canary disabled.' }", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
