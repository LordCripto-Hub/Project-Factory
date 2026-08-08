#!/usr/bin/env python3
"""Safety contracts for read-only local emergency memory access."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

from local_memory_emergency import LocalEmergencyAdapter


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class LocalMemoryEmergencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.dataset = root / "project-factory-history-deadbeef0000"
        self.runtime = root / "runtime"
        self.dataset.mkdir()
        self.events = self.dataset / "events.jsonl"
        rows = [
            {
                "event_id": "commit-a", "sequence": 1,
                "topic": "publisher", "content": "Boss publisher approval",
                "fact_key": "commit:abc:subject", "fact_value": "approval",
                "provenance": "git+repo://Project-Factory@abc#commit",
                "event_type": "commit",
            },
            {
                "event_id": "file-b", "sequence": 2,
                "topic": "session", "content": "Exact tmux recovery",
                "fact_key": "path:bin/mp:latest-subject", "fact_value": "recovery",
                "provenance": "git+repo://Project-Factory@def#path=bin/mp",
                "event_type": "file_change",
            },
        ]
        self.events.write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )
        (self.dataset / "manifest.json").write_text(
            json.dumps({"source_sha": "deadbeef"}), encoding="utf-8"
        )
        self.lock = root / "dataset-lock.json"
        self.write_lock()

    def tearDown(self):
        self.temp.cleanup()

    def write_lock(self):
        files = {
            path.name: sha256(path)
            for path in self.dataset.iterdir() if path.is_file()
        }
        self.lock.write_text(json.dumps({
            "schema_version": 1,
            "dataset_dir": self.dataset.name,
            "source_sha": "deadbeef",
            "repo_slug": "LordCripto-Hub/Project-Factory",
            "files": files,
        }), encoding="utf-8")

    def test_temporary_view_is_private_bounded_and_removed(self):
        adapter = LocalEmergencyAdapter(self.dataset, self.lock, self.runtime)
        result = adapter.retrieve("publisher", limit=3, max_bytes=262_144)
        self.assertEqual([row["id"] for row in result["claims"]], ["commit-a"])
        self.assertLessEqual(len(result["claims"]), 3)
        self.assertEqual(list(self.runtime.glob("memory-view-*")), [])
        self.assertTrue(all(row["sourceUri"] for row in result["claims"]))
        if os.name != "nt":
            self.assertEqual(self.runtime.stat().st_mode & 0o777, 0o700)

    def test_dataset_is_never_mutated(self):
        before = {path.name: sha256(path) for path in self.dataset.iterdir()}
        LocalEmergencyAdapter(self.dataset, self.lock, self.runtime).retrieve(
            "tmux", limit=3
        )
        after = {path.name: sha256(path) for path in self.dataset.iterdir()}
        self.assertEqual(after, before)

    def test_lock_mismatch_and_preliminary_dataset_fail_closed(self):
        self.events.write_text("tampered\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "dataset_checksum_mismatch"):
            LocalEmergencyAdapter(self.dataset, self.lock, self.runtime).retrieve(
                "publisher", limit=3
            )
        preliminary = self.dataset.with_name("project-factory-history-preliminary")
        self.dataset.rename(preliminary)
        with self.assertRaisesRegex(ValueError, "preliminary_dataset_forbidden"):
            LocalEmergencyAdapter(preliminary, self.lock, self.runtime).retrieve(
                "publisher", limit=3
            )

    def test_byte_limit_and_malformed_rows_do_not_escape(self):
        self.events.write_text(
            json.dumps({"event_id": "broken", "content": "publisher"}) + "\n",
            encoding="utf-8",
        )
        self.write_lock()
        result = LocalEmergencyAdapter(
            self.dataset, self.lock, self.runtime
        ).retrieve("publisher", limit=3, max_bytes=64)
        self.assertEqual(result["claims"], [])
        self.assertLessEqual(result["bytesExamined"], 64)

    def test_limits_are_hard(self):
        adapter = LocalEmergencyAdapter(self.dataset, self.lock, self.runtime)
        for limit, max_bytes in ((4, 100), (3, 262_145), (True, 100)):
            with self.subTest(limit=limit, max_bytes=max_bytes), self.assertRaises(ValueError):
                adapter.retrieve("publisher", limit=limit, max_bytes=max_bytes)


if __name__ == "__main__":
    unittest.main(verbosity=2)
