#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
OPERATOR_PAGES = (
    "todos.html",
    "dashboard.html",
    "wall.html",
    "terminal.html",
    "terminal-graph.html",
)


class WindowsDictationOnlyContract(unittest.TestCase):
    def test_production_has_no_browser_microphone_asset_or_hook(self):
        self.assertFalse((ROOT / "bin" / "voice-dock.js").exists())
        for name in OPERATOR_PAGES:
            page = (ROOT / "bin" / name).read_text(encoding="utf-8")
            self.assertNotIn("voice-dock", page, name)
            self.assertNotIn("SpeechRecognition", page, name)

    def test_server_has_no_voice_asset_or_terminal_paste_route(self):
        server = (ROOT / "bin" / "todo-server.py").read_text(encoding="utf-8")
        self.assertNotIn("/assets/voice-dock.js", server)
        self.assertNotIn("/voice/paste", server)
        self.assertNotIn("voice_paste", server)

    def test_shared_theme_and_browser_journeys_have_no_voice_runtime(self):
        css = (ROOT / "bin" / "mypeople-ui.css").read_text(encoding="utf-8")
        journey = (ROOT / "verify" / "browser_journeys.js").read_text(
            encoding="utf-8"
        )
        for source in (css, journey):
            self.assertNotIn("voice-dock", source)
            self.assertNotIn("SpeechRecognition", source)
        self.assertNotIn("/voice/paste", journey)


if __name__ == "__main__":
    unittest.main(verbosity=2)
