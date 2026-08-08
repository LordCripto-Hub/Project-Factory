#!/usr/bin/env python3
"""Fail-closed backend selection for MyPeople agents."""
from __future__ import annotations


SUPPORTED = frozenset({"codex", "claude"})


class BackendResolutionError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _one(value) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, (list, tuple, set)):
        choices = {str(item).strip() for item in value if str(item).strip()}
        if len(choices) > 1:
            raise BackendResolutionError("backend_ambiguous")
        return next(iter(choices), "")
    return str(value).strip()


def resolve_backend(*, explicit="", profile="", policy="") -> dict:
    for source, raw in (
        ("explicit", explicit),
        ("profile", profile),
        ("routing_policy", policy),
    ):
        value = _one(raw)
        if not value:
            continue
        if value not in SUPPORTED:
            raise BackendResolutionError("backend_unsupported")
        return {"backend": value, "resolutionSource": source}
    raise BackendResolutionError("backend_unresolved")


def resolve_profile_backend(bindings: dict, agent_id: str) -> str:
    if not isinstance(bindings, dict):
        return ""
    selected = (bindings.get("agentProfiles") or {}).get(agent_id)
    selected = selected or bindings.get("globalProfile")
    return "codex" if selected else ""
