#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


sys.path.insert(0, str(ROOT / "bin"))
from recording_policy import recording_mode, reconcile_recorder


class Result:
    def __init__(self, returncode=0): self.returncode = returncode


class RecordingPolicyTests(unittest.TestCase):
    def test_policy_defaults_off_and_precedence_is_agent_profile_environment(self):
        self.assertEqual(recording_mode({}, {}, {}), "off")
        self.assertEqual(recording_mode({}, {}, {"MYPEOPLE_RECORDING_DEFAULT": "on"}), "on")
        self.assertEqual(recording_mode({}, {"recording": "off"}, {"MYPEOPLE_RECORDING_DEFAULT": "on"}), "off")
        self.assertEqual(recording_mode({"recording": "on"}, {"recording": "off"}, {}), "on")
        self.assertEqual(recording_mode({"recording": "invalid"}, {}, {}), "off")

    def test_off_reaps_recorder_and_on_is_idempotent(self):
        calls = []
        def tmux(args, **_kwargs):
            calls.append(args)
            if args[:2] == ["has-session", "-t"]:
                return Result(0)
            return Result(0)
        self.assertEqual(reconcile_recorder(tmux, "main", "eng-1", "off", "/tmp/test.cast"), "off")
        self.assertEqual(reconcile_recorder(tmux, "main", "eng-1", "on", "/tmp/test.cast"), "recording")
        self.assertIn(["kill-session", "-t", "rec-eng-1"], calls)
        self.assertFalse(any(call[0] == "new-session" for call in calls))

    def test_hud_has_sanitized_recording_states(self):
        page = (ROOT / "bin" / "dashboard.html").read_text(encoding="utf-8")
        self.assertIn("recordingState", page)
        for state in ("recording", "off", "unknown"):
            self.assertIn(f'"{state}"', page)


if __name__ == "__main__": unittest.main(verbosity=2)
