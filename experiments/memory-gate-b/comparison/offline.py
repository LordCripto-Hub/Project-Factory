from __future__ import annotations

import hashlib
import json
from pathlib import Path
import statistics
import time
from typing import Callable, Iterable

from memory_bench.history_fixture import LoadedHistoryFixture
from memory_bench.history_runner import (
    HistoryDeepRetriever,
    HistoryGraphRetriever,
    HistoryHybridRetriever,
)
from memory_bench.retrieval import CanonicalRetriever, SQLiteFTSRetriever

from .contracts import ComparisonCase


def canonical_receipt(receipt: dict) -> bytes:
    return (
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _logical_payload(receipt: dict) -> dict:
    payload = json.loads(json.dumps(receipt))
    payload.pop("logical_digest", None)
    payload["aggregates"].pop("median_retrieval_latency_ms", None)
    for row in payload["cases"]:
        row.pop("retrieval_latency_ms", None)
    return payload


def _logical_digest(receipt: dict) -> str:
    return hashlib.sha256(canonical_receipt(_logical_payload(receipt))).hexdigest()


def run_offline_comparison(
    loaded: LoadedHistoryFixture,
    cases: Iterable[ComparisonCase],
    *,
    fixture_path: str | Path,
    clock_ns: Callable[[], int] = time.perf_counter_ns,
    top_k: int = 3,
    max_escalations: int = 40,
) -> dict:
    selected_cases = tuple(cases)
    question_by_id = {
        question.question_id: question for question in loaded.fixture.questions
    }
    sqlite_index = SQLiteFTSRetriever(loaded.fixture.events)
    canonical = CanonicalRetriever(sqlite_index, loaded.fixture.events)
    fast = HistoryGraphRetriever(canonical, loaded.fixture.events)
    deep = HistoryDeepRetriever(
        sqlite_index,
        loaded.fixture.events,
        expansions=loaded.fixture.expansion_map,
    )
    hybrid = HistoryHybridRetriever(
        fast,
        deep,
        alias_tokens=loaded.fixture.expansion_map,
        max_escalations=max_escalations,
    )
    rows = []
    try:
        for case in selected_cases:
            question = question_by_id[case.question_id]
            started = clock_ns()
            outcome = hybrid.retrieve(question.query, limit=top_k)
            elapsed_ms = round((clock_ns() - started) / 1_000_000, 3)
            selected_ids = [result.event.event_id for result in outcome.results]
            rejected_ids = sorted(set(selected_ids) & set(case.rejected_evidence_ids))
            passed = (
                set(case.allowed_evidence_ids).issubset(selected_ids)
                and not rejected_ids
                and not outcome.escalation_blocked
            )
            rows.append(
                {
                    "alias": case.alias,
                    "class": case.case_class,
                    "question_id": case.question_id,
                    "retrieval_mode": (
                        "deep_proxy" if outcome.escalated else "sqlite_fts_history_graph"
                    ),
                    "escalated": outcome.escalated,
                    "escalation_blocked": outcome.escalation_blocked,
                    "selected_evidence_ids": selected_ids,
                    "rejected_evidence_ids": rejected_ids,
                    "retrieval_latency_ms": elapsed_ms,
                    "estimated_memory_context_tokens": sum(
                        result.event.approx_tokens for result in outcome.results
                    ),
                    "passed": passed,
                }
            )
    finally:
        sqlite_index.close()

    latencies = [row["retrieval_latency_ms"] for row in rows]
    token_estimates = [row["estimated_memory_context_tokens"] for row in rows]
    receipt = {
        "schema_version": 1,
        "dataset": {
            "name": loaded.dataset_name,
            "repo_slug": loaded.repo_slug,
            "source_sha": loaded.source_sha,
        },
        "fixture_sha256": hashlib.sha256(Path(fixture_path).read_bytes()).hexdigest(),
        "configuration": {
            "top_k": top_k,
            "max_escalations": max_escalations,
            "deep_proxy_is_real_model": False,
        },
        "metrics": {
            "retrieval_latency": "actual",
            "memory_context_tokens": "estimated",
            "provider_tokens": "not_measured",
        },
        "cases": rows,
        "aggregates": {
            "case_count": len(rows),
            "passed_count": sum(row["passed"] for row in rows),
            "escalation_count": sum(row["escalated"] for row in rows),
            "median_retrieval_latency_ms": statistics.median(latencies) if latencies else 0,
            "median_estimated_memory_context_tokens": statistics.median(token_estimates)
            if token_estimates
            else 0,
        },
        "passed": len(rows) == 6 and all(row["passed"] for row in rows),
    }
    receipt["logical_digest"] = _logical_digest(receipt)
    return receipt
