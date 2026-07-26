#!/usr/bin/env python3
"""Bounded, redacted projection of automatic-memory control and receipts."""
from __future__ import annotations

import json
from pathlib import Path

from memory_canary import load_control


PUBLIC_MEMORY_STATUSES = {
    "not_requested", "disabled", "memory_applied", "insufficient_evidence",
    "memory_unavailable", "memory_invalid_response", "memory_budget_exceeded",
    "error",
}
PUBLIC_MEMORY_LEVELS = {"fast", "deep", "exhaustive", "emergency"}


def _public_count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def get_memory_projection(runtime_dir, task_id=""):
    runtime = Path(runtime_dir).resolve()
    control = load_control(runtime)
    latest = None
    events = runtime / "taskspec-events.jsonl"
    if events.exists() and not events.is_symlink():
        try:
            size = events.stat().st_size
            with events.open("rb") as stream:
                stream.seek(max(0, size - 524_288))
                if size > 524_288:
                    stream.readline()
                lines = stream.read(524_288).decode("utf-8").splitlines()
            for line in lines:
                value = json.loads(line)
                if not isinstance(value, dict) or (task_id and value.get("taskId") != task_id):
                    continue
                status = value.get("memoryStatus")
                level = value.get("selectedLevel")
                levels = value.get("levelsAttempted")
                if status not in PUBLIC_MEMORY_STATUSES:
                    continue
                if level is not None and level not in PUBLIC_MEMORY_LEVELS:
                    continue
                if not isinstance(levels, list) or any(item not in PUBLIC_MEMORY_LEVELS for item in levels):
                    continue
                latency = value.get("retrievalLatencyMs")
                if not isinstance(latency, int) or isinstance(latency, bool) or latency < 0:
                    latency = _public_count(value.get("elapsedMilliseconds"))
                latest = {
                    "taskId": str(value.get("taskId") or "")[:128],
                    "projectSlug": str(value.get("projectSlug") or "")[:64],
                    "status": status,
                    "level": level,
                    "levelsAttempted": levels[:4],
                    "latencyMs": latency,
                    "examinedCount": _public_count(value.get("examinedCount")),
                    "claimCount": min(3, _public_count(value.get("embeddedClaimCount"))),
                    "estimatedTokens": min(300, _public_count(value.get("estimatedTokens"))),
                    "provenanceComplete": value.get("provenanceComplete") is True,
                    "reasonCode": str(value.get("reasonCode") or "")[:64] or None,
                    "providerTokens": value.get("aiUsage") if isinstance(value.get("aiUsage"), dict) else "not_measured",
                }
        except (OSError, UnicodeError, json.JSONDecodeError):
            latest = None
    mode = control.get("mode", "manual_canary" if control.get("enabled") else "off")
    return {
        "mode": mode,
        "enabled": mode != "off",
        "controlRevision": control["revision"],
        "last": latest,
    }
