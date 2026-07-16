#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LocalDefaultNetworkContract(unittest.TestCase):
    def test_default_compose_is_loopback_only_and_unprivileged(self):
        compose = (ROOT / "docker" / "compose.volume-backed.yml").read_text(
            encoding="utf-8"
        )
        for port in ("9900", "9933", "7681", "7682", "7699"):
            self.assertIn(f'"127.0.0.1:{port}:{port}"', compose)
        self.assertNotIn("/dev/net/tun", compose)
        self.assertNotIn("NET_ADMIN", compose)
        self.assertNotIn("MYPEOPLE_TAILSCALE_ENABLED", compose)

    def test_optional_tailscale_override_is_explicit_and_complete(self):
        override = (ROOT / "docker" / "compose.tailscale.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn('MYPEOPLE_TAILSCALE_ENABLED: "1"', override)
        self.assertIn("/dev/net/tun:/dev/net/tun", override)
        self.assertIn("NET_ADMIN", override)
        self.assertNotIn("ports:", override)

    def test_runtime_and_heartbeat_never_probe_tailscale_by_default(self):
        supervisor = (ROOT / "bin" / "runtime-supervisor.sh").read_text(
            encoding="utf-8"
        )
        client = (ROOT / "bin" / "queue-client.py").read_text(encoding="utf-8")
        self.assertIn(
            '[[ "${MYPEOPLE_TAILSCALE_ENABLED:-0}" == "1" ]]', supervisor
        )
        self.assertIn(
            'TAILSCALE_ENABLED = ENV.get("MYPEOPLE_TAILSCALE_ENABLED", "0") == "1"',
            client,
        )
        self.assertIn("if not TAILSCALE_ENABLED:", client)
        self.assertIn('ENV.get("TTYD_PUBLIC_URL", "")', client)


if __name__ == "__main__":
    unittest.main(verbosity=2)
