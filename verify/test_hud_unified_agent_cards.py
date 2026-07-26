#!/usr/bin/env python3
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class HudUnifiedAgentCardsContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "bin" / "dashboard.html").read_text(encoding="utf-8")
        cls.browser_source = (ROOT / "verify" / "browser_journeys.js").read_text(
            encoding="utf-8"
        )

    def test_agents_table_is_replaced_by_unified_cards(self):
        self.assertNotIn('id="agentsTable"', self.source)
        self.assertIn("function buildCardRows()", self.source)
        self.assertIn("function renderAgentCards()", self.source)
        self.assertIn('id="retiredAgents"', self.source)
        self.assertIn('id="retiredCards"', self.source)

    def test_cards_attach_without_nested_action_bubbling(self):
        for marker in (
            "card.dataset.attachUrl",
            "activateCardAttach",
            "event.stopPropagation()",
            "event.key==='Enter'||event.key===' '",
            "role','link'",
        ):
            self.assertIn(marker, self.source)

    def test_spawn_and_summary_are_compact(self):
        self.assertIn("Copy spawn", self.source)
        self.assertIn("summary-toggle", self.source)
        self.assertIn("navigator.clipboard?.writeText", self.source)
        self.assertIn("catch(()=>{})", self.source)
        self.assertNotIn('class="cmd"', self.source)

    def test_cards_remain_safe_and_telemetry_honest(self):
        self.assertIn("telemetryStale", self.source)
        self.assertIn("not measured", self.source)
        self.assertIn("textContent", self.source)
        self.assertNotIn("innerHTML", self.source)
        self.assertNotIn("session_id", self.source)
        self.assertNotIn("diagnosticRef", self.source)

    def test_browser_journey_covers_attach_nested_actions_and_stale_fallback(self):
        for marker in (
            "assertUnifiedHudCards",
            "nested card action opened a popup",
            "card click did not open terminal",
            "keyboard attach did not open terminal",
            "HUD cards disappeared during stale telemetry",
        ):
            self.assertIn(marker, self.browser_source)

    def test_full_browser_journey_waits_for_async_hud_cards(self):
        self.assertIn(
            "await page.waitForFunction(() => document.querySelectorAll('#telemetryCards .combat-card').length >= 1);",
            self.browser_source,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
