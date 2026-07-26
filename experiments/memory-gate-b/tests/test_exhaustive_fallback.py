#!/usr/bin/env python3
"""Contracts for bounded exhaustive exploration of the existing event store."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from memory_bench.exhaustive import BoundedExhaustiveSearch
from memory_bench.models import MemoryEvent


def event(event_id, sequence, content, *, event_type="commit", fact_key=None,
          provenance=None, topic="repository-change"):
    return MemoryEvent(
        event_id=event_id,
        sequence=sequence,
        topic=topic,
        content=content,
        fact_key=fact_key,
        provenance=provenance or f"git+repo://Project-Factory#{event_id}",
        event_type=event_type,
    )


class BoundedExhaustiveFallbackTests(unittest.TestCase):
    def setUp(self):
        self.events = (
            event("commit-a", 1, "Reject stale tmux windows", fact_key="commit:abc123:subject"),
            event("file-b", 2, "bin/mp validates exact agent readiness",
                  event_type="file_change", fact_key="path:bin/mp:latest-subject"),
            event("task-c", 3, "Boss preserves task ownership for engineer-3",
                  event_type="task", fact_key="task:card-7:owner"),
        )
        self.aliases = {"session": ("commit:abc123:subject", "path:bin/mp:latest-subject")}

    def test_search_reuses_event_objects_and_preserves_provenance(self):
        search = BoundedExhaustiveSearch(self.events, self.aliases)
        outcome = search.retrieve("stale tmux", max_examined=100, limit=3)
        self.assertIs(search.events[0], self.events[0])
        self.assertEqual(outcome.results[0].event.event_id, "commit-a")
        self.assertTrue(outcome.results[0].event.provenance)
        self.assertLessEqual(outcome.examined_count, 100)
        self.assertLessEqual(len(outcome.results), 3)

    def test_alias_regex_and_structured_filters_are_bounded(self):
        search = BoundedExhaustiveSearch(self.events, self.aliases)
        alias = search.retrieve("session", max_examined=8, limit=3)
        self.assertTrue({"commit-a", "file-b"} & {
            row.event.event_id for row in alias.results
        })
        filtered = search.retrieve(
            "ownership",
            filters={
                "regex": r"engineer-\d",
                "event_type": {"task"},
                "task": "card-7",
                "agent": "engineer-3",
                "after_sequence": 2,
                "before_sequence": 3,
            },
            max_examined=10,
            limit=3,
        )
        self.assertEqual([row.event.event_id for row in filtered.results], ["task-c"])

    def test_file_commit_and_invalid_regex_filters_fail_closed(self):
        search = BoundedExhaustiveSearch(self.events, self.aliases)
        file_rows = search.retrieve(
            "validates", filters={"file": "bin/mp"}, max_examined=10, limit=3
        )
        self.assertEqual([row.event.event_id for row in file_rows.results], ["file-b"])
        commit_rows = search.retrieve(
            "stale", filters={"commit": "abc123"}, max_examined=10, limit=3
        )
        self.assertEqual([row.event.event_id for row in commit_rows.results], ["commit-a"])
        invalid = search.retrieve(
            "anything", filters={"regex": "["}, max_examined=10, limit=3
        )
        self.assertEqual(invalid.results, ())

    def test_search_creates_no_corpus_database_or_files(self):
        with tempfile.TemporaryDirectory() as temp:
            before = set(Path(temp).iterdir())
            BoundedExhaustiveSearch(self.events, self.aliases).retrieve(
                "publisher approval", max_examined=20, limit=3
            )
            self.assertEqual(set(Path(temp).iterdir()), before)

    def test_hard_limits_reject_invalid_requests(self):
        search = BoundedExhaustiveSearch(self.events, self.aliases)
        for kwargs in (
            {"max_examined": 101, "limit": 3},
            {"max_examined": 10, "limit": 4},
            {"max_examined": True, "limit": 3},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                search.retrieve("query", **kwargs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
