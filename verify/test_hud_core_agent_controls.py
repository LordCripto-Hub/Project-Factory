#!/usr/bin/env python3
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "bin" / "dashboard.html").read_text(encoding="utf-8")


class HudCoreAgentControlsContract(unittest.TestCase):
    def test_only_server_authorized_core_agents_receive_command_strip(self):
        self.assertRegex(SOURCE, r"function isCoreControlled\(row\)")
        self.assertRegex(SOURCE, r"function addCommandStrip\(card,\s*row\)")
        self.assertIn("controlCapabilities.agents", SOURCE)
        self.assertIn("controlCapabilities.models", SOURCE)
        self.assertIn("/control-capabilities", SOURCE)
        self.assertNotIn("CORE_AGENT_IDS", SOURCE)

    def test_kill_requires_five_second_confirmation(self):
        self.assertIn("Confirm kill", SOURCE)
        self.assertIn("5000", SOURCE)
        self.assertIn("event.stopPropagation()", SOURCE)
        self.assertIn("card-action danger armed", SOURCE)

    def test_mutations_are_closed_and_status_is_honest(self):
        self.assertRegex(SOURCE, r'postControl\(["\']?/kill')
        self.assertIn('"/revive"', SOURCE)
        self.assertIn('"/switch"', SOURCE)
        self.assertIn("command-status", SOURCE)
        self.assertIn("data.ok === false", SOURCE)
        self.assertIn("await poll()", SOURCE)
        self.assertNotIn("row.model=selected", SOURCE)
        self.assertNotIn('type=\"text\"', SOURCE)

    def test_controls_survive_stale_telemetry_from_fresh_roster(self):
        self.assertRegex(SOURCE, r"addCommandStrip\(card,\s*row\)")
        self.assertRegex(SOURCE, r"telemetryStale\s*=\s*true")
        self.assertIn("renderAgentCards()", SOURCE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
