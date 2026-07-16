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

    def test_existing_roles_delegate_recovery_to_reconcile(self):
        self.assertIn('boss_id="$HOST_ID/main:Boss"', self.source)
        self.assertIn('jq -e --arg aid "$boss_id"', self.source)
        self.assertIn('"$ROOT/bin/mp" reconcile', self.source)
        self.assertNotIn('"$ROOT/bin/mp" revive', self.source)

    def test_provider_switch_lock_pauses_automatic_revival(self):
        loop = self.source.index("while :; do")
        guard = self.source.index('[[ -f "$ROOT/run/provider-switch.lock" ]]', loop)
        pause = self.source.index("sleep 1", guard)
        boss_check = self.source.index("tmux has-session -t mc-main:Boss", pause)
        self.assertLess(loop, guard)
        self.assertLess(guard, pause)
        self.assertLess(pause, boss_check)

    def test_empty_roster_bootstraps_boss_with_codex_sol(self):
        roster_check = self.source.index('jq -e --arg aid "$boss_id"')
        bootstrap = self.source.index('"$ROOT/bin/mp" spawn "$boss_id" --master --backend codex --model gpt-5.6-sol', roster_check)
        self.assertLess(roster_check, bootstrap)
        self.assertNotIn('"$ROOT/bin/mp" revive', self.source[roster_check:bootstrap])

    def test_nightwatch_revives_roster_or_bootstraps_codex_luna(self):
        self.assertIn('nightwatch_id="$HOST_ID/nightwatch:Nightwatch"', self.source)
        start = self.source.index('nightwatch_id="$HOST_ID/nightwatch:Nightwatch"')
        roster_check = self.source.index('jq -e --arg aid "$nightwatch_id"', start)
        bootstrap = self.source.index('"$ROOT/bin/mp" spawn "$nightwatch_id" --boss "$boss_id" --cwd "$ROOT/run/nightwatch" --backend codex --model gpt-5.6-luna', roster_check)
        self.assertLess(roster_check, bootstrap)
        self.assertNotIn('"$ROOT/bin/mp" revive', self.source[roster_check:bootstrap])

    def test_supervisor_uses_bounded_fifteen_second_reconcile_loop(self):
        reconcile = self.source.index('"$ROOT/bin/mp" reconcile')
        sleep = self.source.index("sleep 15", reconcile)
        self.assertLess(reconcile, sleep)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(SupervisorBackendContract)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("PASS internal supervisors revive persisted backends and bootstrap Codex")
    raise SystemExit(0 if result.wasSuccessful() else 1)
