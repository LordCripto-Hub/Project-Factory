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
        os.chmod(path, 0o600)
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

    def test_profile_capture_lock_rejects_symlinked_backend_directory(self):
        lock_root = self.root / "locks"
        outside = self.root / "outside-locks"
        outside.mkdir()
        lock_root.mkdir()
        (lock_root / "codex").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(
            runtime.SessionError,
            "session_capture_path_invalid",
        ):
            with runtime.capture_lock(
                str(lock_root),
                "codex",
                "codex-primary",
                timeout=0,
            ):
                self.fail("capture lock followed a symlinked directory")

    def test_profile_capture_lock_does_not_mutate_symlink_target(self):
        outside = self.root / "outside"
        outside.mkdir()
        linked = self.root / "linked"
        linked.symlink_to(outside, target_is_directory=True)
        escaped = outside / "capture"
        with self.assertRaisesRegex(
            runtime.SessionError,
            "session_capture_path_invalid",
        ):
            with runtime.capture_lock(
                str(linked / "capture"),
                "codex",
                "codex-primary",
                timeout=0,
            ):
                self.fail("capture lock crossed an intermediate symlink")
        self.assertFalse(escaped.exists())

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
                expected_cwd=str(self.cwd),
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
        claude_path.write_text(
            json.dumps(
                {
                    "sessionId": claude_id,
                    "cwd": str(self.cwd),
                }
            )
            + "\n",
            encoding="utf-8",
        )
        os.chmod(claude_path, 0o600)
        self.assertEqual(
            runtime.validate_resume_evidence(
                "claude",
                claude_id,
                claude_config_dir=str(self.root / "claude"),
                expected_cwd=str(self.cwd),
            ),
            str(claude_path.resolve()),
        )

        with self.assertRaisesRegex(runtime.SessionError, "session_missing"):
            runtime.validate_resume_evidence(
                "codex",
                "019f0000-0000-7000-8000-000000000099",
                codex_home=str(self.codex_home),
                expected_cwd=str(self.cwd),
            )

    def test_resume_evidence_rejects_ambiguous_and_contradictory_codex_files(self):
        session_id = "019f0000-0000-7000-8000-000000000008"
        self.write_codex_meta(session_id, name=f"rollout-a-{session_id}.jsonl")
        self.write_codex_meta(session_id, name=f"rollout-b-{session_id}.jsonl")
        with self.assertRaisesRegex(
            runtime.SessionError,
            "session_identity_mismatch",
        ):
            runtime.validate_resume_evidence(
                "codex",
                session_id,
                codex_home=str(self.codex_home),
                expected_cwd=str(self.cwd),
            )

        other_id = "019f0000-0000-7000-8000-000000000009"
        mismatch = self.write_codex_meta(
            other_id,
            name=f"rollout-{session_id}.jsonl",
        )
        for old in mismatch.parent.glob(f"*{session_id}*.jsonl"):
            if old != mismatch:
                old.unlink()
        with self.assertRaisesRegex(
            runtime.SessionError,
            "session_identity_mismatch",
        ):
            runtime.validate_resume_evidence(
                "codex",
                session_id,
                codex_home=str(self.codex_home),
                expected_cwd=str(self.cwd),
            )

    def test_resume_evidence_rejects_symlinked_provider_transcript(self):
        session_id = "019f0000-0000-7000-8000-000000000010"
        target = self.write_codex_meta(
            session_id,
            name="private-target.jsonl",
        )
        linked = target.with_name(f"rollout-{session_id}.jsonl")
        linked.symlink_to(target)
        with self.assertRaisesRegex(
            runtime.SessionError,
            "session_identity_mismatch",
        ):
            runtime.validate_resume_evidence(
                "codex",
                session_id,
                codex_home=str(self.codex_home),
                expected_cwd=str(self.cwd),
            )

    def test_resume_evidence_privately_normalizes_owned_regular_transcript(self):
        session_id = "019f0000-0000-7000-8000-000000000011"
        path = self.write_codex_meta(session_id)
        os.chmod(path, 0o644)
        self.assertEqual(
            runtime.validate_resume_evidence(
                "codex",
                session_id,
                codex_home=str(self.codex_home),
                expected_cwd=str(self.cwd),
            ),
            str(path),
        )
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def fresh_handoff_fixture(self):
        transaction_id = "tx-one"
        transactions_root = self.root / "transactions"
        transaction_dir = transactions_root / transaction_id
        handoff_dir = transaction_dir / "handoffs"
        handoff_dir.mkdir(parents=True, mode=0o700)
        os.chmod(transaction_dir, 0o700)
        os.chmod(handoff_dir, 0o700)
        lock_path = self.root / "provider-switch.lock"
        record = {
            "agent_id": "node-1/main:Engineer-1",
            "backend": "codex",
            "model": "gpt-test",
            "provider_profile": "codex-primary",
            "cwd": str(self.cwd),
            "lifecycle": "owner",
            "owner_task_id": "task-1234",
            "boss_id": "node-1/main:Boss",
            "is_master": False,
            "taskspec_sha256": "a" * 64,
            "role_contract_sha256": "b" * 64,
            "role_contract_version": 1,
        }
        snapshot = {
            key: record.get(key)
            for key in (
                "agent_id",
                "backend",
                "model",
                "provider_profile",
                "cwd",
                "lifecycle",
                "owner_task_id",
                "boss_id",
                "is_master",
                "taskspec_sha256",
                "role_contract_sha256",
                "role_contract_version",
            )
        }
        handoff = {
            "agent": {"agent_id": record["agent_id"], "summary": "continue"},
            "terminalTail": "bounded progress",
            "snapshot": snapshot,
        }
        handoff_path = handoff_dir / "agent.json"
        for path, payload in (
            (lock_path, {"transaction": transaction_id}),
            (
                transaction_dir / "state.json",
                {
                    "transaction": transaction_id,
                    "phase": "stopped",
                    "targetProfile": "codex-primary",
                },
            ),
            (transaction_dir / "roster.json", [record]),
            (handoff_path, handoff),
        ):
            path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
            os.chmod(path, 0o600)
        return transactions_root, lock_path, handoff_path, record

    def test_fresh_handoff_accepts_owned_stopped_private_transaction(self):
        roots, lock_path, handoff_path, record = self.fresh_handoff_fixture()
        authorized = runtime.validate_fresh_handoff(
            str(roots),
            str(lock_path),
            "tx-one",
            str(handoff_path),
            record["agent_id"],
        )
        self.assertEqual(authorized["record"], record)
        self.assertEqual(
            authorized["handoff"]["terminalTail"],
            "bounded progress",
        )

    def test_fresh_handoff_rejects_wrong_lock_or_non_stopped_phase(self):
        roots, lock_path, handoff_path, record = self.fresh_handoff_fixture()
        lock_path.write_text(
            json.dumps({"transaction": "tx-other"}) + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            runtime.SessionError,
            "fresh_handoff_not_authorized",
        ):
            runtime.validate_fresh_handoff(
                str(roots),
                str(lock_path),
                "tx-one",
                str(handoff_path),
                record["agent_id"],
            )

        lock_path.write_text(
            json.dumps({"transaction": "tx-one"}) + "\n",
            encoding="utf-8",
        )
        state_path = roots / "tx-one" / "state.json"
        state_path.write_text(
            json.dumps({"transaction": "tx-one", "phase": "prepared"}) + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            runtime.SessionError,
            "fresh_handoff_not_authorized",
        ):
            runtime.validate_fresh_handoff(
                str(roots),
                str(lock_path),
                "tx-one",
                str(handoff_path),
                record["agent_id"],
            )

    def test_fresh_handoff_rejects_outside_private_path_and_snapshot_mismatch(self):
        roots, lock_path, handoff_path, record = self.fresh_handoff_fixture()
        outside = self.root / "outside.json"
        outside.write_text(handoff_path.read_text(encoding="utf-8"), encoding="utf-8")
        os.chmod(outside, 0o600)
        with self.assertRaisesRegex(
            runtime.SessionError,
            "fresh_handoff_not_authorized",
        ):
            runtime.validate_fresh_handoff(
                str(roots),
                str(lock_path),
                "tx-one",
                str(outside),
                record["agent_id"],
            )

        payload = json.loads(handoff_path.read_text(encoding="utf-8"))
        payload["snapshot"]["cwd"] = str(self.root / "wrong")
        handoff_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        os.chmod(handoff_path, 0o600)
        with self.assertRaisesRegex(
            runtime.SessionError,
            "fresh_handoff_not_authorized",
        ):
            runtime.validate_fresh_handoff(
                str(roots),
                str(lock_path),
                "tx-one",
                str(handoff_path),
                record["agent_id"],
            )

    def test_fresh_handoff_rejects_symlinked_handoff_and_lock(self):
        roots, lock_path, handoff_path, record = self.fresh_handoff_fixture()
        linked_handoff = handoff_path.parent / "linked.json"
        linked_handoff.symlink_to(handoff_path)
        with self.assertRaisesRegex(
            runtime.SessionError,
            "fresh_handoff_not_authorized",
        ):
            runtime.validate_fresh_handoff(
                str(roots),
                str(lock_path),
                "tx-one",
                str(linked_handoff),
                record["agent_id"],
            )

        real_lock = self.root / "provider-switch-real.lock"
        lock_path.replace(real_lock)
        lock_path.symlink_to(real_lock)
        with self.assertRaisesRegex(
            runtime.SessionError,
            "fresh_handoff_not_authorized",
        ):
            runtime.validate_fresh_handoff(
                str(roots),
                str(lock_path),
                "tx-one",
                str(handoff_path),
                record["agent_id"],
            )


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(AgentSessionContract)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("PASS provider session identity primitives")
    raise SystemExit(0 if result.wasSuccessful() else 1)
