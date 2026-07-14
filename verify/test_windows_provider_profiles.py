#!/usr/bin/env python3
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WindowsProviderProfileContract(unittest.TestCase):
    def test_module_uses_local_app_data_and_restricts_acl(self):
        text = (
            ROOT / "windows" / "MyPeople.ProviderProfiles.psm1"
        ).read_text(encoding="utf-8")
        self.assertIn("LOCALAPPDATA", text)
        self.assertIn("SetAccessRuleProtection", text)
        self.assertIn("FileSystemAccessRule", text)
        self.assertIn("Get-MyPeopleProviderAdapter", text)
        for operation in (
            "InspectSource",
            "SaveProfile",
            "ActivateProfile",
            "ValidateRuntime",
            "RuntimeEnvironment",
            "LaunchArguments",
            "RestorePrevious",
        ):
            self.assertIn(operation, text)
        self.assertNotIn("Write-Host $credential", text)
        self.assertNotRegex(text, r"(?m)\\\s*$")
        self.assertIn("Start-Process", text)
        self.assertIn("WaitForExit", text)
        self.assertIn("'exec'", text)
        self.assertIn("'--ephemeral'", text)
        self.assertIn("$probe = 'PROFILE_OK'", text)
        self.assertGreaterEqual(text.count("& docker exec -u 0 $Container chown mp:mp"), 2)
        self.assertNotIn("& codex login status *> $null", text)
        initialize = text[
            text.index("function Initialize-MyPeopleProfileStore"):
            text.index("function Get-MyPeopleProfilePath")
        ]
        self.assertIn("[IO.Directory]::CreateDirectory($script:StoreRoot)", initialize)
        self.assertNotIn("$script:StoreRoot,", initialize)

    def test_save_script_validates_codex_without_printing_auth(self):
        text = (
            ROOT / "windows" / "Save-MyPeopleProviderProfile.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("codex login status", text)
        self.assertIn(".codex", text)
        self.assertNotIn("Get-Content", text)

    def test_switch_script_orders_transaction_and_rollback(self):
        text = (
            ROOT / "windows" / "Switch-MyPeopleProviderProfile.ps1"
        ).read_text(encoding="utf-8")
        preflight = text.index("Get-MyPeopleProviderProfiles")
        prepare = text.index("provider-session prepare")
        stop = text.index("provider-session stop")
        validate = text.index("& $adapter.ValidateRuntime")
        revive = text.index("provider-session revive")
        verify = text.index("provider-session verify")
        commit = text.index("provider-session commit")
        self.assertLess(preflight, prepare)
        self.assertLess(prepare, stop)
        self.assertLess(stop, validate)
        self.assertLess(validate, revive)
        self.assertLess(revive, verify)
        self.assertLess(verify, commit)
        self.assertIn("provider-session rollback", text)
        self.assertIn("$failedPhase", text)
        self.assertIn("[string]$Agent", text)
        self.assertIn("[switch]$InheritGlobal", text)
        self.assertIn("$newAgents.Remove($Agent)", text)
        self.assertIn("[int]$TimeoutSeconds", text)
        self.assertIn("$adapter = Get-MyPeopleProviderAdapter", text)
        self.assertNotRegex(text, r"(?m)\\\s*$")

    def test_status_script_reports_only_non_secret_metadata(self):
        text = (
            ROOT / "windows" / "Get-MyPeopleProviderStatus.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("Get-MyPeopleProviderBindings", text)
        self.assertIn("validation", text.lower())
        self.assertIn("not-run", text)
        self.assertNotIn("ValidateRuntime", text)
        self.assertNotIn("auth.json", text)
        self.assertNotIn("Get-Content", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
