from __future__ import annotations

from .history_fixture import LoadedHistoryFixture
from .history_runner import (
    HistoryDeepRetriever,
    HistoryGraphRetriever,
    HistoryHybridRetriever,
)
from .exhaustive import BoundedExhaustiveSearch
from .retrieval import CanonicalRetriever, SQLiteFTSRetriever, tokenize


PROJECT_REPOSITORY = "LordCripto-Hub/Project-Factory"
PROJECT_SLUG = "project-factory"


def _claims(results) -> list[dict[str, str]]:
    return [
        {
            "id": result.event.event_id,
            "projectSlug": PROJECT_SLUG,
            "content": result.event.content,
            "sourceUri": result.event.provenance,
            "sourceType": result.event.event_type,
            "status": "canonical",
        }
        for result in results
    ]


class HistoryMemoryStore:
    """One locked fixture and one FTS index shared by every recall level."""

    def __init__(self, loaded: LoadedHistoryFixture):
        if loaded.repo_slug != PROJECT_REPOSITORY:
            raise ValueError("project_mismatch")
        self.loaded = loaded
        self.index = SQLiteFTSRetriever(loaded.fixture.events)
        self.fast_retriever = HistoryGraphRetriever(
            CanonicalRetriever(self.index, loaded.fixture.events),
            loaded.fixture.events,
        )
        self.deep_retriever = HistoryDeepRetriever(
            self.index,
            loaded.fixture.events,
            expansions=loaded.fixture.expansion_map,
        )
        self.hybrid_retriever = HistoryHybridRetriever(
            self.fast_retriever,
            self.deep_retriever,
            alias_tokens=loaded.fixture.expansion_map,
            max_escalations=1,
        )
        self.exhaustive_retriever = BoundedExhaustiveSearch(
            loaded.fixture.events,
            loaded.fixture.expansion_map,
        )

    @staticmethod
    def _limit(limit):
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 3:
            raise ValueError("invalid_recall_limit")

    def fast(self, query, limit):
        self._limit(limit)
        query = str(query or "").strip()
        rows = self.fast_retriever.retrieve(query, limit=limit)
        tokens = set(tokenize(query))
        needs_deep = (
            bool(tokens & self.hybrid_retriever.alias_tokens)
            or {"next", "after"}.issubset(tokens)
            or not rows
        )
        return {
            "claims": [] if needs_deep else _claims(rows),
            "examinedCount": len(rows),
        }

    def deep(self, query, limit):
        self._limit(limit)
        rows = self.deep_retriever.retrieve(str(query or "").strip(), limit=limit)
        return {"claims": _claims(rows), "examinedCount": len(rows)}

    def exhaustive(self, query, limit):
        self._limit(limit)
        outcome = self.exhaustive_retriever.retrieve(
            str(query or "").strip(), max_examined=100, limit=limit
        )
        return {
            "claims": _claims(outcome.results),
            "examinedCount": outcome.examined_count,
        }

    def close(self):
        self.index.close()


def recall_history_claims(
    loaded: LoadedHistoryFixture,
    query: str,
    *,
    limit: int,
) -> list[dict[str, str]]:
    if loaded.repo_slug != PROJECT_REPOSITORY:
        raise ValueError("project_mismatch")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 3:
        raise ValueError("invalid_recall_limit")
    query = str(query or "").strip()
    if not query:
        raise ValueError("question_required")

    store = HistoryMemoryStore(loaded)
    try:
        outcome = store.hybrid_retriever.retrieve(query, limit=limit)
        return _claims(outcome.results)
    finally:
        store.close()
