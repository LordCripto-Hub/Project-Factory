#!/usr/bin/env python3
"""Secret-safe, bounded operator telemetry projection."""
from __future__ import annotations

import time


HEALTH_STATES = {
    "authenticated",
    "expired",
    "quota_exhausted",
    "unreachable",
    "unknown",
    "process_dead",
}


def session_alias(provider: str, session_id: str) -> str:
    provider = str(provider or "").strip().lower()
    session_id = str(session_id or "").strip()
    if not provider or len(session_id) < 8:
        return "unavailable"
    return f"{provider[:32]}:{session_id[-8:]}"


def _role(record: dict) -> str:
    agent_id = str(record.get("agent_id") or "")
    if record.get("is_master") or agent_id.endswith(":Boss"):
        return "boss"
    if agent_id.endswith(":Nightwatch") or "/nightwatch:" in agent_id:
        return "nightwatch"
    return "engineer"


def _health_by_agent(receipts: list[dict]) -> dict[str, dict]:
    selected = {}
    for receipt in receipts if isinstance(receipts, list) else []:
        if not isinstance(receipt, dict):
            continue
        agent_id = str(receipt.get("agentId") or "")
        state = str(receipt.get("state") or "")
        if not agent_id or state not in HEALTH_STATES:
            continue
        try:
            observed_at = float(receipt.get("observedAt") or 0)
        except (TypeError, ValueError):
            continue
        current = selected.get(agent_id)
        if current is None or observed_at > current["observedAt"]:
            selected[agent_id] = {
                "state": state,
                "reasonCode": str(receipt.get("reasonCode") or "")[:64],
                "stale": bool(receipt.get("stale")),
                "observedAt": observed_at,
            }
    return selected


def _usage(record: dict, usage_reader) -> dict:
    try:
        snapshot = usage_reader(record) if usage_reader else {}
    except Exception:
        snapshot = {}
    provider = str(record.get("backend") or "")
    session_id = str(record.get("session_id") or "")
    usage = snapshot.get("usage") if isinstance(snapshot, dict) else None
    if (
        snapshot.get("provider") != provider
        or snapshot.get("sessionId") != session_id
        or not isinstance(usage, dict)
    ):
        return {"measurement": "not_measured"}
    input_tokens = usage.get("inputTokens")
    output_tokens = usage.get("outputTokens")
    if (
        isinstance(input_tokens, bool)
        or not isinstance(input_tokens, int)
        or input_tokens < 0
        or isinstance(output_tokens, bool)
        or not isinstance(output_tokens, int)
        or output_tokens < 0
    ):
        return {"measurement": "not_measured"}
    return {
        "measurement": "measured",
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
    }


def build_operator_telemetry(
    roster: list[dict],
    health_receipts: list[dict],
    *,
    usage_reader=None,
    observed_at: float | None = None,
) -> dict:
    observed = float(time.time() if observed_at is None else observed_at)
    health = _health_by_agent(health_receipts)
    rows = []
    for record in roster if isinstance(roster, list) else []:
        if not isinstance(record, dict) or record.get("retired"):
            continue
        agent_id = str(record.get("agent_id") or "")
        if not agent_id:
            continue
        provider = str(record.get("backend") or "")[:32]
        receipt = health.get(agent_id) or {
            "state": "unknown",
            "reasonCode": "insufficient_evidence",
            "stale": True,
            "observedAt": 0.0,
        }
        rows.append({
            "agentId": agent_id[:256],
            "role": _role(record),
            "provider": provider,
            "model": str(record.get("model") or "")[:128],
            "profile": str(record.get("provider_profile") or "")[:128],
            "sessionAlias": session_alias(provider, record.get("session_id")),
            "health": receipt,
            "usage": _usage(record, usage_reader),
        })
    order = {"boss": 0, "nightwatch": 1, "engineer": 2}
    rows.sort(key=lambda row: (order[row["role"]], row["agentId"]))
    return {"ok": True, "observedAt": observed, "agents": rows[:100]}
