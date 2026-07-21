from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import math
import re
import sqlite3
from typing import Iterable, Protocol

from .models import MemoryEvent


TOKEN_RE = re.compile(r"[a-z0-9_]+")
QUERY_STOPWORDS = {"a", "an", "and", "can", "is", "of", "the", "to", "what", "which", "why"}
NORMALIZE = {
    "currently": "current",
    "served": "serve",
    "serves": "serve",
    "changing": "change",
    "changed": "change",
    "credentials": "credential",
    "decisions": "decision",
    "workers": "worker",
}


def tokenize(text: str) -> tuple[str, ...]:
    return tuple(NORMALIZE.get(token, token) for token in TOKEN_RE.findall(text.lower()))


@dataclass(frozen=True)
class RetrievalResult:
    event: MemoryEvent
    score: float
    source: str


@dataclass(frozen=True)
class RetrievalOutcome:
    results: tuple[RetrievalResult, ...]
    escalated: bool
    fast_top_score: float
    escalation_blocked: bool = False


class Retriever(Protocol):
    def retrieve(self, query: str, limit: int = 10) -> tuple[RetrievalResult, ...]: ...


class RecentWindowRetriever:
    def __init__(self, events: Iterable[MemoryEvent], window_events: int = 50):
        self.events = tuple(events)
        self.window_events = max(1, window_events)

    def retrieve(self, query: str, limit: int = 10) -> tuple[RetrievalResult, ...]:
        del query
        window = self.events[-self.window_events :]
        results = [
            RetrievalResult(event=event, score=float(event.sequence + 1), source="recent")
            for event in reversed(window)
        ]
        return tuple(results[:limit])


class CanonicalRetriever:
    """Removes events superseded by a newer canonical event before context injection."""

    def __init__(self, inner: Retriever, events: Iterable[MemoryEvent]):
        self.inner = inner
        self.superseded_ids = {event.supersedes for event in events if event.supersedes}

    def retrieve(self, query: str, limit: int = 10) -> tuple[RetrievalResult, ...]:
        expanded_limit = max(limit * 2, limit + len(self.superseded_ids))
        results = self.inner.retrieve(query, limit=expanded_limit)
        active = [result for result in results if result.event.event_id not in self.superseded_ids]
        return tuple(active[:limit])


class LexicalRetriever:
    """Small dependency-free BM25-like index used as the low-cost baseline."""

    def __init__(self, events: Iterable[MemoryEvent], *, source: str = "lexical"):
        self.events = tuple(events)
        self.source = source
        self.documents: list[Counter[str]] = []
        self.lengths: list[int] = []
        self.postings: dict[str, list[int]] = defaultdict(list)
        for index, event in enumerate(self.events):
            searchable = " ".join(
                part
                for part in (event.topic, event.content, event.fact_key or "", event.fact_value or "")
                if part
            )
            counts = Counter(tokenize(searchable))
            self.documents.append(counts)
            self.lengths.append(sum(counts.values()))
            for token in counts:
                self.postings[token].append(index)
        self.average_length = sum(self.lengths) / max(1, len(self.lengths))

    def retrieve(self, query: str, limit: int = 10) -> tuple[RetrievalResult, ...]:
        query_tokens = tuple(dict.fromkeys(tokenize(query)))
        candidate_ids: set[int] = set()
        for token in query_tokens:
            candidate_ids.update(self.postings.get(token, ()))

        scored: list[RetrievalResult] = []
        document_count = max(1, len(self.events))
        k1 = 1.5
        b = 0.75
        for index in candidate_ids:
            score = 0.0
            counts = self.documents[index]
            length = self.lengths[index]
            for token in query_tokens:
                frequency = counts.get(token, 0)
                if not frequency:
                    continue
                document_frequency = len(self.postings[token])
                inverse_frequency = math.log(
                    1.0 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5)
                )
                denominator = frequency + k1 * (1.0 - b + b * length / max(1.0, self.average_length))
                score += inverse_frequency * (frequency * (k1 + 1.0) / denominator)
            if score:
                scored.append(
                    RetrievalResult(event=self.events[index], score=round(score, 8), source=self.source)
                )

        scored.sort(key=lambda result: (-result.score, -result.event.sequence, result.event.event_id))
        return tuple(scored[:limit])


class SQLiteFTSRetriever:
    """SQLite FTS5 retrieval, matching the storage class used by Engram."""

    def __init__(self, events: Iterable[MemoryEvent]):
        self.events = tuple(events)
        self.connection = sqlite3.connect(":memory:")
        self.connection.execute(
            "CREATE VIRTUAL TABLE memory_fts USING fts5("
            "topic, content, fact_key, fact_value, tokenize='unicode61')"
        )
        rows = (
            (index + 1, event.topic, event.content, event.fact_key or "", event.fact_value or "")
            for index, event in enumerate(self.events)
        )
        with self.connection:
            self.connection.executemany(
                "INSERT INTO memory_fts(rowid, topic, content, fact_key, fact_value) "
                "VALUES (?, ?, ?, ?, ?)",
                rows,
            )

    def retrieve(self, query: str, limit: int = 10) -> tuple[RetrievalResult, ...]:
        tokens = tuple(dict.fromkeys(tokenize(query)))
        if not tokens:
            return ()
        match_query = " OR ".join(f'"{token}"' for token in tokens)
        rows = self.connection.execute(
            "SELECT rowid, bm25(memory_fts, 2.0, 1.0, 3.0, 3.0) AS rank "
            "FROM memory_fts WHERE memory_fts MATCH ? ORDER BY rank LIMIT ?",
            (match_query, limit),
        ).fetchall()
        return tuple(
            RetrievalResult(
                event=self.events[rowid - 1],
                score=round(-float(rank), 8),
                source="sqlite_fts",
            )
            for rowid, rank in rows
        )

    def close(self) -> None:
        self.connection.close()


