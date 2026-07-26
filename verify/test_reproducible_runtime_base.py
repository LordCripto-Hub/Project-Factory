#!/usr/bin/env python3
"""Static contract for the repository-owned MyPeople recovery base."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ReproducibleRuntimeBaseContract(unittest.TestCase):
    def setUp(self):
        self.path = ROOT / "docker" / "Dockerfile.recovery-base"
        self.text = self.path.read_text(encoding="utf-8")

    def test_pins_compatible_runtime_and_non_root_identity(self):
        for token in (
            "ARG NODE_IMAGE=node:22-bookworm-slim@sha256:",
            "FROM debian:12-slim",
            "ARG TTYD_VERSION=1.7.7",
            "ARG CLAUDE_VERSION=2.1.205",
            "ARG CODEX_VERSION=0.144.3",
            "groupadd --gid 1000 mp",
            "useradd --uid 1000 --gid 1000",
            "USER mp",
            "node --version | grep -Eq '^v22\\.'",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.text)

    def test_installs_and_verifies_required_commands(self):
        for command in (
            "python3", "node", "npm", "tmux", "ttyd", "git",
            "rg", "codex", "claude", "ffmpeg",
        ):
            with self.subTest(command=command):
                self.assertIn(f"command -v {command}", self.text)
        self.assertIn("sha256sum -c -", self.text)

    def test_contains_no_credentials_or_remote_network_runtime(self):
        self.assertNotRegex(
            self.text,
            re.compile(
                r"(?i)COPY .*?(auth|credential|token|\.env|\.codex|\.claude)"
            ),
        )
        self.assertNotIn("tailscale", self.text.lower())
        self.assertNotIn("TS_AUTHKEY", self.text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
