from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .models import GoldQuestion, MemoryEvent
from .retrieval import RetrievalResult


@dataclass(frozen=True)
class QuestionScore:
    question_id: str
    recall_at_3: float
    recall_at_10: float
    answer_correct: bool
    provenance_coverage: float
    superseded_hits: int
    false_memory: bool
    injected_context_tokens: int


def _recall(relevant: set[str], results: tuple[RetrievalResult, ...], limit: int) -> float:
    if not relevant:
        return 1.0
    found = {result.event.event_id for result in results[:limit]}
    return len(relevant & found) / len(relevant)


def score_question(
    question: GoldQuestion,
    results: Iterable[RetrievalResult],
    all_events: Iterable[MemoryEvent],
) -> QuestionScore:
    ranked = tuple(results)
    relevant = set(question.relevant_event_ids)
    returned_ids = {result.event.event_id for result in ranked[:10]}
    returned_values = {
        result.event.fact_value for result in ranked[:10] if result.event.fact_value is not None
    }
    superseded_ids = {event.supersedes for event in all_events if event.supersedes}
    superseded_hits = sum(1 for result in ranked[:10] if result.event.event_id in superseded_ids)

    if question.expected_absent:
        false_memory = any(
            result.event.fact_key == question.target_fact_key for result in ranked[:10]
        )
        answer_correct = not false_memory
    elif question.family == "multi_hop":
        false_memory = False
        answer_correct = relevant.issubset(returned_ids) and set(question.expected_values).issubset(
            returned_values
        )
    else:
        false_memory = False
        answer_correct = set(question.expected_values).issubset(returned_values)

    if not relevant:
        provenance_coverage = 1.0
    else:
        evidenced = {
            result.event.event_id
            for result in ranked[:10]
            if result.event.event_id in relevant and bool(result.event.provenance)
        }
        provenance_coverage = len(evidenced) / len(relevant)

    return QuestionScore(
        question_id=question.question_id,
        recall_at_3=_recall(relevant, ranked, 3),
        recall_at_10=_recall(relevant, ranked, 10),
        answer_correct=answer_correct,
        provenance_coverage=provenance_coverage,
        superseded_hits=superseded_hits,
        false_memory=false_memory,
        injected_context_tokens=sum(result.event.approx_tokens for result in ranked[:10]),
    )
