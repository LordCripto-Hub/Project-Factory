#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "bin" / "agent_session.py"
if not MODULE_PATH.is_file():
    raise AssertionError("agent_session module is missing")

spec = importlib.util.spec_from_file_location("agent_session_under_test", MODULE_PATH)
runtime = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(runtime)


class AgentSessionContract(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.codex_home = self.root / "codex"
        self.cwd = self.root / "workspace"
        self.cwd.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def write_codex_meta(
        self,
        session_id: str,
        cwd: Path | None = None,
        *,
        name: str | None = None,
        malformed: bool = False,
    ) -> Path:
        session_dir = self.codex_home / "sessions" / "2026" / "07" / "16"
        session_dir.mkdir(parents=True, exist_ok=True)
        path = session_dir / (
            name or f"rollout-2026-07-16T00-00-00-{session_id}.jsonl"
        )
        if malformed:
            path.write_text("{not-json}\n", encoding="utf-8")
        else:
            path.write_text(
                json.dumps(
                    {
                        "type": "session_meta",
                        "payload": {
                            "id": session_id,
                            "session_id": session_id,
                            "cwd": str(cwd or self.cwd),
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
        return path

    def test_session_id_accepts_opaque_safe_values_and_rejects_paths(self):
        self.assertEqual(
            runtime.validate_session_id(
                "019f0000-0000-7000-8000-000000000001"
            ),
            "019f0000-0000-7000-8000-000000000001",
        )
        self.assertEqual(runtime.validate_session_id("claude-session-1234"), "claude-session-1234")
        for value in ("", "short", "../escape", "a/bbbbbbb", "a\\bbbbbbb", "bad\nvalue"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(runtime.SessionError, "session_id_invalid"):
                    runtime.validate_session_id(value)

    def test_codex_discovery_accepts_exactly_one_new_matching_session(self):
        before = runtime.snapshot_codex_sessions(str(self.codex_home))
        session_id = "019f0000-0000-7000-8000-000000000001"
        path = self.write_codex_meta(session_id)

        found = runtime.discover_codex_session(
            str(self.codex_home),
            str(self.cwd),
            before,
            timeout=0.2,
            poll=0.01,
        )

        self.assertEqual(found["session_id"], session_id)
        self.assertEqual(found["cwd"], os.path.realpath(self.cwd))
        self.assertEqual(found["path"], str(path.resolve()))

    def test_codex_discovery_ignores_stale_session_and_times_out(self):
        self.write_codex_meta("019f0000-0000-7000-8000-000000000002")
        before = runtime.snapshot_codex_sessions(str(self.codex_home))

        with self.assertRaisesRegex(runtime.SessionError, "session_capture_timeout"):
            runtime.discover_codex_session(
                str(self.codex_home),
                str(self.cwd),
                before,
                timeout=0.03,
                poll=0.005,
            )

    def test_codex_discovery_rejects_wrong_cwd(self):
        before = runtime.snapshot_codex_sessions(str(self.codex_home))
        other = self.root / "other"
        other.mkdir()
        self.write_codex_meta(
            "019f0000-0000-7000-8000-000000000003",
            other,
        )

        with self.assertRaisesRegex(runtime.SessionError, "session_cwd_mismatch"):
            runtime.discover_codex_session(
                str(self.codex_home),
                str(self.cwd),
                before,
                timeout=0.03,
                poll=0.005,
            )

    def test_codex_discovery_rejects_malformed_and_ambiguous_metadata(self):
        before = runtime.snapshot_codex_sessions(str(self.codex_home))
        self.write_codex_meta(
            "019f0000-0000-7000-8000-000000000004",
            malformed=True,
        )
        with self.assertRaisesRegex(runtime.SessionError, "session_metadata_invalid"):
            runtime.discover_codex_session(
                str(self.codex_home),
                str(self.cwd),
                before,
                timeout=0.03,
                poll=0.005,
            )

        malformed_snapshot = runtime.snapshot_codex_sessions(str(self.codex_home))
        self.write_codex_meta(
            "019f0000-0000-7000-8000-000000000005",
            name="rollout-a.jsonl",
        )
        self.write_codex_meta(
            "019f0000-0000-7000-8000-000000000006",
            name="rollout-b.jsonl",
        )
        with self.assertRaisesRegex(runtime.SessionError, "session_capture_ambiguous"):
            runtime.discover_codex_session(
                str(self.codex_home),
                str(self.cwd),
                malformed_snapshot,
                timeout=0.03,
                poll=0.005,
            )

    def test_profile_capture_lock_rejects_second_holder(self):
        lock_root = self.root / "locks"
        with runtime.capture_lock(
            str(lock_root), "codex", "codex-primary", timeout=0.1, poll=0.01
        ):
            with self.assertRaisesRegex(runtime.SessionError, "session_capture_busy"):
                with runtime.capture_lock(
                    str(lock_root),
                    "codex",
                    "codex-primary",
                    timeout=0,
                    poll=0.01,
                ):
                    self.fail("second holder acquired the same profile lock")

    def test_resume_arguments_preserve_options_and_session_position(self):
        self.assertEqual(
            runtime.apply_resume_args(
                "codex",
                ["codex", "--model", "gpt-test", "-C", str(self.cwd)],
                "session-1234",
            ),
            [
                "codex",
                "resume",
                "--model",
                "gpt-test",
                "-C",
                str(self.cwd),
                "session-1234",
            ],
        )
        self.assertEqual(
            runtime.apply_resume_args(
                "claude",
                ["claude", "--model", "test"],
                "session-1234",
            ),
            ["claude", "--model", "test", "--resume", "session-1234"],
        )

    def test_resume_evidence_finds_codex_and_claude_transcripts(self):
        codex_id = "019f0000-0000-7000-8000-000000000007"
        codex_path = self.write_codex_meta(codex_id)
        self.assertEqual(
            runtime.validate_resume_evidence(
                "codex",
                codex_id,
                codex_home=str(self.codex_home),
            ),
            str(codex_path.resolve()),
        )

        claude_id = "claude-session-1234"
        claude_path = (
            self.root
            / "claude"
            / "projects"
            / "workspace"
            / f"{claude_id}.jsonl"
        )
        claude_path.parent.mkdir(parents=True)
        claude_path.write_text("{}\n", encoding="utf-8")
        self.assertEqual(
            runtime.validate_resume_evidence(
                "claude",
                claude_id,
                claude_config_dir=str(self.root / "claude"),
            ),
            str(claude_path.resolve()),
        )

        with self.assertRaisesRegex(runtime.SessionError, "session_missing"):
            runtime.validate_resume_evidence(
                "codex",
                "019f0000-0000-7000-8000-000000000099",
                codex_home=str(self.codex_home),
            )


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(AgentSessionContract)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("PASS provider session identity primitives")
    raise SystemExit(0 if result.wasSuccessful() else 1)
