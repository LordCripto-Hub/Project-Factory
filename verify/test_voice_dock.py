#!/usr/bin/env python3
"""Voice Dock safety and same-origin integration contracts."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_server():
    sys.path.insert(0, str(ROOT / "bin"))
    loader = importlib.machinery.SourceFileLoader("todo_server_voice", str(ROOT / "bin" / "todo-server.py"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class VoiceDockContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = {
            "INSTALL_DIR": str(ROOT),
            "QUEUE_SECRET": "verify-secret",
            "HOST_ID": "verify-host",
            "NIGHTWATCH_IDLE_MIN": "9999",
        }
        with patch.dict(os.environ, env, clear=False):
            cls.server = load_server()

    def test_terminal_paste_neutralizes_control_characters(self):
        text = self.server.safe_terminal_text("echo first\r\necho second\n\x1b[31m\tbad\x7f")
        self.assertEqual(text, "echo first echo second [31m bad")
        self.assertFalse(any(ord(char) < 32 or ord(char) == 127 for char in text))

    def test_shared_module_uses_native_speech_recognition_and_never_submits(self):
        js = (ROOT / "bin" / "voice-dock.js").read_text(encoding="utf-8")
        self.assertIn("SpeechRecognition", js)
        self.assertIn("webkitSpeechRecognition", js)
        self.assertIn("interimResults", js)
        self.assertIn("es-AR", js)
        self.assertIn("/voice/paste", js)
        self.assertNotIn("MediaRecorder", js)
        self.assertNotIn("/voice/transcribe", js)
        self.assertNotIn("OPENAI_API_KEY", js)
        self.assertNotIn("requestSubmit(", js)
        self.assertNotIn("form.submit(", js)

    def test_ctrl_windows_shortcut_is_latched_and_toggles_dictation(self):
        js = (ROOT / "bin" / "voice-dock.js").read_text(encoding="utf-8")
        self.assertIn("event.ctrlKey&&event.metaKey", js)
        self.assertIn("shortcutLatched", js)
        self.assertIn("toggleListening", js)

    def test_server_has_no_paid_transcription_proxy(self):
        source = (ROOT / "bin" / "todo-server.py").read_text(encoding="utf-8")
        self.assertNotIn("OPENAI_API_KEY", source)
        self.assertNotIn('p=="/voice/transcribe"', source)
        self.assertNotIn("api.openai.com", source)

    def test_compact_dock_exposes_a_recording_animation(self):
        css = (ROOT / "bin" / "mypeople-ui.css").read_text(encoding="utf-8")
        js = (ROOT / "bin" / "voice-dock.js").read_text(encoding="utf-8")
        self.assertIn("voice-meter", js)
        self.assertIn("@keyframes voice-meter", css)
        self.assertIn(".voice-dock.listening", css)

    def test_visible_voice_strings_are_english(self):
        js = (ROOT / "bin" / "voice-dock.js").read_text(encoding="utf-8")
        for phrase in ("MyPeople Dictation", "Start dictation", "Listening", "Text inserted"):
            self.assertIn(phrase, js)

    def test_browser_journey_executes_mocked_dictation(self):
        journey = (ROOT / "verify" / "browser_journeys.js").read_text(encoding="utf-8")
        self.assertIn("async function voiceMock", journey)
        self.assertIn("FakeSpeechRecognition", journey)
        self.assertIn("scenario === 'voice_mock'", journey)

    def test_terminal_wrapper_is_same_origin(self):
        html = (ROOT / "bin" / "terminal.html").read_text(encoding="utf-8")
        self.assertIn("voice-dock.js", html)
        self.assertIn("id=\"terminalFrame\"", html)
        self.assertIn("data-terminal-agent", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
