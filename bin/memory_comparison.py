#!/usr/bin/env python3
"""Private, fail-closed runtime state for the paired Memory Gate B comparison."""
from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
import re
import time


STATE_NAME = "state.json"
EVENTS_NAME = "events.jsonl"
ROOT_NAME = "memory-comparison"
RUN_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
CLEANUP_FIELDS = {
    "worker_absent",
    "card_absent",
    "conversation_retired",
    "temp_artifacts_absent",
}
RESULT_FIELDS = {"score_receipt", "metrics"}
SCORE_FIELDS = {
    "schema_version",
    "case_alias",
    "components",
    "score",
    "successful",
    "harmful",
    "violations",
}
METRIC_FIELDS = {
    "wall_time_ms",
    "retrieval_latency_ms",
    "memory_context_tokens_estimated",
    "provider_tokens",
    "rework_count",
}
FORBIDDEN_WORDS = {
    "prompt",
    "content",
    "transcript",
    "reasoning",
    "credential",
    "secret",
    "token",
    "password",
    "authorization",
    "apikey",
}
ALLOWED_METRIC_KEYS = {
    "providertokens",
    "memorycontexttokensestimated",
}


class MemoryComparisonError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _label(value, code, maximum=128):
    clean = str(value or "").strip()
    if not clean or len(clean) > maximum or any(ord(c) < 32 or ord(c) == 127 for c in clean):
        raise MemoryComparisonError(code)
    return clean


def _run_dir(runtime_dir, run_id):
    clean = _label(run_id, "invalid_run_id", 64)
    if not RUN_ID_RE.fullmatch(clean):
        raise MemoryComparisonError("invalid_run_id")
    return Path(runtime_dir).resolve() / ROOT_NAME / "runs" / clean


def _timestamp(now):
    value = now() if callable(now) else now
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise MemoryComparisonError("invalid_timestamp")
    return float(value)


