from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryEvent:
    event_id: str
    sequence: int
    topic: str
    content: str
    fact_key: str | None = None
    fact_value: str | None = None
    supersedes: str | None = None
    provenance: str = "synthetic://benchmark"
    event_type: str = "observation"

    @property
    def approx_tokens(self) -> int:
        return max(1, len(self.content.split()))


@dataclass(frozen=True)
class GoldQuestion:
    question_id: str
    family: str
    query: str
    relevant_event_ids: tuple[str, ...]
    expected_values: tuple[str, ...] = ()
    expected_absent: bool = False
    target_fact_key: str | None = None


@dataclass(frozen=True)
class BenchmarkFixture:
    seed: int
    target_tokens: int
    events: tuple[MemoryEvent, ...]
    questions: tuple[GoldQuestion, ...]
    query_expansions: tuple[tuple[str, tuple[str, ...]], ...] = ()
    benchmark_version: int = 1

    @property
    def approx_tokens(self) -> int:
        return sum(event.approx_tokens for event in self.events)

    @property
    def memory_map_approx_tokens(self) -> int:
        return sum(1 + len(expansions) for _, expansions in self.query_expansions)

    @property
    def expansion_map(self) -> dict[str, tuple[str, ...]]:
        return dict(self.query_expansions)
