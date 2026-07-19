#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import stat
import tempfile
import unittest

import provider_handoff
import provider_transaction


class ProviderSharedPrimitiveContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.lock_path = str(Path(self.temp.name) / "provider-switch.lock")

    def test_handoff_is_bounded_and_redacts_secret_material(self):
        record = {
            "agent_id": "node-1/main:Worker-1",
            "backend": "codex",
            "model": "gpt-5.6-luna",
            "owner_task_id": "task-1",
            "session_id": "must-not-leak",
        }
        handoff = provider_handoff.build_handoff(
            record, "OPENAI_API_KEY=secret\nwork completed"
        )
        rendered = json.dumps(handoff)
        self.assertNotIn("secret", rendered)
        self.assertNotIn("must-not-leak", rendered)
        self.assertLessEqual(len(handoff["terminalTail"]), 4000)

    def test_provider_lock_is_owned_exclusive_and_private(self):
        provider_transaction.acquire_lock(self.lock_path, "tx-one")
        self.assertEqual(
            stat.S_IMODE(Path(self.lock_path).stat().st_mode), 0o600
        )
        with self.assertRaises(provider_transaction.SwitchBusy):
            provider_transaction.acquire_lock(self.lock_path, "tx-two")
        provider_transaction.release_lock(self.lock_path, "tx-two")
        self.assertTrue(Path(self.lock_path).exists())
        provider_transaction.release_lock(self.lock_path, "tx-one")
        self.assertFalse(Path(self.lock_path).exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
