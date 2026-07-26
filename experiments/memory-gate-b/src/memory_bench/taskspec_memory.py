from __future__ import annotations

from .history_fixture import LoadedHistoryFixture
from .history_runner import (
    HistoryDeepRetriever,
    HistoryGraphRetriever,
    HistoryHybridRetriever,
)
from .retrieval import CanonicalRetriever, SQLiteFTSRetriever


PROJECT_REPOSITORY = "LordCripto-Hub/Project-Factory"
PROJECT_SLUG = "project-factory"


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

    index = SQLiteFTSRetriever(loaded.fixture.events)
    try:
        fast = HistoryGraphRetriever(
            CanonicalRetriever(index, loaded.fixture.events),
            loaded.fixture.events,
        )
        deep = HistoryDeepRetriever(
            index,
            loaded.fixture.events,
            expansions=loaded.fixture.expansion_map,
        )
        hybrid = HistoryHybridRetriever(
            fast,
            deep,
            alias_tokens=loaded.fixture.expansion_map,
            max_escalations=1,
        )
        outcome = hybrid.retrieve(query, limit=limit)
        return [
            {
                "id": result.event.event_id,
                "projectSlug": PROJECT_SLUG,
                "content": result.event.content,
                "sourceUri": result.event.provenance,
                "sourceType": result.event.event_type,
                "status": "canonical",
            }
            for result in outcome.results
        ]
    finally:
        index.close()
