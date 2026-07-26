from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "windows" / "Invoke-IsolatedTaskSpecMemory.ps1"


class TaskSpecWindowsLauncherTests(unittest.TestCase):
    def test_launcher_binds_final_identity_and_sanitized_receipt(self):
        source = LAUNCHER.read_text(encoding="utf-8-sig")
        self.assertIn("project-factory-history-80dce6f86632", source)
        self.assertIn("80dce6f866329b79061bb1ed6b0594f9fdf2dd45", source)
        self.assertIn("LordCripto-Hub/Project-Factory", source)
        self.assertIn("taskspec-memory-result.json", source)
        self.assertIn("container-receipt.json", source)
        self.assertIn("Get-FileHash", source)

    def test_launcher_times_out_cleans_up_and_never_deletes_volumes(self):
        source = LAUNCHER.read_text(encoding="utf-8-sig")
        self.assertIn("Start-Job", source)
        self.assertIn("Wait-Job", source)
        self.assertIn("$ExitCode = 124", source)
        self.assertIn("finally", source)
        self.assertIn("down --remove-orphans", source)
        self.assertNotIn("down -v", source)
        self.assertNotIn("Remove-Item", source)

    def test_launcher_proves_live_mypeople_is_unchanged(self):
        source = LAUNCHER.read_text(encoding="utf-8-sig")
        self.assertGreaterEqual(source.count("Get-LiveMyPeopleState"), 3)
        self.assertIn("live_mypeople_before", source)
        self.assertIn("live_mypeople_after", source)
        self.assertIn("live_mypeople_unchanged", source)
        self.assertIn("cleanup_verified", source)

    def test_powershell_error_handling_preserves_primary_result(self):
        source = LAUNCHER.read_text(encoding="utf-8-sig")
        self.assertNotRegex(
            source.split("param(", 1)[1].split(")", 1)[0],
            r"\$PSScriptRoot",
        )
        self.assertIn("$ImageInspectExitCode = $LASTEXITCODE", source)
        self.assertIn("$PrimaryExitCode = $ExitCode", source)

    def test_launcher_rejects_an_empty_promotion_gate_set(self):
        source = LAUNCHER.read_text(encoding="utf-8-sig")
        self.assertIn("$PromotionGates.Count -eq 0", source)
        self.assertIn("promotion gate set is missing", source)


if __name__ == "__main__":
    unittest.main()
