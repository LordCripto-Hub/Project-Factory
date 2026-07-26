#!/usr/bin/env python3
"""Bounded, secret-safe provider health receipts."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time


REASONS = {
    "authenticated": "session_active",
    "expired": "authentication_rejected",
    "quota_exhausted": "quota_rejected",
    "unreachable": "transport_failure",
    "unknown": "insufficient_evidence",
    "process_dead": "process_missing",
}
SECRET = re.compile(
    r"(?i)(authorization\s*:\s*bearer|token|password|secret|api[_-]?key)\s*[=:]?\s*\S+"
)


def classify_provider_health(evidence: dict) -> str:
    if evidence.get("processAlive") is False:
        return "process_dead"
    if evidence.get("authRejected") is True:
        return "expired"
    if evidence.get("quotaRejected") is True:
        return "quota_exhausted"
    if evidence.get("transportFailure") is True:
        return "unreachable"
    if evidence.get("authenticatedInteraction") is True:
        return "authenticated"
    return "unknown"


def _sanitize(value: object) -> str:
    text = str(value or "")[:240]
    return SECRET.sub("[REDACTED]", text)


def build_health_receipt(
    provider: str,
    profile: str,
    agent_id: str,
    evidence: dict,
    source: str,
    now: float | None = None,
) -> dict:
    state = classify_provider_health(evidence)
    return {
        "provider": str(provider or "")[:32],
        "profile": str(profile or "")[:128],
        "agentId": str(agent_id or "")[:256],
        "state": state,
        "reasonCode": REASONS[state],
        "observedAt": float(time.time() if now is None else now),
        "source": str(source or "unknown")[:32],
        "diagnosticRef": _sanitize(evidence.get("diagnosticRef")),
    }


def _health_dir(runtime_dir: str) -> Path:
    return Path(runtime_dir).resolve() / "provider-health"


def write_health_receipt(runtime_dir: str, receipt: dict) -> str:
    directory = _health_dir(runtime_dir)
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    key = hashlib.sha256(receipt["agentId"].encode()).hexdigest()[:24]
    destination = directory / f"{key}.json"
    descriptor, temporary = tempfile.mkstemp(prefix=".health-", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(receipt, stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
        os.chmod(destination, 0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return str(destination)


def read_health_receipts(
    runtime_dir: str,
    stale_after: float,
    now: float | None = None,
) -> list[dict]:
    observed_now = float(time.time() if now is None else now)
    rows = []
    directory = _health_dir(runtime_dir)
    if not directory.exists():
        return rows
    for path in sorted(directory.glob("*.json")):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        row["stale"] = observed_now - float(row.get("observedAt", 0)) > stale_after
        rows.append(row)
    return rows
