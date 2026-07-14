#!/usr/bin/env python3
"""Regression for Codex TUI paste/render/submit ordering."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import unittest


class Result:
    returncode = 0
    stdout = ""
    stderr = ""


class CodexSubmitContract(unittest.TestCase):
    def test_submit_waits_for_a_render_tick_after_paste(self):
        runtime = Path(os.environ.get(
            "MYPEOPLE_MPCOMMON",
            "/home/mp/mypeople/bin/mpcommon.py",
        )).resolve()
        spec = importlib.util.spec_from_file_location("mpcommon_codex_submit_under_test", runtime)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        events = []

        def runner(argv, **_kwargs):
            events.append(("tmux", list(argv)))
            return Result()

        module.time.sleep = lambda seconds: events.append(("sleep", seconds))
        self.assertTrue(module.tmux_send_message("mc-main:Boss", "single line", runner=runner))

        paste = next(i for i, event in enumerate(events) if event[:2] == ("tmux", ["paste-buffer", "-d", "-t", "mc-main:Boss"]))
        render_ticks = [i for i, event in enumerate(events) if event[0] == "sleep"]
        self.assertTrue(render_ticks, "message delivery must wait after paste before Enter")
        render_tick = render_ticks[0]
        submit = next(i for i, event in enumerate(events) if event[:2] == ("tmux", ["send-keys", "-t", "mc-main:Boss", "Enter"]))
        self.assertLess(paste, render_tick)
        self.assertLess(render_tick, submit)
        self.assertGreater(events[render_tick][1], 0)
        self.assertLessEqual(events[render_tick][1], 0.25)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(CodexSubmitContract)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("PASS Codex message delivery waits for render before submit")
    raise SystemExit(0 if result.wasSuccessful() else 1)
