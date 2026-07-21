#!/usr/bin/env python3
"""Private runtime control and receipts for the bounded memory canary."""
from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
import secrets
import time


CONTROL_NAME = "memory-canary-control.json"
CONTROL_FIELDS = {
    "schemaVersion",
    "enabled",
    "allowedProjects",
    "revision",
    "updatedAt",
}
ALLOWED_PROJECT = "project-factory"
RECEIPT_NAME = "memory-canary-events.jsonl"
MAX_RECEIPT_BYTES = 16_384
DEFAULT_CONTROL = {
    "schemaVersion": 1,
    "enabled": False,
    "allowedProjects": [ALLOWED_PROJECT],
    "revision": 1,
    "updatedAt": 0,
}


class MemoryCanaryError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _invalid():
    raise MemoryCanaryError("canary_control_invalid")


def _validate_control(value):
    if not isinstance(value, dict) or set(value) != CONTROL_FIELDS:
        _invalid()
    if value.get("schemaVersion") != 1:
        _invalid()
    if not isinstance(value.get("enabled"), bool):
        _invalid()
    projects = value.get("allowedProjects")
    if (
        not isinstance(projects, list)
        or projects != [ALLOWED_PROJECT]
        or len(projects) != len(set(projects))
    ):
        _invalid()
    revision = value.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        _invalid()
    updated_at = value.get("updatedAt")
    if (
        isinstance(updated_at, bool)
        or not isinstance(updated_at, (int, float))
        or not math.isfinite(updated_at)
        or updated_at < 0
    ):
        _invalid()
    return {
        "schemaVersion": 1,
        "enabled": value["enabled"],
        "allowedProjects": [ALLOWED_PROJECT],
        "revision": revision,
        "updatedAt": updated_at,
    }


def load_control(runtime_dir, *, missing_ok=True):
    root = Path(runtime_dir).resolve()
    path = root / CONTROL_NAME
    if not path.exists():
        if missing_ok:
            return copy.deepcopy(DEFAULT_CONTROL)
        raise MemoryCanaryError("canary_control_missing")
    try:
        if path.is_symlink():
            _invalid()
        raw = path.read_text(encoding="utf-8")
        return _validate_control(json.loads(raw))
    except MemoryCanaryError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as error:
        raise MemoryCanaryError("canary_control_invalid") from error


