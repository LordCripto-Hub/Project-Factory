#!/usr/bin/env python3
"""Windows DPAPI and memory activation safety contract."""
from pathlib import Path
import os
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WindowsMemoryContract(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows DPAPI round trip")
    def test_dpapi_round_trip_and_metadata_only_settings(self):
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ROOT / "verify" / "Test-WindowsMemory.ps1"),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertIn("PASS Windows memory DPAPI contract", result.stdout)
        self.assertNotIn("fixture-memory-token", result.stdout)

    def test_module_streams_secret_to_tmpfs_without_arguments_or_logs(self):
        text = (ROOT / "windows" / "MyPeople.Memory.psm1").read_text(
            encoding="utf-8"
        )
        self.assertIn("ProtectedData", text)
        self.assertIn("CurrentUser", text)
        self.assertIn("RedirectStandardInput", text)
        self.assertIn("[Console]::InputEncoding", text)
        self.assertIn("[Text.UTF8Encoding]::new($false)", text)
        self.assertIn("$previousInputEncoding", text)
        self.assertIn("/run/mypeople-secrets/MYPEOPLE_MEMORY_TOKEN", text)
        self.assertIn("docker", text)
        self.assertIn("exec", text)
        self.assertNotIn("Write-Output $secret", text)
        self.assertNotIn("Write-Host $secret", text)
        self.assertNotIn("AUTH_TOKEN=", text)

    def test_entry_points_are_explicit_and_fail_closed(self):
        credential = (
            ROOT / "windows" / "Set-MyPeopleMemoryCredential.ps1"
        ).read_text(encoding="utf-8")
        activation = (
            ROOT / "windows" / "Set-MyPeopleMemoryActivation.ps1"
        ).read_text(encoding="utf-8")
        module = (ROOT / "windows" / "MyPeople.Memory.psm1").read_text(
            encoding="utf-8"
        )
        self.assertIn("[switch]$Generate", credential)
        self.assertIn("AUTH_TOKEN", credential)
        self.assertIn("RedirectStandardInput", credential)
        self.assertIn("[Console]::InputEncoding", credential)
        self.assertIn("[Text.UTF8Encoding]::new($false)", credential)
        self.assertIn("$previousInputEncoding", credential)
        self.assertIn("StandardInput.Write($token)", credential)
        self.assertNotIn("StandardInput.WriteLine($token)", credential)
        self.assertLess(
            credential.index("Save-MyPeopleMemoryCredentialBytes"),
            credential.index("secret put AUTH_TOKEN"),
        )
        self.assertIn("ValidateSet('Enable', 'Disable')", activation)
        self.assertIn("memory-profile", module)
        self.assertIn("Clear-MyPeopleMemoryCredentialInContainer", activation)
        self.assertIn("Persistent memory activation is blocked", activation)
        self.assertIn(
            "https://mypeople-memory-sandbox.labmkt.workers.dev/mcp",
            module,
        )
        self.assertNotIn("Write-Output $token", credential)
        self.assertNotIn("Write-Host $token", credential)

    def test_live_pilot_runner_always_clears_the_tmpfs_credential(self):
        pilot = ROOT / "windows" / "Test-MyPeopleMemoryPilot.ps1"
        self.assertTrue(pilot.is_file())
        text = pilot.read_text(encoding="utf-8")
        self.assertIn("Install-MyPeopleMemoryCredentialInContainer", text)
        self.assertIn("MYPEOPLE_MEMORY_PILOT_E2E=1", text)
        self.assertIn("test_memory_activation_e2e.py", text)
        self.assertIn("finally", text)
        self.assertIn("Clear-MyPeopleMemoryCredentialInContainer", text)
        self.assertIn("test ! -e", text)
        self.assertNotIn("MYPEOPLE_MEMORY_TOKEN=", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
