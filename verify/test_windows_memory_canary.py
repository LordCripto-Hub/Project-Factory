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
            "/run/mypeople-secrets/MYPEOPLE_MEMORY_CANARY_TOKEN",
            "finally",
        ):
            self.assertIn(marker, text)
        self.assertNotIn("Write-Output $token", text)
        self.assertNotIn("Write-Host $token", text)
        self.assertNotIn("docker restart mypeople", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
