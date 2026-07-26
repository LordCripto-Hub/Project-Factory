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
    retrieval_latency = "not_measured"
    if bypass or not requested:
        candidate = baseline
        status = "rolled_back" if bypass else "not_requested"
    else:
        def measured_recall(request):
            nonlocal retrieval_latency
            started = time.monotonic()
            try:
                return recall(request) if recall is not None else None
            finally:
                retrieval_latency = round((time.monotonic() - started) * 1000)

        candidate = compile_spec(
            task,
            profile,
            recall=measured_recall if recall is not None else None,
            now=now,
        )
        status = candidate.get("memoryStatus", "error")
    baseline_chars = canonical_char_count(baseline)
    candidate_chars = canonical_char_count(candidate)
    delta = max(0, candidate_chars - baseline_chars)
    metadata = _memory_metadata(candidate)
    receipt = {
        "schemaVersion": 1,
        "eventType": "start",
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
        "retrievalLatencyMs": retrieval_latency,
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


def _usage_counter(snapshot, field):
    if not isinstance(snapshot, dict):
        return None
    usage = snapshot.get("usage")
    value = usage.get(field) if isinstance(usage, dict) else None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def provider_usage_delta(before, after):
    if not isinstance(before, dict) or not isinstance(after, dict):
        return "not_measured"
    provider = str(before.get("provider") or "").strip()
    session_id = str(before.get("sessionId") or "").strip()
    if (
        not provider
        or provider != str(after.get("provider") or "").strip()
        or not session_id
        or session_id != str(after.get("sessionId") or "").strip()
    ):
        return "not_measured"
    result = {}
    for field in ("inputTokens", "outputTokens"):
        left = _usage_counter(before, field)
        right = _usage_counter(after, field)
        if left is None or right is None or right < left:
            return "not_measured"
        result[field] = right - left
    return result


def provider_usage_snapshot(path, provider, session_id):
    provider = str(provider or "").strip()
    session_id = str(session_id or "").strip()
    candidate = Path(path)
    if provider != "codex" or not session_id or candidate.is_symlink():
        return {}
    try:
        if not candidate.is_file() or candidate.stat().st_size > 32 * 1024 * 1024:
            return {}
        last = None
        with candidate.open("r", encoding="utf-8") as stream:
            first = json.loads(stream.readline())
            payload = first.get("payload") if isinstance(first, dict) else None
            if (
                first.get("type") != "session_meta"
                or not isinstance(payload, dict)
                or str(payload.get("id") or payload.get("session_id") or "") != session_id
            ):
                return {}
            for line in stream:
                event = json.loads(line)
                event_payload = event.get("payload") if isinstance(event, dict) else None
                if (
                    event.get("type") != "event_msg"
                    or not isinstance(event_payload, dict)
                    or event_payload.get("type") != "token_count"
                ):
                    continue
                info = event_payload.get("info")
                total = info.get("total_token_usage") if isinstance(info, dict) else None
                if not isinstance(total, dict):
                    continue
                input_tokens = total.get("input_tokens")
                output_tokens = total.get("output_tokens")
                if (
                    isinstance(input_tokens, bool)
                    or not isinstance(input_tokens, int)
                    or input_tokens < 0
                    or isinstance(output_tokens, bool)
                    or not isinstance(output_tokens, int)
                    or output_tokens < 0
                ):
                    continue
                last = {
                    "provider": provider,
                    "sessionId": session_id,
                    "usage": {
                        "inputTokens": input_tokens,
                        "outputTokens": output_tokens,
                    },
                }
        return last or {}
    except (OSError, UnicodeError, json.JSONDecodeError, AttributeError):
        return {}


def _attempt_start(runtime_dir, attempt_id, task_id):
    path = Path(runtime_dir).resolve() / RECEIPT_NAME
    if not path.exists() or path.is_symlink():
        raise MemoryCanaryError("canary_receipt_invalid")
    try:
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                value = json.loads(line)
                if (
                    isinstance(value, dict)
                    and value.get("eventType") == "start"
                    and value.get("attemptId") == attempt_id
                    and value.get("taskId") == task_id
                ):
                    return value
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise MemoryCanaryError("canary_receipt_invalid") from error
    raise MemoryCanaryError("canary_attempt_missing")


def _bounded_label(value, code, maximum=128):
    clean = str(value or "").strip()
    if (
        not clean
        or len(clean) > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in clean)
    ):
        raise MemoryCanaryError(code)
    return clean


