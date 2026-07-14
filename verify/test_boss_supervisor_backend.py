#!/usr/bin/env python3
"""Regression contract for backend-aware internal-agent recovery."""
from __future__ import annotations

import os
from pathlib import Path
import unittest


class SupervisorBackendContract(unittest.TestCase):
    def setUp(self):
        self.source = Path(os.environ.get(
            "MYPEOPLE_SUPERVISOR",
            "/home/mp/mypeople/bin/boss-supervisor.sh",
        )).read_text(encoding="utf-8")

    def test_existing_boss_is_revived_from_roster(self):
        self.assertIn('boss_id="$HOST_ID/main:Boss"', self.source)
        self.assertIn('jq -e --arg aid "$boss_id"', self.source)
        self.assertIn('"$ROOT/bin/mp" revive "$boss_id"', self.source)

    def test_empty_roster_bootstraps_boss_with_codex_sol(self):
        roster_check = self.source.index('jq -e --arg aid "$boss_id"')
        revive = self.source.index('"$ROOT/bin/mp" revive "$boss_id"', roster_check)
        fallback = self.source.index('"$ROOT/bin/mp" spawn "$boss_id" --master --backend codex --model gpt-5.6-sol', revive)
        self.assertLess(roster_check, revive)
        self.assertLess(revive, fallback)
        between = self.source[revive:fallback]
        self.assertIn("else", between)
        self.assertNotIn("||", between)

    def test_nightwatch_revives_roster_or_bootstraps_codex_luna(self):
        self.assertIn('nightwatch_id="$HOST_ID/nightwatch:Nightwatch"', self.source)
        start = self.source.index('nightwatch_id="$HOST_ID/nightwatch:Nightwatch"')
        roster_check = self.source.index('jq -e --arg aid "$nightwatch_id"', start)
        revive = self.source.index('"$ROOT/bin/mp" revive "$nightwatch_id"', roster_check)
        fallback = self.source.index('"$ROOT/bin/mp" spawn "$nightwatch_id" --boss "$boss_id" --cwd "$ROOT/run/nightwatch" --backend codex --model gpt-5.6-luna', revive)
        self.assertLess(roster_check, revive)
        self.assertLess(revive, fallback)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(SupervisorBackendContract)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("PASS internal supervisors revive persisted backends and bootstrap Codex")
    raise SystemExit(0 if result.wasSuccessful() else 1)
