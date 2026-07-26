#!/usr/bin/env python3
"""Pure contracts for bounded automatic Project Factory memory recall."""
from __future__ import annotations

import re


ALLOWED_PROJECT = "project-factory"
QUERY_MAX_CHARS = 800
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]+")


def _clean_line(value) -> str:
    without_controls = _CONTROL_RE.sub(" ", str(value or ""))
    return " ".join(without_controls.split())


def _task_fragments(task: dict) -> list[str]:
    fragments: list[str] = []
    seen: set[str] = set()
    for value in (
        task.get("text"),
        task.get("doneCondition"),
        task.get("contextQuestion"),
    ):
        for raw_line in str(value or "").splitlines() or [str(value or "")]:
            clean = _clean_line(raw_line)
            folded = clean.casefold()
            if clean and folded not in seen:
                seen.add(folded)
                fragments.append(clean)
    return fragments


def derive_memory_query(task: dict, max_chars: int = QUERY_MAX_CHARS) -> str:
    """Compile provider-free recall text from public task contract fields only."""
    if not isinstance(task, dict):
        return ""
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < 1:
        return ""
    return " | ".join(_task_fragments(task))[:max_chars].rstrip(" |")


def memory_eligibility(task: dict) -> str:
    """Return a stable exclusion reason or ``eligible`` for automatic recall."""
    if not isinstance(task, dict) or task.get("projectSlug") != ALLOWED_PROJECT:
        return "project_denied"
    marker = (task.get("experiment") or {}).get("memory_comparison") or {}
    if task.get("test") is True and marker.get("arm") == "baseline":
        return "comparison_baseline"
    if not derive_memory_query(task):
        return "empty_query"
    return "eligible"