def set_control(
    runtime_dir,
    *,
    enabled,
    project=ALLOWED_PROJECT,
    now=time.time,
):
    if not isinstance(enabled, bool):
        raise MemoryCanaryError("canary_control_invalid")
    if project != ALLOWED_PROJECT:
        raise MemoryCanaryError("canary_project_denied")
    root = Path(runtime_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    current = load_control(root)
    if current["enabled"] is enabled:
        return current
    updated = {
        **current,
        "enabled": enabled,
        "revision": current["revision"] + 1,
        "updatedAt": now(),
    }
    updated = _validate_control(updated)
    path = root / CONTROL_NAME
    temporary = root / f".{CONTROL_NAME}.{os.getpid()}.{time.time_ns()}.tmp"
    descriptor = None
    try:
        descriptor = os.open(
            os.fspath(temporary),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = None
            json.dump(updated, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    except OSError as error:
        raise MemoryCanaryError("canary_control_write_failed") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return updated


def assert_task_allowed(task, control):
    if not isinstance(task, dict) or task.get("memoryCanary") is not True:
        raise MemoryCanaryError("canary_not_requested")
    control = _validate_control(control)
    if not control["enabled"]:
        raise MemoryCanaryError("canary_disabled")
    if (
        task.get("projectSlug") != ALLOWED_PROJECT
        or ALLOWED_PROJECT not in control["allowedProjects"]
    ):
        raise MemoryCanaryError("canary_project_denied")
    if not str(task.get("contextQuestion") or "").strip():
        raise MemoryCanaryError("canary_question_required")


def canonical_char_count(document):
    return len(
        json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def session_alias(backend, session_id):
    clean = str(session_id or "").strip()
    return f"{backend}:{clean[-8:]}" if clean else "unavailable"


def _memory_metadata(spec):
    metadata = getattr(spec, "memory_metadata", {})
    claims = spec.get("memoryClaims") if isinstance(spec, dict) else []
    count = len(claims) if isinstance(claims, list) else 0
    return {
        "returnedClaimCount": metadata.get("returnedClaimCount", count),
        "embeddedClaimCount": metadata.get("embeddedClaimCount", count),
        "memoryProviderUsage": metadata.get("aiUsage", "not_measured"),
    }


def compile_attempt(
    *,
    task,
    profile,
    control,
    compile_spec,
    recall,
    bypass=False,
    now=time.time,
):
    if not isinstance(task, dict) or not isinstance(profile, dict):
        raise MemoryCanaryError("canary_contract_invalid")
    requested = task.get("memoryCanary") is True
    if requested and not bypass:
        assert_task_allowed(task, control)
    baseline_profile = copy.deepcopy(profile)
    memory = baseline_profile.get("memory")
    if not isinstance(memory, dict):
        raise MemoryCanaryError("canary_contract_invalid")
    memory["enabled"] = False
    baseline = compile_spec(
        task,
        baseline_profile,
        recall=lambda _request: (_ for _ in ()).throw(
            MemoryCanaryError("canary_baseline_recall_forbidden")
        ),
        now=now,
    )
    if bypass or not requested:
        candidate = baseline
        status = "rolled_back" if bypass else "not_requested"
    else:
        candidate = compile_spec(task, profile, recall=recall, now=now)
        status = candidate.get("memoryStatus", "error")
    baseline_chars = canonical_char_count(baseline)
    candidate_chars = canonical_char_count(candidate)
    delta = max(0, candidate_chars - baseline_chars)
    metadata = _memory_metadata(candidate)
    receipt = {
        "schemaVersion": 1,
        "attemptId": secrets.token_hex(12),
        "taskId": str(task.get("id") or ""),
        "projectSlug": str(task.get("projectSlug") or ""),
        "controlRevision": control.get("revision") if isinstance(control, dict) else None,
        "profileRevision": profile.get("revision"),
        "memoryStatus": status,
        "returnedClaimCount": (
            metadata["returnedClaimCount"] if requested and not bypass else 0
        ),
        "embeddedClaimCount": (
            metadata["embeddedClaimCount"] if requested and not bypass else 0
        ),
        "retrievalLatencyMs": "not_measured",
        "baselineCharacters": baseline_chars,
        "candidateCharacters": candidate_chars,
        "memoryDeltaCharacters": delta,
        "memoryDeltaTokensEstimated": (delta + 3) // 4,
        "memoryProviderUsage": (
            metadata["memoryProviderUsage"]
            if requested and not bypass
            else "not_measured"
        ),
        "startedAt": now(),
        "outcome": "pending",
    }
    return {"baseline": baseline, "candidate": candidate, "receipt": receipt}


def _receipt_has_forbidden_content(value):
    forbidden = {
        "question",
        "contextquestion",
        "memoryclaims",
        "claimtext",
        "content",
        "token",
        "secret",
        "credential",
        "transcript",
        "reasoning",
    }
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).replace("_", "").lower()
            if normalized in forbidden or any(
                word in normalized
                for word in ("password", "apikey", "authorization")
            ):
                return True
            if _receipt_has_forbidden_content(child):
                return True
    elif isinstance(value, list):
        return any(_receipt_has_forbidden_content(child) for child in value)
    return False


def append_receipt(runtime_dir, event):
    if (
        not isinstance(event, dict)
        or not str(event.get("attemptId") or "").strip()
        or not str(event.get("taskId") or "").strip()
        or _receipt_has_forbidden_content(event)
    ):
        raise MemoryCanaryError("canary_receipt_content_forbidden")
    try:
        encoded = (
            json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as error:
        raise MemoryCanaryError("canary_receipt_invalid") from error
    if len(encoded) > MAX_RECEIPT_BYTES:
        raise MemoryCanaryError("canary_receipt_invalid")
    root = Path(runtime_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    path = root / RECEIPT_NAME
    if path.is_symlink():
        raise MemoryCanaryError("canary_receipt_invalid")
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(os.fspath(path), flags, 0o600)
        with os.fdopen(descriptor, "ab") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(path, 0o600)
    except OSError as error:
        raise MemoryCanaryError("canary_receipt_write_failed") from error


def latest_receipt(runtime_dir, task_id):
    path = Path(runtime_dir).resolve() / RECEIPT_NAME
    if not path.exists():
        return None
    if path.is_symlink():
        raise MemoryCanaryError("canary_receipt_invalid")
    task_id = str(task_id or "").strip()
    latest = None
    try:
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                if len(line.encode("utf-8")) > MAX_RECEIPT_BYTES:
                    raise MemoryCanaryError("canary_receipt_invalid")
                value = json.loads(line)
                if isinstance(value, dict) and value.get("taskId") == task_id:
                    latest = value
    except MemoryCanaryError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise MemoryCanaryError("canary_receipt_invalid") from error
    return latest
