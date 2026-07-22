from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "experiments" / "memory-gate-b"
OLD_DATASET = EXPERIMENT / "datasets" / "project-factory-history-80dce6f86632"
NEW_DATASET = EXPERIMENT / "datasets" / "project-factory-history-039a62988625"
OLD_LOCK = EXPERIMENT / "docker" / "history-hybrid.dataset-lock.json"
NEW_LOCK = EXPERIMENT / "docker" / "history-hybrid-039a62988625.dataset-lock.json"
OLD_REPORT = EXPERIMENT / "reports" / "comparison-offline-2026-07-22.json"

NEW_SHA = "039a62988625369f3f86c055cd476b0080395daa"
NEW_NAME = "project-factory-history-039a62988625"
EXPECTED_FILES = {
    "aliases.json",
    "events.jsonl",
    "manifest.json",
    "questions.jsonl",
    "validation.json",
}
HISTORICAL_HASHES = {
    "docker/history-hybrid.dataset-lock.json":
        "f45b08636a09e4c184943a219affbe0c9945e6143cac3479f7d3c1b811a1bb63",
    "reports/comparison-offline-2026-07-22.json":
        "e064add0142eb65566b379cbc252937cc80756836853df7c2caa91ca2d4eebbd",
    "datasets/project-factory-history-80dce6f86632/aliases.json":
        "84b5c5d0d7b5bd5b8a42c63079bb88b46a53d4f0acbd7ab52855da460db26f35",
    "datasets/project-factory-history-80dce6f86632/events.jsonl":
        "38146f1d7922c7e03d8c6b07b2c78a6dfa40cf039eb9a192fd38bd402b6cf015",
    "datasets/project-factory-history-80dce6f86632/manifest.json":
        "2b59a23dbd2b7dfbd6ec589bd3a10d2cb4f53e98a26900f2f17276b8818d154e",
    "datasets/project-factory-history-80dce6f86632/questions.jsonl":
        "80813c8ad4283543e6d7f80d75f5e6c0a5c7282384721808afa69efeb700a3ee",
    "datasets/project-factory-history-80dce6f86632/validation.json":
        "f3451091ecc73683bb3a23efd48af09a3bd729eb5a9296bc649bfa515a7b5490",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class MemoryDatasetRefreshContract(unittest.TestCase):
    def test_historical_evidence_is_byte_identical(self):
        for relative, expected in HISTORICAL_HASHES.items():
            path = EXPERIMENT / relative
            self.assertTrue(path.is_file(), relative)
            self.assertEqual(sha256(path), expected, relative)

    def test_current_sha_dataset_is_complete_and_independently_locked(self):
        self.assertTrue(NEW_DATASET.is_dir(), "current-SHA dataset is missing")
        self.assertTrue(NEW_LOCK.is_file(), "current-SHA lock is missing")
        self.assertEqual({path.name for path in NEW_DATASET.iterdir()}, EXPECTED_FILES)

        manifest = json.loads((NEW_DATASET / "manifest.json").read_text(encoding="utf-8"))
        lock = json.loads(NEW_LOCK.read_text(encoding="utf-8"))
        self.assertEqual(manifest["source_sha"], NEW_SHA)
        self.assertEqual(lock["source_sha"], NEW_SHA)
        self.assertEqual(lock["dataset_dir"], NEW_NAME)
        self.assertEqual(lock["repo_slug"], "LordCripto-Hub/Project-Factory")
        self.assertEqual(set(lock["files"]), EXPECTED_FILES)
        for name, expected in lock["files"].items():
            self.assertEqual(sha256(NEW_DATASET / name), expected, name)

        self.assertEqual(manifest["question_count"], 100)
        self.assertTrue(
            json.loads((NEW_DATASET / "validation.json").read_text(encoding="utf-8"))["passed"]
        )


if __name__ == "__main__":
    unittest.main()
