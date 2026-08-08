from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import re
import statistics
from typing import Iterable

from .history_fixture import LoadedHistoryFixture
from .models import BenchmarkFixture, GoldQuestion, MemoryEvent
from .retrieval import (
    CanonicalRetriever,
    ExhaustiveDeepProxy,
    RetrievalOutcome,
    RetrievalResult,
    Retriever,
    SQLiteFTSRetriever,
    tokenize,
)
from .scoring import QuestionScore, score_question


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
SHA_ANCHOR_RE = re.compile(r"(?<![0-9a-f])[0-9a-f]{12,40}(?![0-9a-f])")


def _deduplicate(
    results: Iterable[RetrievalResult],
    limit: int,
) -> tuple[RetrievalResult, ...]:
    selected: list[RetrievalResult] = []
    seen: set[str] = set()
    for result in results:
        if result.event.event_id in seen:
            continue
        selected.append(result)
        seen.add(result.event.event_id)
        if len(selected) == limit:
            break
    return tuple(selected)


class HistoryGraphRetriever:
    """Adds deterministic commit relations to a lexical retriever."""

    def __init__(self, inner: Retriever, events: Iterable[MemoryEvent]):
        self.inner = inner
        self.events = tuple(events)
        self.commits = tuple(event for event in self.events if event.event_type == "commit")
        self.commit_index = {
            event.event_id.removeprefix("commit-"): index
            for index, event in enumerate(self.commits)
        }
        self.by_anchor: dict[str, tuple[MemoryEvent, ...]] = {}
        for commit in self.commits:
            anchor = commit.event_id.removeprefix("commit-")
            related = tuple(
                event
                for event in self.events
                if anchor in event.provenance
            )
            self.by_anchor[anchor] = related

    @staticmethod
    def _project_file_relation(event: MemoryEvent) -> MemoryEvent:
        marker = "#path="
        if event.event_type != "file_change" or marker not in event.provenance:
            return event
        path = event.provenance.split(marker, 1)[1]
        return replace(event, fact_value=path)

    def _find_anchor(self, query: str) -> str | None:
        match = SHA_ANCHOR_RE.search(query.casefold())
        if match is None:
            return None
        supplied = match.group(0)
        matches = [anchor for anchor in self.commit_index if anchor.startswith(supplied)]
        return matches[0] if len(matches) == 1 else None

    def retrieve(self, query: str, limit: int = 10) -> tuple[RetrievalResult, ...]:
        lexical = self.inner.retrieve(query, limit=limit)
        anchor = self._find_anchor(query)
        if anchor is None:
            return lexical

        tokens = set(tokenize(query))
        graph: list[RetrievalResult] = []
        if {"next", "after"}.issubset(tokens):
            current = self.commit_index[anchor]
            if current + 1 < len(self.commits):
                graph.append(
                    RetrievalResult(
                        self.commits[current + 1],
                        float("inf"),
                        "history_graph",
                    )
                )
        elif {"change", "file"}.issubset(tokens) or "jointly" in tokens:
            graph.extend(
                RetrievalResult(
                    self._project_file_relation(event),
                    float("inf"),
                    "history_graph",
                )
                for event in self.by_anchor[anchor][:2]
            )
        return _deduplicate((*graph, *lexical), limit)


class HistoryDeepRetriever(HistoryGraphRetriever):
    """Full-corpus deterministic proxy plus history relations."""

    def __init__(
        self,
        events_or_retriever: Iterable[MemoryEvent] | Retriever,
        events: Iterable[MemoryEvent],
        *,
        expansions: dict[str, tuple[str, ...]] | None = None,
    ):
        deep = CanonicalRetriever(
            ExhaustiveDeepProxy(events_or_retriever, expansions=expansions),
            events,
        )
        super().__init__(deep, events)


class HistoryHybridRetriever:
    """Bounded router for aliases, successor relations, and lexical misses."""

    def __init__(
        self,
        fast: Retriever,
        deep: Retriever,
        *,
        alias_tokens: Iterable[str],
        max_escalations: int,
    ):
        self.fast = fast
        self.deep = deep
        self.alias_tokens = frozenset(alias_tokens)
        self.max_escalations = max_escalations
        self.used_escalations = 0

    def retrieve(self, query: str, limit: int = 10) -> RetrievalOutcome:
        fast_results = self.fast.retrieve(query, limit=limit)
        top_score = fast_results[0].score if fast_results else 0.0
        tokens = set(tokenize(query))
        must_escalate = (
            bool(tokens & self.alias_tokens)
            or {"next", "after"}.issubset(tokens)
            or not fast_results
        )
        if not must_escalate:
            return RetrievalOutcome(fast_results, False, top_score)
        if self.used_escalations >= self.max_escalations:
            return RetrievalOutcome(fast_results, False, top_score, True)

        self.used_escalations += 1
        deep_results = self.deep.retrieve(query, limit=limit)
        return RetrievalOutcome(
            _deduplicate((*deep_results, *fast_results), limit),
            True,
            top_score,
        )


@dataclass(frozen=True)
class _Executed:
    question: GoldQuestion
    score: QuestionScore
    escalated: bool
    escalation_blocked: bool
    result_event_ids: tuple[str, ...]
    result_sources: tuple[str, ...]


def _scoring_corpus(
    fixture: BenchmarkFixture,
    question: GoldQuestion,
) -> tuple[MemoryEvent, ...]:
    if question.family != "multi_hop":
        return fixture.events
    historical_relation_ids = set(question.relevant_event_ids)
    return tuple(
        replace(event, supersedes=None)
        if event.supersedes in historical_relation_ids
        else event
        for event in fixture.events
    )


