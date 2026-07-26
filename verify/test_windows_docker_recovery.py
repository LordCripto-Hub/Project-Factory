#!/usr/bin/env python3
"""Static safety contract for image-loss recovery on Windows."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "windows" / "Recover-MyPeopleDockerDeployment.ps1"


class WindowsDockerRecoveryContract(unittest.TestCase):
    def setUp(self):
        self.text = SCRIPT.read_text(encoding="utf-8")

    def test_recovery_is_fail_closed_and_volume_preserving(self):
        for token in (
            "[Parameter(Mandatory)][string]$CandidateImage",
            "[Parameter(Mandatory)][string]$VerificationReceipt",
            "Get-MyPeopleVolumeContract",
            "Enter-MyPeopleDockerOperationLock",
            "portable-state.tar.gz",
            "candidate-verified",
            "beforeBoardSha256",
            "beforeStableRosterSha256",
            "MYPEOPLE_MEMORY_COMPARISON_ENABLED=0",
            "recovery_failed",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.text)
        for forbidden in (
            "docker volume rm",
            "docker compose down -v",
            "docker system prune",
            "docker volume prune",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.text.lower())

    def test_preflight_refuses_unsafe_or_unverifiable_inputs(self):
        for token in (
            "Recovery requires the mypeople container to be absent.",
            "Required state volume is missing:",
            "Verification receipt did not pass.",
            "Verification receipt image ID does not match the candidate.",
            "Need at least $MinimumFreeGiB GiB free.",
            "if (-not $Execute)",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
