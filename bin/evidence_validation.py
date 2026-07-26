#!/usr/bin/env python3
"""Validation for portable task-evidence references."""
from __future__ import annotations

import re
import urllib.parse


WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")


def validate_evidence_url(value: str) -> dict:
    raw = str(value or "").strip()
    local = (
        raw.lower().startswith("file:")
        or bool(WINDOWS_DRIVE.match(raw))
        or raw.startswith("\\\\")
        or raw.startswith("/")
    )
    if local:
        return {
            "ok": False,
            "error": "local_evidence_path_rejected",
            "action": "use_proof_file",
        }
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return {"ok": False, "error": "invalid_evidence_url"}
    return {"ok": True, "url": raw}
