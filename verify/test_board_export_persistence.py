#!/usr/bin/env python3
from __future__ import annotations

import importlib.machinery
import os
import pathlib
import sys
import tempfile
import types
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
if "fcntl" not in sys.modules:
    fcntl = types.ModuleType("fcntl")
    fcntl.LOCK_EX = 2
    fcntl.LOCK_UN = 8
    fcntl.flock = lambda *_args, **_kwargs: None
    sys.modules["fcntl"] = fcntl


def load_exporter():
    return importlib.machinery.SourceFileLoader(
        "board_export_persistence_" + os.urandom(4).hex(),
        str(ROOT / "bin" / "board-export.py"),
    ).load_module()


class BoardExportPersistenceContract(unittest.TestCase):
    def test_default_repo_is_inside_the_durable_todos_volume(self):
        exporter = load_exporter()
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary).resolve()
            repo = pathlib.Path(exporter.default_repo(str(root), port=9933, host="node-1")).resolve()
            durable = (root / "todos" / "board-backup").resolve()
            self.assertTrue(repo.is_relative_to(durable))
            self.assertIn("node-1-9933-", repo.name)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(BoardExportPersistenceContract)
    )
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("PASS durable board exporter path contract")
