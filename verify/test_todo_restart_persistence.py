#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
SECRET = "restart-persistence-secret"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class TodoRestartPersistenceE2E(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.runtime = Path(self.temp.name)
        self.port = free_port()
        self.board = self.runtime / "todos" / "board.v2.json"
        self.roster = self.runtime / "run" / "roster.json"
        self.roster.parent.mkdir(parents=True)
        self.roster.write_text("[]", encoding="utf-8")
        self.process = None
        self.start_server()

    def tearDown(self):
        self.stop_server()

    def start_server(self):
        env = {
            **os.environ,
            "PYTHONPATH": str(ROOT / "bin"),
            "INSTALL_DIR": str(self.runtime),
            "BOARD_PATH": str(self.board),
            "ROSTER_PATH": str(self.roster),
            "QUEUE_SECRET": SECRET,
            "HOST_ID": "verify-host",
            "BOSS_AGENT": "main:Boss",
            "BIND_ADDR": "127.0.0.1",
            "TODO_PORT": str(self.port),
            "HUD_PORT": "1",
            "NIGHTWATCH_IDLE_MIN": "9999",
        }
        self.process = subprocess.Popen(
            [sys.executable, str(ROOT / "bin" / "todo-server.py")],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            try:
                if self.request("GET", "/health")[0] == 200:
                    return
            except OSError:
                time.sleep(0.05)
        stderr = self.process.stderr.read().decode(errors="replace")
        self.fail(f"todo server did not start: {stderr[-1000:]}")

    def stop_server(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=5)
        if self.process and self.process.stderr:
            self.process.stderr.close()
        self.process = None

    def request(self, method, path, body=None, content_type="application/json"):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        raw = body
        if body is not None and content_type == "application/json":
            raw = json.dumps(body).encode()
        headers = {"X-Queue-Secret": SECRET}
        if raw is not None:
            headers["Content-Type"] = content_type
            headers["Content-Length"] = str(len(raw))
        connection.request(method, path, body=raw, headers=headers)
        response = connection.getresponse()
        payload = response.read()
        connection.close()
        decoded = json.loads(payload) if payload else {}
        return response.status, decoded

    def upload(self, task_id: str, content: bytes):
        boundary = "mypeople-restart-boundary"
        parts = []
        for name, value in (("task_id", task_id), ("by", "verify-host/main:Worker")):
            parts.append(
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode()
            )
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"evidence.txt\"\r\nContent-Type: text/plain\r\n\r\n".encode()
            + content
            + b"\r\n"
        )
        parts.append(f"--{boundary}--\r\n".encode())
        return self.request(
            "POST", "/todo/proof", b"".join(parts),
            f"multipart/form-data; boundary={boundary}",
        )

    def test_task_owner_comments_and_artifact_survive_restart_once(self):
        status, created = self.request("POST", "/todo/update", {
            "op": "add",
            "text": "Restart persistence contract",
            "projectSlug": "project-factory",
            "contextQuestion": "What state must survive?",
            "evidencePolicy": "required",
            "test": True,
            "by": "CEO",
        })
        self.assertEqual(status, 200)
        task_id = created["id"]
        owner = {
            "agent_id": "verify-host/main:Worker",
            "host": "verify-host",
            "state": "alive",
            "retired": False,
            "boss_id": "verify-host/main:Boss",
            "lifecycle": "owner",
            "owner_task_id": task_id,
        }
        self.roster.write_text(json.dumps([owner]), encoding="utf-8")
        status, _ = self.request("POST", "/todo/owner", {
            "action": "assign", "task_id": task_id,
            "agent_id": owner["agent_id"], "by": "verify-host/main:Boss",
        })
        self.assertEqual(status, 200)
        for author, text in (("CEO", "Please retain this."), (owner["agent_id"], "Acknowledged.")):
            status, _ = self.request("POST", "/todo/comment", {
                "task_id": task_id, "by": author, "body": text,
            })
            self.assertEqual(status, 200)
        artifact = b"restart-persistence-evidence\n"
        status, uploaded = self.upload(task_id, artifact)
        self.assertEqual(status, 200)
        status, _ = self.request("POST", "/todo/status", {
            "task_id": task_id, "state": "done", "verified": True, "by": "CEO",
        })
        self.assertEqual(status, 200)
        status, before_board = self.request("GET", "/todo/board")
        self.assertEqual(status, 200)
        before = before_board["tasks"][task_id]
        proof_url = uploaded["proof"]["url"]
        proof_sha = uploaded["proof"]["sha256"]
        self.assertEqual(proof_sha, hashlib.sha256(artifact).hexdigest())

        self.stop_server()
        self.start_server()

        status, after_board = self.request("GET", "/todo/board")
        self.assertEqual(status, 200)
        after = after_board["tasks"][task_id]
        self.assertEqual(after, before)
        self.assertEqual(list(after_board["tasks"]).count(task_id), 1)
        self.assertEqual(len(after["comments"]), 2)
        self.assertEqual(len(after["proofs"]), 1)
        self.assertEqual(len(after["ownerHistory"]), 2)
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{proof_url}",
            headers={"X-Queue-Secret": SECRET},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            restored = response.read()
        self.assertEqual(hashlib.sha256(restored).hexdigest(), proof_sha)


if __name__ == "__main__":
    unittest.main(verbosity=2)
