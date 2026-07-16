#!/usr/bin/env python3
"""Task evidence and worker handoff contracts."""
from __future__ import annotations

import argparse
import hashlib
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str, path: Path):
    module_dir = str(path.parent)
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
    loader = importlib.machinery.SourceFileLoader(name + os.urandom(4).hex(), str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class TaskEvidenceContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = {
            "INSTALL_DIR": str(ROOT),
            "QUEUE_SECRET": "verify-secret",
            "HOST_ID": "verify-host",
            "NIGHTWATCH_IDLE_MIN": "9999",
        }
        with patch.dict(os.environ, env, clear=False):
            cls.server = load_script("todo_server_evidence_", ROOT / "bin" / "todo-server.py")
            cls.mp = load_script("mp_evidence_", ROOT / "bin" / "mp")

    def test_normalized_tasks_have_a_small_evidence_policy_contract(self):
        task = self.server.normalize_task({})
        self.assertEqual(task["evidencePolicy"], "optional")

    def test_proof_paths_reject_traversal_and_require_authenticated_routing(self):
        self.assertIsNone(self.server.proof_file_path("..", "board.v2.json"))
        self.assertIsNone(self.server.proof_file_path("task-1", "../board.v2.json"))
        valid = self.server.proof_file_path("task-1", "screen.png")
        self.assertIsNotNone(valid)
        source = (ROOT / "bin" / "todo-server.py").read_text(encoding="utf-8")
        auth = source.index("if not self.auth_kind():return self.json")
        proof_route = source.index('m=re.fullmatch(r"/todo/proof/')
        self.assertLess(auth, proof_route)
    def test_binary_upload_is_a_downloadable_file(self):
        kind = self.server.classify_media(
            "", "/todo/proof/task/file.zip", "result.zip", "application/zip"
        )
        self.assertEqual(kind, "file")

    def test_only_explicit_http_urls_are_link_evidence(self):
        self.assertTrue(self.server.is_explicit_http_url("https://example.test/a"))
        self.assertTrue(self.server.is_explicit_http_url("HTTP://example.test/a"))
        self.assertFalse(self.server.is_explicit_http_url("bien como van los fix"))
        self.assertEqual(self.server.classify_media("link", "bien como van los fix"), "text")
        self.assertEqual(self.server.classify_media("link", "https://example.test/a"), "link")

    def test_legacy_relative_link_proof_migrates_to_comment(self):
        board = {"version": 2, "order": ["task-1"], "tasks": {"task-1": {
            "id": "task-1", "comments": [], "proofs": [{"id": "old", "kind": "link",
            "url": "como van los fix", "body": "", "by": "CEO", "ts": 1}]
        }}}
        self.assertTrue(self.server.migrate(board))
        task = board["tasks"]["task-1"]
        self.assertEqual(task["proofs"], [])
        self.assertEqual(task["comments"][0]["body"], "como van los fix")

    def test_ui_composer_routes_text_and_urls_separately(self):
        source = (ROOT / "bin" / "todos.html").read_text(encoding="utf-8")
        self.assertIn("function isDirectUrl", source)
        self.assertIn("/^https?:\\/\\/[^\\s]+$/i.test(text)", source)
        self.assertIn("if(url)await api('/todo/proof'", source)
        self.assertIn("else await api('/todo/comment'", source)
        self.assertIn("e.key==='Enter'&&!e.shiftKey", source)

    def test_proof_metadata_is_auditable(self):
        content = b"visual evidence"
        proof = self.server.proof_metadata(
            content, "screen.png", "image/png", "verify-host/main:eng-1"
        )
        self.assertEqual(proof["filename"], "screen.png")
        self.assertEqual(proof["mime"], "image/png")
        self.assertEqual(proof["bytes"], len(content))
        self.assertEqual(proof["sha256"], hashlib.sha256(content).hexdigest())
        self.assertEqual(proof["by"], "verify-host/main:eng-1")

    def test_required_evidence_blocks_done_until_proof_and_verification(self):
        task = self.server.normalize_task({"evidencePolicy": "required", "proofs": []})
        self.assertEqual(
            self.server.done_transition_error(task, "done", True),
            "evidence_required",
        )
        task["proofs"].append({"kind": "text", "body": "tests pass"})
        self.assertEqual(
            self.server.done_transition_error(task, "done", False),
            "verification_required",
        )
        self.assertIsNone(self.server.done_transition_error(task, "done", True))

    def test_reopening_clears_stale_verification(self):
        self.assertFalse(
            self.server.transition_verified("done", "working", None, True)
        )
        self.assertTrue(
            self.server.transition_verified("review", "done", True, False)
        )

    def test_mp_complete_accepts_files_and_urls_as_evidence(self):
        calls = []
        uploads = []
        notices = []
        self.mp.http_json = lambda path, method="GET", body=None, **kwargs: calls.append((path, method, body)) or {"ok": True}
        self.mp.http_multipart = lambda path, fields, file_path: uploads.append((path, fields, file_path)) or {"ok": True}
        self.mp.notify_agent = lambda target, message: notices.append((target, message))

        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "screen.png"
            artifact.write_bytes(b"png")
            env = {
                "AGENT_ID": "verify-host/main:eng-1",
                "OWNER_TASK_ID": "task-1",
                "BOSS_ID": "verify-host/main:Boss",
            }
            with patch.dict(os.environ, env, clear=False):
                self.mp.complete(argparse.Namespace(
                    summary=["Implemented", "the", "screen"],
                    proof=[],
                    proof_file=[str(artifact)],
                    proof_url=["http://127.0.0.1:9933/result"],
                ))

        self.assertEqual(uploads[0][0], "/todo/proof")
        self.assertEqual(uploads[0][1]["task_id"], "task-1")
        self.assertTrue(any(c[0] == "/todo/proof" and c[2]["kind"] == "link" for c in calls))
        self.assertTrue(any(c[0] == "/todo/status" and c[2]["state"] == "review" for c in calls))
        self.assertEqual(len(notices), 1)

    def test_parser_exposes_repeatable_evidence_options(self):
        ns = self.mp.parser().parse_args([
            "complete", "done", "--proof-file", "screen.png", "--proof-url", "https://example.test/result"
        ])
        self.assertEqual(ns.proof_file, ["screen.png"])
        self.assertEqual(ns.proof_url, ["https://example.test/result"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
