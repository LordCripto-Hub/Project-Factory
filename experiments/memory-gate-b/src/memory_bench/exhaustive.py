from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from .models import MemoryEvent
from .retrieval import RetrievalResult, tokenize


@dataclass(frozen=True)
class ExhaustiveOutcome:
    results: tuple[RetrievalResult, ...]
    examined_count: int
    queries: tuple[str, ...]


def _searchable(event: MemoryEvent) -> str:
    return " ".join(
        value for value in (
            event.topic,
            event.content,
            event.fact_key or "",
            event.fact_value or "",
            event.provenance,
            event.event_type,
        ) if value
    ).casefold()


def _bounded_int(value, minimum, maximum, code):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(code)
    return value


def _regex_filter(filters):
    expression = filters.get("regex")
    if expression is None:
        return None, True
    if not isinstance(expression, str) or not expression or len(expression) > 256:
        return None, False
    try:
        return re.compile(expression, re.IGNORECASE), True
    except re.error:
        return None, False


def _matches_filters(event, searchable, filters, expression):
    event_types = filters.get("event_type")
    if event_types is not None:
        if not isinstance(event_types, (set, frozenset, tuple, list)):
            return False
        if event.event_type not in event_types:
            return False
    for key in ("file", "commit", "task", "agent"):
        expected = filters.get(key)
        if expected is not None and (
            not isinstance(expected, str) or expected.casefold() not in searchable
        ):
            return False
    after = filters.get("after_sequence")
    before = filters.get("before_sequence")
    if after is not None and (isinstance(after, bool) or not isinstance(after, int) or event.sequence < after):
        return False
    if before is not None and (isinstance(before, bool) or not isinstance(before, int) or event.sequence > before):
        return False
    if expression is not None and expression.search(searchable) is None:
        return False
    return True


class BoundedExhaustiveSearch:
    """Explore existing immutable events without materializing another store."""

    def __init__(self, events: Iterable[MemoryEvent], aliases=None):
        self.events = tuple(events)
        self.aliases = {
            str(key).casefold(): tuple(str(value) for value in values)
            for key, values in dict(aliases or {}).items()
        }

    def retrieve(self, query, *, filters=None, max_examined=100, limit=3):
        max_examined = _bounded_int(max_examined, 1, 100, "invalid_max_examined")
        limit = _bounded_int(limit, 1, 3, "invalid_recall_limit")
        query = " ".join(str(query or "").split())
        if not query:
            raise ValueError("question_required")
        filters = dict(filters or {})
        expression, regex_valid = _regex_filter(filters)
        if not regex_valid:
            return ExhaustiveOutcome((), 0, (query,))

        refinements = [query]
        for token in tokenize(query):
            refinements.extend(self.aliases.get(token.casefold(), ()))
        refinements = list(dict.fromkeys(refinements))
        ranked = {}
        examined = 0
        executed = []
        for refinement in refinements:
            executed.append(refinement)
            refinement_tokens = set(tokenize(refinement))
            refinement_folded = refinement.casefold()
            for event in self.events:
                if examined >= max_examined:
                    break
                examined += 1
                searchable = _searchable(event)
                if not _matches_filters(event, searchable, filters, expression):
                    continue
                searchable_tokens = set(tokenize(searchable))
                overlap = len(refinement_tokens & searchable_tokens)
                exact_fact = event.fact_key and event.fact_key.casefold() == refinement_folded
                if not overlap and not exact_fact and refinement_folded not in searchable:
                    continue
                score = float(overlap + (3 if exact_fact else 0) + 1)
                candidate = RetrievalResult(event, score, "bounded_exhaustive")
                previous = ranked.get(event.event_id)
                if previous is None or candidate.score > previous.score:
                    ranked[event.event_id] = candidate
            if examined >= max_examined or len(ranked) >= limit:
                break
        rows = tuple(sorted(
            ranked.values(),
            key=lambda row: (-row.score, -row.event.sequence, row.event.event_id),
        )[:limit])
        return ExhaustiveOutcome(rows, examined, tuple(executed))