def complete_attempt(
    runtime_dir,
    *,
    attempt_id,
    task_id,
    runtime_record,
    outcome,
    evidence_count,
    usage_before,
    usage_after,
    completed_at,
):
    attempt_id = _bounded_label(attempt_id, "canary_attempt_invalid")
    task_id = _bounded_label(task_id, "canary_task_invalid")
    if not isinstance(runtime_record, dict):
        raise MemoryCanaryError("canary_runtime_invalid")
    start = _attempt_start(runtime_dir, attempt_id, task_id)
    try:
        completed = float(completed_at)
        started = float(start["startedAt"])
    except (KeyError, TypeError, ValueError) as error:
        raise MemoryCanaryError("canary_timing_invalid") from error
    if not math.isfinite(completed) or not math.isfinite(started) or completed < started:
        raise MemoryCanaryError("canary_timing_invalid")
    if isinstance(evidence_count, bool) or not isinstance(evidence_count, int) or evidence_count < 0:
        raise MemoryCanaryError("canary_evidence_invalid")
    retry_count = runtime_record.get("recovery_attempts", 0)
    if isinstance(retry_count, bool) or not isinstance(retry_count, int) or retry_count < 0:
        retry_count = 0
    backend = _bounded_label(
        runtime_record.get("backend"), "canary_backend_invalid", maximum=32
    )
    event = {
        "schemaVersion": 1,
        "eventType": "completion",
        "attemptId": attempt_id,
        "taskId": task_id,
        "completedAt": completed,
        "durationMilliseconds": round((completed - started) * 1000),
        "outcome": _bounded_label(outcome, "canary_outcome_invalid", maximum=32),
        "evidenceCount": evidence_count,
        "retryCount": retry_count,
        "backend": backend,
        "model": _bounded_label(
            runtime_record.get("model") or "unavailable",
            "canary_model_invalid",
        ),
        "providerProfile": _bounded_label(
            runtime_record.get("provider_profile") or "unavailable",
            "canary_profile_invalid",
        ),
        "sessionAlias": session_alias(backend, runtime_record.get("session_id")),
        "providerUsage": provider_usage_delta(usage_before, usage_after),
    }
    append_receipt(runtime_dir, event)
    return event


def receipt_projection(runtime_dir, task_id):
    path = Path(runtime_dir).resolve() / RECEIPT_NAME
    if not path.exists():
        return None
    if path.is_symlink():
        raise MemoryCanaryError("canary_receipt_invalid")
    task_id = _bounded_label(task_id, "canary_task_invalid")
    starts = {}
    completions = {}
    try:
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                value = json.loads(line)
                if not isinstance(value, dict) or value.get("taskId") != task_id:
                    continue
                attempt_id = str(value.get("attemptId") or "")
                if value.get("eventType") == "start":
                    starts[attempt_id] = value
                elif value.get("eventType") == "completion":
                    completions[attempt_id] = value
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise MemoryCanaryError("canary_receipt_invalid") from error
    if not starts:
        return None
    start = max(starts.values(), key=lambda row: float(row.get("startedAt") or 0))
    completion = completions.get(start["attemptId"])
    allowed_start = {
        "attemptId", "taskId", "projectSlug", "controlRevision",
        "profileRevision", "memoryStatus", "returnedClaimCount",
        "embeddedClaimCount", "retrievalLatencyMs", "baselineCharacters",
        "candidateCharacters", "memoryDeltaCharacters",
        "memoryDeltaTokensEstimated", "memoryProviderUsage", "startedAt",
    }
    projection = {key: start[key] for key in allowed_start if key in start}
    if completion:
        allowed_completion = {
            "completedAt", "durationMilliseconds", "outcome", "evidenceCount",
            "retryCount", "backend", "model", "providerProfile",
            "sessionAlias", "providerUsage",
        }
        projection.update(
            {key: completion[key] for key in allowed_completion if key in completion}
        )
    return projection
