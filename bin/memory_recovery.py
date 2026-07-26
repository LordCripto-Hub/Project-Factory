#!/usr/bin/env python3
"""Ordered, bounded, provider-free coordination for hybrid-memory recall."""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import time


LEVELS = ("fast", "deep", "exhaustive", "emergency")
CLAIM_FIELDS = ("id", "projectSlug", "content", "sourceUri", "sourceType")


@dataclass(frozen=True)
class RecoveryLimits:
    deadline_seconds: float = 2.0
    max_claims: int = 3
    max_estimated_tokens: int = 300
    exhaustive_examined: int = 100


def estimate_tokens(value) -> int:
    text = value if isinstance(value, str) else json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return (len(text.encode("utf-8")) + 3) // 4


def _valid_limits(limits) -> bool:
    return (
        isinstance(limits, RecoveryLimits)
        and math.isfinite(limits.deadline_seconds)
        and limits.deadline_seconds > 0
        and 1 <= limits.max_claims <= 3
        and 1 <= limits.max_estimated_tokens <= 300
        and 1 <= limits.exhaustive_examined <= 100
    )


def _valid_claim(value) -> bool:
    return (
        isinstance(value, dict)
        and all(isinstance(value.get(field), str) and value[field].strip()
                for field in CLAIM_FIELDS)
        and value.get("projectSlug") == "project-factory"
    )


def _adapter_result(value):
    if isinstance(value, list) or isinstance(value, tuple):
        claims, examined = list(value), len(value)
    elif isinstance(value, dict) and set(value) == {"claims", "examinedCount"}:
        claims = value["claims"]
        examined = value["examinedCount"]
        if not isinstance(claims, list):
            raise ValueError("invalid_claims")
        if isinstance(examined, bool) or not isinstance(examined, int) or examined < 0:
            raise ValueError("invalid_examined_count")
    else:
        raise ValueError("invalid_adapter_response")
    return claims, examined


def _outcome(status, attempted, claims, started, clock, *, selected=None,
             examined=0, estimated_tokens=0, provenance=True, reason=None):
    elapsed = max(0.0, clock() - started)
    return {
        "status": status,
        "selectedLevel": selected,
        "levelsAttempted": list(attempted),
        "claims": list(claims),
        "elapsedMilliseconds": round(elapsed * 1000),
        "examinedCount": examined,
        "returnedCount": len(claims),
        "estimatedTokens": estimated_tokens,
        "provenanceComplete": provenance,
        "reasonCode": reason,
    }


def recover(query, adapters, *, limits=RecoveryLimits(),
            sufficient=lambda rows: bool(rows), clock=time.monotonic):
    started = clock()
    if (
        not isinstance(query, str)
        or not query.strip()
        or not isinstance(adapters, dict)
        or set(adapters) != set(LEVELS)
        or not all(callable(adapters[level]) for level in LEVELS)
        or not _valid_limits(limits)
    ):
        return _outcome(
            "memory_invalid_response", [], [], started, clock,
            provenance=False, reason="adapter_contract_invalid",
        )

    attempted = []
    examined = 0
    saw_unavailable = False
    saw_invalid = False
    for level in LEVELS:
        if clock() - started >= limits.deadline_seconds:
            return _outcome(
                "memory_unavailable", attempted, [], started, clock,
                examined=examined, reason="deadline_exceeded",
            )
        attempted.append(level)
        try:
            rows, level_examined = _adapter_result(
                adapters[level](query, limits.max_claims)
            )
        except (OSError, TimeoutError):
            saw_unavailable = True
            continue
        except (TypeError, ValueError):
            saw_invalid = True
            continue
        examined += level_examined
        if len(rows) > limits.max_claims or any(not _valid_claim(row) for row in rows):
            saw_invalid = True
            continue
        if not sufficient(rows):
            continue
        claims = [dict(row) for row in rows]
        token_count = estimate_tokens(claims)
        if token_count > limits.max_estimated_tokens:
            return _outcome(
                "memory_budget_exceeded", attempted, [], started, clock,
                selected=level, examined=examined,
                estimated_tokens=token_count, reason="token_budget_exceeded",
            )
        return _outcome(
            "memory_applied", attempted, claims, started, clock,
            selected=level, examined=examined,
            estimated_tokens=token_count, provenance=True,
        )

    if saw_invalid:
        return _outcome(
            "memory_invalid_response", attempted, [], started, clock,
            examined=examined, provenance=False,
            reason="adapter_response_invalid",
        )
    if saw_unavailable:
        return _outcome(
            "memory_unavailable", attempted, [], started, clock,
            examined=examined, reason="adapter_unavailable",
        )
    return _outcome(
        "insufficient_evidence", attempted, [], started, clock,
        examined=examined, reason="no_sufficient_evidence",
    )
