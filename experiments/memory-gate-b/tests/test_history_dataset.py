from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

try:
    history_dataset = importlib.import_module("memory_bench.history_dataset")
    IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - asserted as the RED state
    history_dataset = None
    IMPORT_ERROR = exc


EXPECTED_FAMILIES = {
    "exact": 20,
    "semantic": 20,
    "temporal": 15,
    "multi_hop": 15,
    "contradiction": 10,
    "continuation": 10,
    "failure": 5,
    "negative": 5,
}


class HistoryDatasetTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNone(
            IMPORT_ERROR,
            f"repository-owned history dataset builder is missing: {IMPORT_ERROR}",
        )

    def test_reads_only_committed_git_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self._init_repo(repo)
            tracked = repo / "src" / "worker.py"
            tracked.parent.mkdir(parents=True)
            tracked.write_text("first\n", encoding="utf-8")
            first = self._commit(repo, "feat: add worker", 1)
            tracked.write_text("second\n", encoding="utf-8")
            second = self._commit(repo, "fix: correct worker", 2)
            (repo / "untracked-secret.txt").write_text("not evidence\n", encoding="utf-8")

            source_sha, commits = history_dataset.read_git_history(repo, second)

            self.assertEqual(source_sha, second)
            self.assertEqual([commit.sha for commit in commits], [first, second])
            self.assertNotIn("untracked-secret.txt", repr(commits))
            self.assertNotIn(str(repo), repr(commits))

    def test_refuses_source_sha_that_is_not_a_commit(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self._init_repo(repo)
            path = repo / "README.md"
            path.write_text("fixture\n", encoding="utf-8")
            self._commit(repo, "feat: initialize", 1)

            with self.assertRaisesRegex(ValueError, "source SHA must resolve to a commit"):
                history_dataset.read_git_history(repo, "refs/heads/missing")

    def test_builds_exactly_100_grounded_questions_deterministically(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._build_long_history(Path(temp))

            first = history_dataset.build_history_dataset(
                repo, "HEAD", "example/project-factory"
            )
            second = history_dataset.build_history_dataset(
                repo, first.source_sha, "example/project-factory"
            )

            self.assertEqual(first, second)
            self.assertEqual(len(first.questions), 100)
            self.assertEqual(
                Counter(question.family for question in first.questions),
                EXPECTED_FAMILIES,
            )
            event_ids = {event.event_id for event in first.events}
            for question in first.questions:
                self.assertTrue(set(question.relevant_event_ids).issubset(event_ids))

    def test_writes_canonical_validated_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._build_long_history(root / "repo")
            dataset = history_dataset.build_history_dataset(
                repo, "HEAD", "example/project-factory"
            )
            first = root / "first"
            second = root / "second"

            validation = history_dataset.write_history_dataset(dataset, first)
            history_dataset.write_history_dataset(dataset, second)

            expected = {
                "aliases.json",
                "events.jsonl",
                "manifest.json",
                "questions.jsonl",
                "validation.json",
            }
            self.assertTrue(validation["passed"])
            self.assertEqual({path.name for path in first.iterdir()}, expected)
            for name in expected:
                self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())
            manifest = json.loads((first / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["source_sha"], dataset.source_sha)
            self.assertEqual(manifest["question_count"], 100)

    def _build_long_history(self, repo: Path) -> Path:
        repo.mkdir(parents=True, exist_ok=True)
        self._init_repo(repo)
        base = datetime(2024, 1, 1, tzinfo=timezone.utc)
        for index in range(120):
            path = repo / "src" / f"module-{index % 20:02d}.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"revision {index}\n", encoding="utf-8")
            subject = (
                f"fix: repair module {index:03d}"
                if index % 17 == 0
                else f"feat: evolve module {index:03d}"
            )
            self._commit_at(repo, subject, base + timedelta(seconds=index))
        return repo

    def _init_repo(self, repo: Path) -> None:
        self._git(repo, "init")
        self._git(repo, "config", "user.name", "Dataset Test")
        self._git(repo, "config", "user.email", "dataset@example.invalid")

    def _commit(self, repo: Path, subject: str, second: int) -> str:
        return self._commit_at(
            repo,
            subject,
            datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=second),
        )

    def _commit_at(self, repo: Path, subject: str, value: datetime) -> str:
        self._git(repo, "add", ".")
        timestamp = value.isoformat()
        env = {
            **os.environ,
            "GIT_AUTHOR_DATE": timestamp,
            "GIT_COMMITTER_DATE": timestamp,
        }
        self._git(repo, "commit", "-m", subject, env=env)
        return self._git(repo, "rev-parse", "HEAD")

    @staticmethod
    def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
        completed = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
        )
        return completed.stdout.strip()


if __name__ == "__main__":
    unittest.main()
