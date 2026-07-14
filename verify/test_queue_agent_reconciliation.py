#!/usr/bin/env python3
"""Queue heartbeat must replace, not only append, each host agent set."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import os
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_runtime():
    module_dir = str(ROOT / "bin")
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
    path = str(ROOT / "bin" / "queue-server.py")
    loader = importlib.machinery.SourceFileLoader(
        "mypeople_queue_reconcile_under_test_" + os.urandom(4).hex(), path
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class QueueAgentReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.queue = load_runtime()
        self.queue.AGENTS.clear()

    def test_missing_agent_is_removed_on_next_host_heartbeat(self):
        self.queue.reconcile_host_agents("node-1", [
            {"agent_id": "node-1/main:Boss", "state": "alive"},
            {"agent_id": "node-1/main:eng-2", "state": "alive"},
        ])
        self.assertIn("node-1/main:eng-2", self.queue.AGENTS)

        self.queue.reconcile_host_agents("node-1", [
            {"agent_id": "node-1/main:Boss", "state": "alive"},
        ])

        self.assertIn("node-1/main:Boss", self.queue.AGENTS)
        self.assertNotIn("node-1/main:eng-2", self.queue.AGENTS)

    def test_other_hosts_are_not_removed(self):
        self.queue.reconcile_host_agents("node-2", [
            {"agent_id": "node-2/main:Boss", "state": "alive"},
        ])
        self.queue.reconcile_host_agents("node-1", [])

        self.assertIn("node-2/main:Boss", self.queue.AGENTS)


if __name__ == "__main__":
    unittest.main(verbosity=2)