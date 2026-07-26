#!/usr/bin/env python3
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class HudProviderTelemetryContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "bin" / "dashboard.html").read_text(encoding="utf-8")

    def test_combat_status_and_agent_detail_surfaces_exist(self):
        for marker in (
            'id="combatStatus"',
            'id="telemetryState"',
            'id="telemetryCards"',
            "Combat Status",
            "/todo/operator-telemetry",
            "<th>MODEL</th>",
            "<th>HEALTH</th>",
            "No active provider telemetry",
        ):
            self.assertIn(marker, self.source)

    def test_every_health_and_usage_state_is_rendered(self):
        for state in (
            "authenticated",
            "unknown",
            "quota_exhausted",
            "expired",
            "unreachable",
            "process_dead",
            "not measured",
        ):
            self.assertIn(state, self.source)
        self.assertIn("inputTokens", self.source)
        self.assertIn("outputTokens", self.source)
        self.assertIn("sessionAlias", self.source)

    def test_rendering_is_safe_selectable_and_stale_aware(self):
        for marker in (
            "textContent",
            "selected-agent",
            "scrollIntoView",
            "telemetryStale",
            "lastTelemetry",
            "STALE",
        ):
            self.assertIn(marker, self.source)
        self.assertNotIn("innerHTML", self.source)
        self.assertNotIn("diagnosticRef", self.source)
        self.assertNotIn("session_id", self.source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