TOPIC_EXPANSIONS = {
    "visual": ("ui", "theme", "scorpion", "amber"),
    "interface": ("ui", "theme"),
    "design": ("theme",),
    "credential": ("security", "provider", "references_only"),
    "worker": ("orchestration", "model", "switch"),
    "task": ("ownership", "taskspec", "checkpoint"),
    "port": ("runtime", "network", "localhost"),
    "chromatic": ("visual", "theme", "scorpion", "amber"),
    "shell": ("interface", "ui", "theme"),
}


def _expand_query(query: str, expansions: dict[str, tuple[str, ...]]) -> str:
    tokens = tokenize(query)
    additions: list[str] = []
    for token in tokens:
        additions.extend(expansions.get(token, ()))
    return " ".join((*tokens, *additions))


class TopicMapLexicalRetriever:
    def __init__(
        self,
        events: Iterable[MemoryEvent] | Retriever,
        *,
        expansions: dict[str, tuple[str, ...]] | None = None,
    ):
        self.lexical = events if hasattr(events, "retrieve") else LexicalRetriever(events)
        self.expansions = {**TOPIC_EXPANSIONS, **(expansions or {})}

    def retrieve(self, query: str, limit: int = 10) -> tuple[RetrievalResult, ...]:
        return self.lexical.retrieve(_expand_query(query, self.expansions), limit=limit)


DEEP_EXPANSIONS = {
    **TOPIC_EXPANSIONS,
    "boss": ("orchestration", "ownership", "selection"),
    "change": ("switch", "replacement", "preserve"),
    "identity": ("task_card", "task", "taskspec"),
    "without": ("preserve", "remain"),
    "why": ("therefore", "because", "owns"),
}


class ExhaustiveDeepProxy:
    """Deterministic full-corpus proxy. This is not an actual RLM invocation."""

    def __init__(
        self,
        events: Iterable[MemoryEvent] | Retriever,
        *,
        expansions: dict[str, tuple[str, ...]] | None = None,
    ):
        self.lexical = events if hasattr(events, "retrieve") else LexicalRetriever(events)
        self.expansions = {**DEEP_EXPANSIONS, **(expansions or {})}

    def retrieve(self, query: str, limit: int = 10) -> tuple[RetrievalResult, ...]:
        return self.lexical.retrieve(_expand_query(query, self.expansions), limit=limit)


class HybridRetriever:
    def __init__(
        self,
        fast: Retriever,
        deep: Retriever,
        *,
        minimum_fast_score: float = 2.0,
        minimum_fast_results: int = 2,
        minimum_query_coverage: float = 0.5,
        max_escalations: int | None = None,
        require_anchor_match: bool = False,
    ):
        self.fast = fast
        self.deep = deep
        self.minimum_fast_score = minimum_fast_score
        self.minimum_fast_results = minimum_fast_results
        self.minimum_query_coverage = minimum_query_coverage
        self.max_escalations = max_escalations
        self.require_anchor_match = require_anchor_match
        self.used_escalations = 0

    def retrieve(self, query: str, limit: int = 10) -> RetrievalOutcome:
        fast_results = self.fast.retrieve(query, limit=limit)
        top_score = fast_results[0].score if fast_results else 0.0
        query_tokens = {token for token in tokenize(query) if token not in QUERY_STOPWORDS}
        top_tokens: set[str] = set()
        if fast_results and query_tokens:
            top = fast_results[0].event
            top_tokens = set(
                tokenize(
                    " ".join(
                        part
                        for part in (top.topic, top.content, top.fact_key or "", top.fact_value or "")
                        if part
                    )
                )
            )
            query_coverage = len(query_tokens & top_tokens) / len(query_tokens)
        else:
            query_coverage = 0.0
        anchor_tokens = {
            token for token in query_tokens if "_" in token or any(character.isdigit() for character in token)
        }
        anchor_missing = (
            self.require_anchor_match
            and bool(anchor_tokens)
            and not bool(anchor_tokens & top_tokens)
        )
        escalate = (
            len(fast_results) < self.minimum_fast_results
            or top_score < self.minimum_fast_score
            or query_coverage < self.minimum_query_coverage
            or anchor_missing
        )
        if not escalate:
            return RetrievalOutcome(fast_results, False, top_score)

        if self.max_escalations is not None and self.used_escalations >= self.max_escalations:
            return RetrievalOutcome(fast_results, False, top_score, True)

        self.used_escalations += 1
        deep_results = self.deep.retrieve(query, limit=limit)
        combined: list[RetrievalResult] = list(deep_results)
        seen = {result.event.event_id for result in combined}
        for result in fast_results:
            if result.event.event_id not in seen:
                combined.append(result)
                seen.add(result.event.event_id)
        return RetrievalOutcome(tuple(combined[:limit]), True, top_score)
