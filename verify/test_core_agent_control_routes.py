#!/usr/bin/env python3
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CoreAgentControlRoutesContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.queue_source = (ROOT / "bin" / "queue-server.py").read_text(encoding="utf-8")
        cls.todo_source = (ROOT / "bin" / "todo-server.py").read_text(encoding="utf-8")

    def test_capabilities_and_actions_use_existing_auth(self):
        self.assertIn('if path=="/control-capabilities"', self.queue_source)
        self.assertIn('if path in ("/kill","/revive","/switch")', self.queue_source)
        self.assertLess(self.queue_source.index("if not self.authed()"), self.queue_source.index('if path=="/control-capabilities"'))

    def test_routes_delegate_to_closed_domain_and_sanitize_failures(self):
        self.assertIn("core_agent_controls.execute", self.queue_source)
        self.assertIn('{"ok":False,"error":error.code}', self.queue_source)
        self.assertIn('"control_unavailable"', self.queue_source)
        self.assertNotIn("shell=True", self.queue_source)

    def test_todo_proxy_forwards_only_fixed_control_routes(self):
        for route in ('"/control-capabilities"', '"/kill"', '"/revive"', '"/switch"'):
            self.assertIn(route, self.todo_source)
        self.assertNotIn('"/command"', self.todo_source)


if __name__ == "__main__":
    unittest.main(verbosity=2)

