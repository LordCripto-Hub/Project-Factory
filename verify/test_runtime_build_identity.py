#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
from runtime_identity import read_runtime_identity


class RuntimeBuildIdentityTests(unittest.TestCase):
    def test_reader_allow_lists_and_sanitizes_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "runtime-build.json"
            path.write_text(json.dumps({
                "schema": 1,
                "sha": "81c7515deadbeef",
                "build": "20260801T174621Z",
                "image": "mypeople-node:operator-reliability",
                "state": "live",
                "secret": "must-not-leak",
            }), encoding="utf-8")
            identity = read_runtime_identity(path)
            self.assertEqual(identity, {
                "schema": 1,
                "sha": "81c7515deadbeef",
                "build": "20260801T174621Z",
                "image": "mypeople-node:operator-reliability",
                "state": "live",
            })
            self.assertNotIn("secret", json.dumps(identity))

    def test_absent_or_invalid_manifest_is_unknown(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "missing.json"
            expected = {"schema": 1, "sha": "unknown", "build": "unknown", "image": "unknown", "state": "unknown"}
            self.assertEqual(read_runtime_identity(path), expected)
            path.write_text('{"schema":1,"sha":"../../bad"}', encoding="utf-8")
            self.assertEqual(read_runtime_identity(path), expected)

    def test_all_operator_surfaces_render_the_same_identity_contract(self):
        for name in ("todos.html", "terminal-graph.html", "dashboard.html"):
            page = (ROOT / "bin" / name).read_text(encoding="utf-8")
            self.assertIn("runtimeIdentity", page, name)
            self.assertIn("buildIdentity", page, name)
        todo = (ROOT / "bin" / "todo-server.py").read_text(encoding="utf-8")
        queue = (ROOT / "bin" / "queue-server.py").read_text(encoding="utf-8")
        self.assertIn("read_runtime_identity", todo)
        self.assertIn("read_runtime_identity", queue)

    def test_image_build_generates_manifest_from_explicit_provenance(self):
        dockerfile = (ROOT / "docker" / "Dockerfile.runtime-image").read_text(encoding="utf-8")
        for value in ("MYPEOPLE_SOURCE_SHA", "MYPEOPLE_BUILD_ID", "MYPEOPLE_IMAGE_REF"):
            self.assertIn(value, dockerfile)
        self.assertIn("runtime-build.json", dockerfile)
        self.assertIn("ARG MYPEOPLE_SOURCE_SHA=unknown", dockerfile)
        self.assertNotIn("19700101T000000Z", dockerfile)


if __name__ == "__main__":
    unittest.main(verbosity=2)