def _atomic_state(run_dir, state):
    run_dir.mkdir(parents=True, exist_ok=True)
    target = run_dir / STATE_NAME
    if target.is_symlink():
        raise MemoryComparisonError("state_invalid")
    temporary = run_dir / f".{STATE_NAME}.{os.getpid()}.{time.time_ns()}.tmp"
    descriptor = None
    try:
        descriptor = os.open(os.fspath(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = None
            json.dump(state, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
    except (OSError, TypeError, ValueError) as error:
        raise MemoryComparisonError("state_write_failed") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _append_event(run_dir, event):
    encoded = (json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    if len(encoded) > 8192:
        raise MemoryComparisonError("event_invalid")
    path = run_dir / EVENTS_NAME
    if path.is_symlink():
        raise MemoryComparisonError("event_invalid")
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(os.fspath(path), flags, 0o600)
        with os.fdopen(descriptor, "ab") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except OSError as error:
        raise MemoryComparisonError("event_write_failed") from error


def _persist(run_dir, state, event_type, timestamp, **fields):
    state["updated_at"] = timestamp
    _atomic_state(run_dir, state)
    _append_event(
        run_dir,
        {
            "schema_version": 1,
            "run_id": state["run_id"],
            "event_type": event_type,
            "status": state["status"],
            "timestamp": timestamp,
            **fields,
        },
    )
    return copy.deepcopy(state)


def load_state(runtime_dir, run_id):
    path = _run_dir(runtime_dir, run_id) / STATE_NAME
    if not path.is_file() or path.is_symlink():
        raise MemoryComparisonError("run_not_found")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise MemoryComparisonError("state_invalid") from error
    if not isinstance(value, dict) or value.get("run_id") != run_id:
        raise MemoryComparisonError("state_invalid")
    return value


def _violate(run_dir, state, code, now):
    timestamp = _timestamp(now)
    state["status"] = "aborted"
    state["cleanup_required"] = True
    state["abort_code"] = code
    _persist(run_dir, state, "run_aborted", timestamp, code=code)
    raise MemoryComparisonError(code)


def _assert_open(run_dir, state, now):
    if state["status"] == "aborted":
        raise MemoryComparisonError("run_aborted")
    if state["status"] == "completed":
        raise MemoryComparisonError("run_completed")


def start_run(runtime_dir, *, run_id, cases, fixture_sha256, now=time.time):
    run_dir = _run_dir(runtime_dir, run_id)
    if (run_dir / STATE_NAME).exists():
        raise MemoryComparisonError("run_exists")
    if not isinstance(fixture_sha256, str) or not SHA_RE.fullmatch(fixture_sha256):
        raise MemoryComparisonError("invalid_fixture_sha")
    if not isinstance(cases, list) or not cases:
        raise MemoryComparisonError("invalid_cases")
    pairs = []
    aliases = set()
    for row in cases:
        if not isinstance(row, dict) or set(row) != {"alias", "arm_order"}:
            raise MemoryComparisonError("invalid_cases")
        alias = _label(row["alias"], "invalid_cases")
        order = row["arm_order"]
        if alias in aliases or not isinstance(order, list) or len(order) != 2 or set(order) != {"baseline", "memory"}:
            raise MemoryComparisonError("invalid_cases")
        aliases.add(alias)
        pairs.append({"alias": alias, "arm_order": list(order), "arms": {}, "completed": False})
    timestamp = _timestamp(now)
    state = {
        "schema_version": 1,
        "run_id": run_id,
        "status": "planned",
        "fixture_sha256": fixture_sha256,
        "offline_digest": None,
        "pairs": pairs,
        "active_arm": None,
        "used_resources": {"worker_ids": [], "card_ids": [], "conversation_ids": []},
        "cleanup_required": False,
        "abort_code": None,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    return _persist(run_dir, state, "run_started", timestamp)


def record_offline_qualification(runtime_dir, *, run_id, logical_digest, passed, now=time.time):
    run_dir = _run_dir(runtime_dir, run_id)
    state = load_state(runtime_dir, run_id)
    _assert_open(run_dir, state, now)
    if state["status"] != "planned":
        return _violate(run_dir, state, "offline_qualification_order", now)
    if not isinstance(logical_digest, str) or not SHA_RE.fullmatch(logical_digest) or type(passed) is not bool:
        return _violate(run_dir, state, "offline_qualification_invalid", now)
    if not passed:
        return _violate(run_dir, state, "offline_qualification_failed", now)
    timestamp = _timestamp(now)
    state["offline_digest"] = logical_digest
    state["status"] = "offline_qualified"
    return _persist(run_dir, state, "offline_qualified", timestamp)


def _next_arm(state):
    for pair in state["pairs"]:
        if pair["completed"]:
            continue
        for arm in pair["arm_order"]:
            row = pair["arms"].get(arm)
            if row is None:
                return pair, arm
            if not row.get("cleaned"):
                return pair, None
        return pair, "pair_completion_required"
    return None, None


def start_arm(runtime_dir, *, run_id, case_alias, arm, worker_id, card_id, conversation_id, now=time.time):
    run_dir = _run_dir(runtime_dir, run_id)
    state = load_state(runtime_dir, run_id)
    _assert_open(run_dir, state, now)
    if state.get("active_arm") is not None:
        code = "cleanup_required" if state["status"] == "arm_recorded" else "arm_already_active"
        return _violate(run_dir, state, code, now)
    pair, expected = _next_arm(state)
    if pair is None or expected in (None, "pair_completion_required") or pair["alias"] != case_alias or expected != arm:
        return _violate(run_dir, state, "arm_order_violation", now)
    resources = {
        "worker_id": _label(worker_id, "invalid_resource"),
        "card_id": _label(card_id, "invalid_resource"),
        "conversation_id": _label(conversation_id, "invalid_resource"),
    }
    used = state["used_resources"]
    if (
        resources["worker_id"] in used["worker_ids"]
        or resources["card_id"] in used["card_ids"]
        or resources["conversation_id"] in used["conversation_ids"]
    ):
        return _violate(run_dir, state, "resource_reuse", now)
    used["worker_ids"].append(resources["worker_id"])
    used["card_ids"].append(resources["card_id"])
    used["conversation_ids"].append(resources["conversation_id"])
    pair["arms"][arm] = {"resources": resources, "result": None, "cleaned": False}
    state["active_arm"] = {"case_alias": case_alias, "arm": arm, **resources}
    state["status"] = "arm_started"
    timestamp = _timestamp(now)
    return _persist(run_dir, state, "arm_started", timestamp, case_alias=case_alias, arm=arm)


def _contains_forbidden(value):
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = re.sub(r"[^a-z]", "", str(key).lower())
            if normalized not in ALLOWED_METRIC_KEYS and any(
                word in normalized for word in FORBIDDEN_WORDS
            ):
                return True
            if _contains_forbidden(child):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden(child) for child in value)
    return False


def _validate_result(result, case_alias):
    if not isinstance(result, dict) or set(result) != RESULT_FIELDS or _contains_forbidden(result):
        raise MemoryComparisonError("result_content_forbidden")
    score = result.get("score_receipt")
    metrics = result.get("metrics")
    if not isinstance(score, dict) or set(score) != SCORE_FIELDS or score.get("case_alias") != case_alias:
        raise MemoryComparisonError("result_invalid")
    if not isinstance(metrics, dict) or set(metrics) != METRIC_FIELDS:
        raise MemoryComparisonError("result_invalid")
    if isinstance(metrics.get("wall_time_ms"), bool) or not isinstance(metrics.get("wall_time_ms"), int) or metrics["wall_time_ms"] < 0:
        raise MemoryComparisonError("result_invalid")
    if isinstance(score.get("score"), bool) or not isinstance(score.get("score"), int) or not 0 <= score["score"] <= 100:
        raise MemoryComparisonError("result_invalid")
    if type(score.get("successful")) is not bool or type(score.get("harmful")) is not bool:
        raise MemoryComparisonError("result_invalid")
    if isinstance(metrics.get("rework_count"), bool) or not isinstance(metrics.get("rework_count"), int) or metrics["rework_count"] < 0:
        raise MemoryComparisonError("result_invalid")
    return copy.deepcopy(result)


def record_arm_result(runtime_dir, *, run_id, case_alias, arm, result, now=time.time):
    run_dir = _run_dir(runtime_dir, run_id)
    state = load_state(runtime_dir, run_id)
    _assert_open(run_dir, state, now)
    active = state.get("active_arm")
    if state["status"] != "arm_started" or not active or (active["case_alias"], active["arm"]) != (case_alias, arm):
        return _violate(run_dir, state, "arm_result_order", now)
    try:
        normalized = _validate_result(result, case_alias)
    except MemoryComparisonError as error:
        return _violate(run_dir, state, error.code, now)
    pair = next(row for row in state["pairs"] if row["alias"] == case_alias)
    pair["arms"][arm]["result"] = normalized
    state["status"] = "arm_recorded"
    timestamp = _timestamp(now)
    return _persist(run_dir, state, "arm_recorded", timestamp, case_alias=case_alias, arm=arm)


def _validate_cleanup(evidence):
    if not isinstance(evidence, dict) or set(evidence) != CLEANUP_FIELDS or any(value is not True for value in evidence.values()):
        raise MemoryComparisonError("cleanup_evidence_invalid")


def record_cleanup(runtime_dir, *, run_id, evidence, now=time.time):
    run_dir = _run_dir(runtime_dir, run_id)
    state = load_state(runtime_dir, run_id)
    _validate_cleanup(evidence)
    active = state.get("active_arm")
    if state["status"] == "aborted":
        if active:
            pair = next(row for row in state["pairs"] if row["alias"] == active["case_alias"])
            pair["arms"][active["arm"]]["cleaned"] = True
        state["active_arm"] = None
        state["cleanup_required"] = False
        timestamp = _timestamp(now)
        return _persist(run_dir, state, "abort_cleanup_recorded", timestamp)
    if state["status"] != "arm_recorded" or not active:
        return _violate(run_dir, state, "cleanup_order", now)
    pair = next(row for row in state["pairs"] if row["alias"] == active["case_alias"])
    pair["arms"][active["arm"]]["cleaned"] = True
    case_alias, arm = active["case_alias"], active["arm"]
    state["active_arm"] = None
    state["cleanup_required"] = False
    state["status"] = "arm_cleaned"
    timestamp = _timestamp(now)
    return _persist(run_dir, state, "arm_cleaned", timestamp, case_alias=case_alias, arm=arm)


def complete_pair(runtime_dir, *, run_id, case_alias, now=time.time):
    run_dir = _run_dir(runtime_dir, run_id)
    state = load_state(runtime_dir, run_id)
    _assert_open(run_dir, state, now)
    pair, expected = _next_arm(state)
    if state["status"] != "arm_cleaned" or pair is None or pair["alias"] != case_alias or expected != "pair_completion_required":
        return _violate(run_dir, state, "pair_completion_order", now)
    pair["completed"] = True
    state["status"] = "pair_completed"
    timestamp = _timestamp(now)
    return _persist(run_dir, state, "pair_completed", timestamp, case_alias=case_alias)


def complete_run(runtime_dir, *, run_id, now=time.time):
    run_dir = _run_dir(runtime_dir, run_id)
    state = load_state(runtime_dir, run_id)
    _assert_open(run_dir, state, now)
    if state["status"] != "pair_completed" or not all(pair["completed"] for pair in state["pairs"]):
        return _violate(run_dir, state, "run_completion_order", now)
    state["status"] = "completed"
    timestamp = _timestamp(now)
    return _persist(run_dir, state, "run_completed", timestamp)


def abort_run(runtime_dir, *, run_id, code="operator_abort", now=time.time):
    run_dir = _run_dir(runtime_dir, run_id)
    state = load_state(runtime_dir, run_id)
    if state["status"] in {"aborted", "completed"}:
        raise MemoryComparisonError(f"run_{state['status']}")
    timestamp = _timestamp(now)
    state["status"] = "aborted"
    state["cleanup_required"] = True
    state["abort_code"] = _label(code, "invalid_abort_code", 64)
    return _persist(run_dir, state, "run_aborted", timestamp, code=state["abort_code"])


def build_public_summary(runtime_dir, run_id):
    state = load_state(runtime_dir, run_id)
    scores = {"baseline": [], "memory": []}
    successes = {"baseline": 0, "memory": 0}
    harmful = 0
    arm_count = 0
    rework = {"baseline": 0, "memory": 0}
    for pair in state["pairs"]:
        for arm, row in pair["arms"].items():
            result = row.get("result")
            if not result:
                continue
            arm_count += 1
            receipt = result["score_receipt"]
            scores[arm].append(receipt["score"])
            successes[arm] += int(receipt["successful"])
            harmful += int(receipt["harmful"])
            rework[arm] += result["metrics"]["rework_count"]
    return {
        "schema_version": 1,
        "run_id": state["run_id"],
        "status": state["status"],
        "case_count": len(state["pairs"]),
        "completed_pair_count": sum(pair["completed"] for pair in state["pairs"]),
        "arm_count": arm_count,
        "scores": scores,
        "successful_counts": successes,
        "harmful_count": harmful,
        "rework_counts": rework,
        "cleanup_complete": not state["cleanup_required"] and state["active_arm"] is None,
        "provider_tokens": "not_measured",
    }
