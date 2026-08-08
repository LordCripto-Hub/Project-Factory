#!/usr/bin/env python3
from __future__ import annotations

import os
import re

from agent_session import HANDOFF_SNAPSHOT_FIELDS


PUBLIC_HANDOFF_FIELDS = (
    "agent_id",
    "backend",
    "model",
    "provider_profile",
    "lifecycle",
    "owner_task_id",
    "boss_id",
    "is_master",
    "state",
    "status",
    "summary",
)

__all__ = [
    "PUBLIC_HANDOFF_FIELDS",
    "build_handoff",
    "redact",
    "sanitize_terminal_tail",
]


def redact(text: str) -> str:
    value = str(text or "")
    substitutions = (
        (
            re.compile(
                r"(?i)authorization\s*:\s*bearer\s+[A-Za-z0-9._-]+"
            ),
            "Authorization: Bearer [REDACTED]",
        ),
        (
            re.compile(
                r"(?i)(?<![A-Za-z0-9])(?:tskey-auth-|sk-|ghp_|github_pat_)"
                r"[A-Za-z0-9._-]+"
            ),
            "[REDACTED_TOKEN]",
        ),
        (
            re.compile(r"(?i)[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}"),
            "[REDACTED_EMAIL]",
        ),
        (
            re.compile(r"(?i)[A-Z]:\\Users\\[^\r\n]+"),
            "[REDACTED_WINDOWS_PATH]",
        ),
        (
            re.compile(r"/" + r"Users/[^/\r\n]+(?:/[^\r\n]*)?"),
            "[REDACTED_MACOS_PATH]",
        ),
    )
    for pattern, replacement in substitutions:
        value = pattern.sub(replacement, value)
    return value


def sanitize_terminal_tail(text: str) -> str:
    sensitive_assignment = re.compile(
        r"(?i)(?:\b[A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|"
        r"PRIVATE_KEY|COOKIE|SESSION)[A-Z0-9_]*\b|\bset-cookie\b)\s*[:=]"
    )
    jwt = re.compile(
        r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"
        r"(?:\.[A-Za-z0-9_-]+)?\b"
    )
    credential_path = re.compile(
        r"/home/[^/\s]+/(?:(?:\.codex|\.claude|\.config)/|"
        r"mypeople/run/provider-homes/)[^\s]+"
    )
    userinfo = re.compile(r"(?i)(https?://)[^/@\s]+@")
    output = []
    in_private_key = False
    for raw_line in str(text or "").splitlines():
        line = raw_line
        if "-----BEGIN " in line and "PRIVATE KEY-----" in line:
            in_private_key = True
            output.append("[REDACTED_PRIVATE_KEY]")
            continue
        if in_private_key:
            if "-----END " in line and "PRIVATE KEY-----" in line:
                in_private_key = False
            continue
        line = redact(line)
        line = credential_path.sub("[REDACTED_CREDENTIAL_PATH]", line)
        line = userinfo.sub(r"\1[REDACTED_USERINFO]@", line)
        line = jwt.sub("[REDACTED_JWT]", line)
        if sensitive_assignment.search(line):
            line = "[REDACTED_SENSITIVE_LINE]"
        output.append(line)
    return "\n".join(output)


def build_handoff(record: dict, terminal_tail: str, limit: int = 4000) -> dict:
    public = {}
    for key in PUBLIC_HANDOFF_FIELDS:
        if key not in record:
            continue
        value = record[key]
        public[key] = redact(value) if isinstance(value, str) else value
    bounded = max(0, int(limit))
    tail = sanitize_terminal_tail(terminal_tail)
    if bounded:
        tail = tail[-bounded:]
    else:
        tail = ""
    snapshot = {
        field: (
            os.path.realpath(str(record.get(field) or ""))
            if field == "cwd"
            else record.get(field)
        )
        for field in HANDOFF_SNAPSHOT_FIELDS
    }
    return {"agent": public, "terminalTail": tail, "snapshot": snapshot}
