#!/usr/bin/env python3
"""Static safety contract for the one-click Windows launcher."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WindowsLauncherContract(unittest.TestCase):
    def test_launcher_is_bounded_preserving_and_health_gated(self):
        text = (ROOT / "windows" / "Start-MyPeople.ps1").read_text(encoding="utf-8")
        self.assertIn("Docker Desktop.exe", text)
        self.assertIn("docker info", text)
        self.assertIn("docker start mypeople", text)
        self.assertIn("mypeople up --detach", text)
        self.assertIn("http://localhost:9933/health", text)
        self.assertIn("http://localhost:9900/health", text)
        self.assertIn("main:Boss \\[alive\\]", text)
        self.assertIn("nightwatch:Nightwatch \\[alive\\]", text)
        self.assertIn("Boss and Nightwatch", text)
        self.assertIn("Start-Process 'http://localhost:9933/'", text)
        self.assertIn("launcher.log", text)
        self.assertIn("MyPeople could not start", text)
        self.assertIn("Docker CLI is not installed", text)
        self.assertNotIn("docker rm", text)
        self.assertNotIn("docker run", text)
        self.assertNotIn("docker compose down", text)

    def test_launcher_rehydrates_provider_before_starting_agents(self):
        text = (ROOT / "windows" / "Start-MyPeople.ps1").read_text(encoding="utf-8")
        compose = text.index("docker compose pinned deployment up")
        container_start = text.index("docker start mypeople")
        memory_rehydrate = text.index("Sync-MyPeopleMemoryActivation")
        rehydrate = text.index("& $adapter.ActivateProfile")
        start_agents = text.index("mypeople up --detach")
        self.assertLess(compose, memory_rehydrate)
        self.assertLess(container_start, memory_rehydrate)
        self.assertLess(memory_rehydrate, rehydrate)
        self.assertLess(compose, rehydrate)
        self.assertLess(container_start, rehydrate)
        self.assertLess(rehydrate, start_agents)
        self.assertIn("& $adapter.ValidateRuntime", text)
        self.assertIn("No provider binding configured", text)

    def test_provider_failure_opens_control_plane_in_degraded_mode(self):
        text = (ROOT / "windows" / "Start-MyPeople.ps1").read_text(encoding="utf-8")
        required = [
            "$providerReady = $false",
            "$providerWarning",
            "providers-pause",
            "providers-resume",
            "READY DEGRADED",
            "if ($providerReady)",
            "Show-LauncherWarning",
        ]
        for value in required:
            self.assertIn(value, text)
        self.assertNotIn("Save-MyPeopleProviderProfile.ps1", text)
        self.assertNotIn("Save-MyPeopleCodexCredential", text)
        provider_gate = text.index("if ($providerReady)")
        agent_wait = text.index("'Boss and Nightwatch'")
        browser_open = text.index("Start-Process 'http://localhost:9933/'")
        self.assertLess(provider_gate, agent_wait)
        self.assertLess(agent_wait, browser_open)

    def test_provider_launch_gate_precedes_every_container_start(self):
        launcher = (ROOT / "windows" / "Start-MyPeople.ps1").read_text(
            encoding="utf-8"
        )
        compose = (ROOT / "docker" / "compose.volume-backed.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("provider-launch-gate:", compose)
        self.assertIn('profiles: ["launcher"]', compose)
        self.assertIn("network_mode: none", compose)
        self.assertIn("provider-launch-gate", launcher)
        self.assertIn("Set-LegacyProviderLaunchGate", launcher)

        pinned_gate = launcher.index("run --rm --no-deps provider-launch-gate")
        pinned_start = launcher.index("docker compose pinned deployment up")
        legacy_gate = launcher.index("Set-LegacyProviderLaunchGate -Container 'mypeople'")
        legacy_start = launcher.index("docker start mypeople")
        self.assertLess(pinned_gate, pinned_start)
        self.assertLess(legacy_gate, legacy_start)

    def test_launcher_uses_dpapi_to_tmpfs_memory_rehydration(self):
        text = (ROOT / "windows" / "Start-MyPeople.ps1").read_text(encoding="utf-8")
        self.assertIn("MyPeople.Memory.psm1", text)
        self.assertIn("Sync-MyPeopleMemoryActivation", text)
        self.assertNotIn("MYPEOPLE_MEMORY_TOKEN=", text)

        compose = (ROOT / "docker" / "compose.volume-backed.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("tmpfs:", compose)
        self.assertIn("/run/mypeople-secrets", compose)
        self.assertIn("uid=1000", compose)
        self.assertIn("gid=1000", compose)
        self.assertIn("mode=0700", compose)
        self.assertNotIn("MYPEOPLE_MEMORY_TOKEN", compose)

    def test_launcher_recovers_the_pinned_volume_backed_deployment(self):
        text = (ROOT / "windows" / "Start-MyPeople.ps1").read_text(encoding="utf-8")
        self.assertIn(r"MyPeople\deployment", text)
        self.assertIn("compose.volume-backed.yml", text)
        self.assertIn("--env-file", text)
        self.assertIn("docker compose", text)
        self.assertNotIn("compose down", text)
        self.assertNotIn("volume rm", text)
        self.assertNotIn("compose.tailscale.yml", text)
        self.assertNotIn("TS_AUTHKEY", text)

    def test_launcher_supports_noninteractive_migration_verification(self):
        launcher = (ROOT / "windows" / "Start-MyPeople.ps1").read_text(encoding="utf-8")
        migration = (
            ROOT / "windows" / "Migrate-MyPeopleDockerState.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("[switch]$NonInteractive", launcher)
        self.assertIn("if (-not $NonInteractive)", launcher)
        self.assertIn("powershell.exe", migration)
        self.assertIn("-NonInteractive", migration)

    def test_shortcut_installer_targets_hidden_powershell_launcher(self):
        text = (ROOT / "windows" / "Install-MyPeopleShortcut.ps1").read_text(encoding="utf-8")
        self.assertIn("CreateShortcut", text)
        self.assertIn("Start-MyPeople.ps1", text)
        self.assertIn("LOCALAPPDATA", text)
        self.assertIn("MyPeople\\launcher", text)
        self.assertIn("Copy-Item", text)
        self.assertIn("MyPeople.ProviderProfiles.psm1", text)
        self.assertIn("MyPeople.Memory.psm1", text)
        self.assertIn("Set-MyPeopleMemoryCredential.ps1", text)
        self.assertIn("Set-MyPeopleMemoryActivation.ps1", text)
        self.assertIn("compose.volume-backed.yml", text)
        self.assertIn("compose.tailscale.yml", text)
        self.assertIn("state-volumes.json", text)
        self.assertIn("-WindowStyle Hidden", text)
        self.assertIn("MyPeople.lnk", text)

    def test_public_docs_use_windows_dictation_and_explicit_remote_opt_in(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        manual = (ROOT / "docs" / "USER-MANUAL.md").read_text(encoding="utf-8")
        for text in (readme, manual):
            self.assertIn("Win + H", text)
            self.assertIn("compose.tailscale.yml", text)
            self.assertIn("127.0.0.1", text)
            self.assertNotIn("Ctrl + Windows", text)
            self.assertNotIn("Voice Dock", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
