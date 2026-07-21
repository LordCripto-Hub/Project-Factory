#!/usr/bin/env python3
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MemoryCanarySidecarContract(unittest.TestCase):
    def test_compose_is_internal_read_only_and_has_no_production_mounts(self):
        text = (ROOT / "experiments/memory-gate-b/docker/compose.live-canary.yml").read_text(encoding="utf-8")
        for marker in (
            "read_only: true", "cap_drop:", "- ALL",
            "no-new-privileges:true", "internal: true",
            "read_only: true",
        ):
            self.assertIn(marker, text)
        self.assertNotIn("ports:", text)
        self.assertNotIn("/var/run/docker.sock", text)
        self.assertNotIn("/home/mp/mypeople/run", text)
        self.assertNotIn("/home/mp/.codex", text)

    def test_entrypoint_requires_live_marker_and_secret_file(self):
        text = (ROOT / "experiments/memory-gate-b/docker/live-canary-entrypoint.sh").read_text(encoding="utf-8")
        self.assertIn('MYPEOPLE_GATE_B_LIVE_CANARY', text)
        self.assertIn('/run/secrets/MYPEOPLE_MEMORY_CANARY_TOKEN', text)
        self.assertIn('exec node', text)

    def test_server_keeps_https_fixture_and_explicit_internal_http_mode(self):
        text = (ROOT / "experiments/memory-gate-b/docker/taskspec-memory-server.mjs").read_text(encoding="utf-8")
        self.assertIn("createServer as createHttpServer", text)
        self.assertIn("createServer as createHttpsServer", text)
        self.assertIn("MYPEOPLE_GATE_B_LIVE_CANARY", text)
        self.assertIn("host !== '0.0.0.0'", text)
        self.assertIn("host !== '127.0.0.1'", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
