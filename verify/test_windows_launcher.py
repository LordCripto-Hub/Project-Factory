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
        container_start = text.index("docker start mypeople")
        rehydrate = text.index("& $adapter.ActivateProfile")
        start_agents = text.index("mypeople up --detach")
        self.assertLess(container_start, rehydrate)
        self.assertLess(rehydrate, start_agents)
        self.assertIn("& $adapter.ValidateRuntime", text)
        self.assertIn("No provider binding configured", text)

    def test_shortcut_installer_targets_hidden_powershell_launcher(self):
        text = (ROOT / "windows" / "Install-MyPeopleShortcut.ps1").read_text(encoding="utf-8")
        self.assertIn("CreateShortcut", text)
        self.assertIn("Start-MyPeople.ps1", text)
        self.assertIn("LOCALAPPDATA", text)
        self.assertIn("MyPeople\\launcher", text)
        self.assertIn("Copy-Item", text)
        self.assertIn("MyPeople.ProviderProfiles.psm1", text)
        self.assertIn("-WindowStyle Hidden", text)
        self.assertIn("MyPeople.lnk", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
