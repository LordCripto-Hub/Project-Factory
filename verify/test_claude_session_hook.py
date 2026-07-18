#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "plugins" / "tmux-boss-hooks" / "scripts" / "emit-event"


class ClaudeSessionHookContract(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.install = self.root / "mypeople"
        self.workspace = self.root / "workspace"
        self.roster = self.install / "run" / "roster.json"
        self.status = self.install / "status"
        self.workspace.mkdir()
        self.roster.parent.mkdir(parents=True)
        self.write_roster()

    def write_roster(self):
        self.roster.write_text(
            json.dumps(
                [
                    {
                        "agent_id": "node-1/main:Boss",
                        "backend": "claude",
                        "cwd": str(self.workspace),
                        "session_id": "",
                        "resume_state": "pending",
                    },
                    {
                        "agent_id": "node-1/main:Other",
                        "session_id": "keep-me",
                    },
                ]
            ),
            encoding="utf-8",
        )

    def tearDown(self):
        self.temporary.cleanup()

    def run_hook(self, session_id: str):
        environment = os.environ.copy()
        environment.update(
            {
                "AGENT_ID": "node-1/main:Boss",
                "INSTALL_DIR": str(self.install),
                "ROSTER_PATH": str(self.roster),
                "STATUS_DIR": str(self.status),
                "MYPEOPLE_PROVIDER_PROFILE": "claude-primary",
                "PYTHONPATH": str(ROOT / "bin"),
                "HOME": str(self.root / "home"),
                "QUEUE_URL": "http://127.0.0.1:1",
                "QUEUE_SECRET": "test-only",
            }
        )
        payload = {
            "hook_event_name": "SessionStart",
            "session_id": session_id,
        }
        return subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps(payload),
            text=True,
            cwd=self.workspace,
            env=environment,
            capture_output=True,
            timeout=15,
        )

    def load_roster(self):
        return json.loads(self.roster.read_text(encoding="utf-8"))

    def test_session_start_persists_claude_identity_in_status_and_roster(self):
        completed = self.run_hook("claude-session-1234")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "")
        rows = self.load_roster()
        boss = next(row for row in rows if row["agent_id"].endswith(":Boss"))
        other = next(row for row in rows if row["agent_id"].endswith(":Other"))
        self.assertEqual(boss["session_id"], "claude-session-1234")
        self.assertEqual(boss["session_backend"], "claude")
        self.assertEqual(boss["session_profile"], "claude-primary")
        self.assertEqual(boss["session_cwd"], os.path.realpath(self.workspace))
        self.assertEqual(boss["resume_state"], "available")
        self.assertEqual(other["session_id"], "keep-me")
        status_path = self.status / "mc-main" / "Boss.json"
        status = json.loads(status_path.read_text(encoding="utf-8"))
        self.assertEqual(status["session_id"], "claude-session-1234")

    def test_invalid_session_id_is_ignored_without_payload_output(self):
        before = self.roster.read_text(encoding="utf-8")
        completed = self.run_hook("../escape")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "")
        self.assertEqual(self.roster.read_text(encoding="utf-8"), before)
        self.assertNotIn("../escape", completed.stderr)

    def test_session_start_waits_for_spawn_to_publish_roster_row(self):
        self.roster.unlink()
        writer = threading.Timer(0.75, self.write_roster)
        writer.start()
        try:
            completed = self.run_hook("claude-session-race-1234")
        finally:
            writer.join(timeout=2)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        boss = next(
            row
            for row in self.load_roster()
            if row["agent_id"].endswith(":Boss")
        )
        self.assertEqual(boss["session_id"], "claude-session-race-1234")
        self.assertEqual(boss["resume_state"], "available")


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(
        ClaudeSessionHookContract
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("PASS Claude hook session identity persistence")
    raise SystemExit(0 if result.wasSuccessful() else 1)
