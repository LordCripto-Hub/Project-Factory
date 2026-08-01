#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LocalMemoryRuntimeContractTests(unittest.TestCase):
    def test_supervisor_owns_one_local_memory_runtime(self):
        supervisor = (ROOT / "bin" / "runtime-supervisor.sh").read_text(encoding="utf-8")
        self.assertIn('spawn local-memory python3 "$ROOT/bin/local-memory-runtime.py"', supervisor)

    def test_runtime_is_loopback_only_and_reuses_hybrid_memory(self):
        runtime = (ROOT / "bin" / "local-memory-runtime.py").read_text(encoding="utf-8")
        self.assertIn("http://127.0.0.1:18443/mcp", runtime)
        self.assertIn("query_automatic_memory.py", runtime)
        self.assertNotIn("cloudflare", runtime.lower())
        self.assertNotIn("codex_apps", runtime)
        self.assertIn("mode != \"automatic\"", runtime)
        self.assertIn('RUNTIME / "node_modules"', runtime)
        self.assertIn('ROOT / "memory-gateway" / "node_modules"', runtime)

    def test_runtime_allows_only_its_loopback_http_profile(self):
        supervisor = (ROOT / "bin" / "runtime-supervisor.sh").read_text(encoding="utf-8")
        self.assertIn('export MYPEOPLE_MEMORY_ALLOW_HTTP=1', supervisor)

    def test_server_paths_are_runtime_configurable(self):
        server = (ROOT / "bin" / "local-memory-server.mjs").read_text(encoding="utf-8")
        for setting in (
            "MYPEOPLE_LOCAL_MEMORY_QUERY",
            "MYPEOPLE_LOCAL_MEMORY_DATASET",
            "MYPEOPLE_LOCAL_MEMORY_LOCK",
            "MYPEOPLE_LOCAL_MEMORY_RUNTIME",
        ):
            self.assertIn(setting, server)
        self.assertNotIn("/workspace/scripts", server)
        self.assertNotIn("0.0.0.0", server)


if __name__ == "__main__":
    unittest.main(verbosity=2)