def _execute(
    fixture: BenchmarkFixture,
    retriever: Retriever | HistoryHybridRetriever,
    *,
    limit: int,
    hybrid: bool,
) -> list[_Executed]:
    rows: list[_Executed] = []
    for question in fixture.questions:
        raw = retriever.retrieve(question.query, limit=limit)
        if hybrid:
            assert isinstance(raw, RetrievalOutcome)
            results = raw.results
            escalated = raw.escalated
            blocked = raw.escalation_blocked
        else:
            assert isinstance(raw, tuple)
            results = raw
            escalated = False
            blocked = False
        rows.append(
            _Executed(
                question=question,
                score=score_question(
                    question,
                    results,
                    _scoring_corpus(fixture, question),
                ),
                escalated=escalated,
                escalation_blocked=blocked,
                result_event_ids=tuple(result.event.event_id for result in results),
                result_sources=tuple(result.source for result in results),
            )
        )
    return rows


def _percentile(values: list[int], fraction: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[int(round((len(ordered) - 1) * fraction))]


def _summary(rows: list[_Executed], *, families: bool = True) -> dict[str, object]:
    count = max(1, len(rows))
    result: dict[str, object] = {
        "question_count": len(rows),
        "recall_at_3": round(statistics.fmean(row.score.recall_at_3 for row in rows), 4),
        "recall_at_10": round(statistics.fmean(row.score.recall_at_10 for row in rows), 4),
        "answer_accuracy": round(sum(row.score.answer_correct for row in rows) / count, 4),
        "provenance_coverage": round(
            statistics.fmean(row.score.provenance_coverage for row in rows), 4
        ),
        "superseded_hits": sum(row.score.superseded_hits for row in rows),
        "false_memory_rate": round(sum(row.score.false_memory for row in rows) / count, 4),
        "mean_injected_context_tokens": round(
            statistics.fmean(row.score.injected_context_tokens for row in rows), 2
        ),
        "p95_injected_context_tokens": _percentile(
            [row.score.injected_context_tokens for row in rows], 0.95
        ),
        "escalation_rate": round(sum(row.escalated for row in rows) / count, 4),
        "escalation_blocked_rate": round(
            sum(row.escalation_blocked for row in rows) / count, 4
        ),
    }
    if families:
        result["families"] = {
            family: _summary(
                [row for row in rows if row.question.family == family],
                families=False,
            )
            for family in EXPECTED_FAMILIES
        }
        result["questions"] = [
            {
                **asdict(row.score),
                "family": row.question.family,
                "escalated": row.escalated,
                "escalation_blocked": row.escalation_blocked,
                "result_event_ids": list(row.result_event_ids),
                "result_sources": list(row.result_sources),
            }
            for row in rows
        ]
    return result


def _logical_digest(report: dict[str, object]) -> str:
    encoded = json.dumps(
        report,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def run_history_hybrid(
    loaded: LoadedHistoryFixture,
    *,
    limit: int = 10,
    max_escalations: int = 40,
) -> dict[str, object]:
    fixture = loaded.fixture
    sqlite_index = SQLiteFTSRetriever(fixture.events)
    canonical = CanonicalRetriever(sqlite_index, fixture.events)
    fast = HistoryGraphRetriever(canonical, fixture.events)
    deep = HistoryDeepRetriever(
        sqlite_index,
        fixture.events,
        expansions=fixture.expansion_map,
    )
    hybrid = HistoryHybridRetriever(
        fast,
        deep,
        alias_tokens=fixture.expansion_map,
        max_escalations=max_escalations,
    )
    try:
        fast_rows = _execute(fixture, fast, limit=limit, hybrid=False)
        hybrid_rows = _execute(fixture, hybrid, limit=limit, hybrid=True)
    finally:
        sqlite_index.close()

    variants = {
        "sqlite_fts_history_graph": _summary(fast_rows),
        "hybrid": _summary(hybrid_rows),
    }
    hybrid_summary = variants["hybrid"]
    assert isinstance(hybrid_summary, dict)
    observed_families = Counter(question.family for question in fixture.questions)
    gates = {
        "question_contract": (
            len(fixture.questions) == 100
            and observed_families == Counter(EXPECTED_FAMILIES)
        ),
        "recall_at_10": hybrid_summary["recall_at_10"] >= 0.95,
        "answer_accuracy": hybrid_summary["answer_accuracy"] >= 0.95,
        "provenance_coverage": hybrid_summary["provenance_coverage"] == 1.0,
        "no_superseded_hits": hybrid_summary["superseded_hits"] == 0,
        "false_memory_rate": hybrid_summary["false_memory_rate"] < 0.02,
        "no_blocked_escalations": hybrid_summary["escalation_blocked_rate"] == 0.0,
    }
    report: dict[str, object] = {
        "schema_version": 1,
        "dataset": {
            "name": loaded.dataset_name,
            "repo_slug": loaded.repo_slug,
            "source_sha": loaded.source_sha,
            "event_count": len(fixture.events),
            "question_count": len(fixture.questions),
            "alias_count": len(fixture.query_expansions),
        },
        "configuration": {
            "limit": limit,
            "max_escalations": max_escalations,
            "deep_proxy_is_real_model": False,
        },
        "variants": variants,
        "promotion_gates": gates,
    }
    report["logical_digest"] = _logical_digest(report)
    return report
