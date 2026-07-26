#!/usr/bin/env python3
"""Private, closed records for lossless task-routing escalation."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import time

from mpcommon import parse_agent_id
from provider_handoff import redact, sanitize_terminal_tail
from task_routing import TASK_ID, canonical_decision_bytes


ELIGIBLE_FAILURES = frozenset(
    {
        "verification_failed",
        "implementation_blocked",
        "model_capability_insufficient",
    }
)
REQUEST_FIELDS = frozenset(
    {
        "schemaVersion",
        "requestId",
        "agentId",
        "taskId",
        "bossId",
        "requestedBy",
        "actorClass",
        "failure",
        "summary",
        "proofs",
        "routingSha256",
        "createdAt",
        "state",
    }
)
REQUEST_STATES = frozenset(
    {"prepared", "queued", "processing", "committed", "rolled_back", "recovery_required"}
)
TERMINAL_STATES = frozenset(
    {"committed", "rolled_back", "recovery_required"}
)
TRANSACTION_PHASES = frozenset(
    {
        "prepared",
        "stopped",
        "resuming",
        "verifying",
        "committed",
        "rolling_back",
        "rolled_back",
        "recovery_required",
    }
)
TRANSACTION_FIELDS = frozenset(
    {
        "requestId",
        "phase",
        "createdAt",
        "updatedAt",
        "failure",
        "agentId",
        "taskId",
        "routingBeforeSha256",
        "routingCandidateSha256",
        "providerProfile",
        "fromModel",
        "toModel",
        "continuationSent",
        "errorCode",
    }
)

REQUEST_ID = re.compile(r"^[0-9a-f]{32}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SAFE_TEXT_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
SENSITIVE_LITERAL = re.compile(
    r"(?i)(?:authorization\s*:|bearer\s+|OPENAI_API_KEY|"
    r"-----BEGIN [^-]*PRIVATE KEY-----|(?:sk-|tskey-auth-|ghp_|github_pat_)"
    r"[A-Za-z0-9._-]+|"
    r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})"
)

_REQUEST_TRANSITIONS = {
    "prepared": frozenset({"queued", "processing"}),
    "queued": frozenset({"processing"}),
    "processing": TERMINAL_STATES,
}
_TRANSACTION_TRANSITIONS = {
    "prepared": frozenset({"stopped", "rolling_back"}),
    "stopped": frozenset({"resuming", "rolling_back"}),
    "resuming": frozenset({"verifying", "rolling_back"}),
    "verifying": frozenset({"committed", "rolling_back"}),
    "rolling_back": frozenset({"rolled_back", "recovery_required"}),
}


class EscalationError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _fail(code: str):
    raise EscalationError(code)


def _validate_request_id(value) -> str:
    if not isinstance(value, str) or not REQUEST_ID.fullmatch(value):
        _fail("escalation_request_invalid")
    return value


def _validate_sha256(value) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        _fail("escalation_request_invalid")
    return value


def _validate_agent(value) -> str:
    if not isinstance(value, str) or len(value) > 256:
        _fail("escalation_request_invalid")
    try:
        parse_agent_id(value)
    except (TypeError, ValueError):
        _fail("escalation_request_invalid")
    return value


def _safe_text(value, *, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > maximum
        or SAFE_TEXT_CONTROL.search(value)
        or SENSITIVE_LITERAL.search(value)
        or redact(value) != value
        or sanitize_terminal_tail(value) != value
    ):
        _fail("escalation_request_invalid")
    return value


def _validate_request(record) -> dict:
    if (
        not isinstance(record, dict)
        or set(record) != REQUEST_FIELDS
        or record.get("schemaVersion") != 1
    ):
        _fail("escalation_request_invalid")
    _validate_request_id(record.get("requestId"))
    agent_id = _validate_agent(record.get("agentId"))
    boss_id = _validate_agent(record.get("bossId"))
    if (
        not isinstance(record.get("taskId"), str)
        or not TASK_ID.fullmatch(record["taskId"])
    ):
        _fail("escalation_request_invalid")
    actor_class = record.get("actorClass")
    requested_by = record.get("requestedBy")
    if actor_class not in {"worker", "boss", "operator"}:
        _fail("escalation_request_invalid")
    if actor_class == "worker":
        if _validate_agent(requested_by) != agent_id:
            _fail("escalation_request_invalid")
    elif actor_class == "boss":
        if _validate_agent(requested_by) != boss_id:
            _fail("escalation_request_invalid")
    elif requested_by != "local-operator":
        _fail("escalation_request_invalid")
    if record.get("failure") not in ELIGIBLE_FAILURES:
        _fail("routing_failure_not_escalatable")
    _safe_text(record.get("summary"), maximum=2000)
    proofs = record.get("proofs")
    if (
        not isinstance(proofs, list)
        or not 1 <= len(proofs) <= 5
        or any(not isinstance(item, str) for item in proofs)
    ):
        _fail("escalation_request_invalid")
    for proof in proofs:
        _safe_text(proof, maximum=1000)
    _validate_sha256(record.get("routingSha256"))
    created = record.get("createdAt")
    if (
        not isinstance(created, (int, float))
        or isinstance(created, bool)
        or not math.isfinite(created)
        or created < 0
    ):
        _fail("escalation_request_invalid")
    if record.get("state") not in REQUEST_STATES:
        _fail("escalation_request_invalid")
    return dict(record)


def _absolute(path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _assert_no_symlinks(path) -> Path:
    target = _absolute(path)
    current = Path(target.anchor)
    for part in target.parts[1:]:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            _fail("escalation_path_invalid")
    return target


def _private_dir(path) -> Path:
    target = _assert_no_symlinks(path)
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    _assert_no_symlinks(target)
    if not target.is_dir():
        _fail("escalation_path_invalid")
    os.chmod(target, 0o700)
    return target


def _private_file(path) -> Path:
    target = _assert_no_symlinks(path)
    try:
        mode = target.stat().st_mode
    except FileNotFoundError:
        _fail("escalation_record_missing")
    if not stat.S_ISREG(mode) or stat.S_IMODE(mode) != 0o600:
        _fail("escalation_path_invalid")
    return target


def _json_bytes(value) -> bytes:
    try:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            + b"\n"
        )
    except (TypeError, ValueError) as error:
        raise EscalationError("escalation_request_invalid") from error


def _atomic_bytes(path, raw: bytes) -> str:
    target = _assert_no_symlinks(path)
    _private_dir(target.parent)
    if target.exists():
        _private_file(target)
    temporary = target.parent / (
        f".{target.name}.{os.getpid()}.{time.time_ns()}.tmp"
    )
    descriptor = None
    try:
        descriptor = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
        os.chmod(target, 0o600)
    except OSError:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise
    return str(target)


def _load_json(path):
    target = _private_file(path)
    try:
        with target.open(encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, ValueError, TypeError) as error:
        raise EscalationError("escalation_record_invalid") from error


def _request_path(root, request_id: str) -> Path:
    request_id = _validate_request_id(request_id)
    base = _absolute(root)
    target = base / "requests" / f"{request_id}.json"
    if target.parent.parent != base:
        _fail("escalation_path_invalid")
    return target


def _same_request(left: dict, right: dict) -> bool:
    ignored = {"createdAt", "state"}
    return all(
        left.get(key) == right.get(key)
        for key in REQUEST_FIELDS - ignored
    )


def create_request(
    root,
    *,
    request_id,
    agent_id,
    task_id,
    boss_id,
    requested_by,
    actor_class,
    failure,
    summary,
    proofs,
    routing_sha256,
    now=None,
) -> tuple[str, dict]:
    record = {
        "schemaVersion": 1,
        "requestId": request_id,
        "agentId": agent_id,
        "taskId": task_id,
        "bossId": boss_id,
        "requestedBy": requested_by,
        "actorClass": actor_class,
        "failure": failure,
        "summary": summary,
        "proofs": list(proofs) if isinstance(proofs, list) else proofs,
        "routingSha256": routing_sha256,
        "createdAt": time.time() if now is None else now,
        "state": "prepared",
    }
    record = _validate_request(record)
    target = _request_path(root, record["requestId"])
    _assert_no_symlinks(root)
    if target.exists():
        current = load_request(root, record["requestId"])
        if not _same_request(current, record):
            _fail("escalation_request_conflict")
        return str(target), current
    _atomic_bytes(target, _json_bytes(record))
    return str(target), record


def load_request(root, request_id) -> dict:
    target = _request_path(root, request_id)
    record = _load_json(target)
    try:
        return _validate_request(record)
    except EscalationError as error:
        if error.code == "routing_failure_not_escalatable":
            raise EscalationError("escalation_record_invalid") from error
        raise


def write_request_state(root, request, state) -> dict:
    supplied = _validate_request(request)
    if state not in REQUEST_STATES:
        _fail("escalation_state_invalid")
    current = load_request(root, supplied["requestId"])
    if not _same_request(current, supplied):
        _fail("escalation_request_conflict")
    prior = current["state"]
    if prior == state:
        return current
    if prior in TERMINAL_STATES or state not in _REQUEST_TRANSITIONS.get(
        prior, frozenset()
    ):
        _fail("escalation_state_invalid")
    updated = dict(current)
    updated["state"] = state
    target = _request_path(root, updated["requestId"])
    _atomic_bytes(target, _json_bytes(updated))
    return updated


def transaction_paths(root, request_id) -> dict[str, str]:
    request_id = _validate_request_id(request_id)
    base = _absolute(root)
    directory = base / "transactions" / request_id
    if directory.parent.parent != base:
        _fail("escalation_path_invalid")
    return {
        "directory": str(directory),
        "state": str(directory / "state.json"),
        "roster_before": str(directory / "roster-before.json"),
        "routing_before": str(directory / "routing-before.json"),
        "routing_candidate": str(directory / "routing-candidate.json"),
        "handoff": str(directory / "handoff.json"),
    }


def _validate_transaction(record) -> dict:
    if (
        not isinstance(record, dict)
        or not {"requestId", "phase", "createdAt", "updatedAt"}.issubset(record)
        or not set(record).issubset(TRANSACTION_FIELDS)
    ):
        _fail("escalation_state_invalid")
    _validate_request_id(record.get("requestId"))
    if record.get("phase") not in TRANSACTION_PHASES:
        _fail("escalation_state_invalid")
    for field in ("createdAt", "updatedAt"):
        value = record.get(field)
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or value < 0
        ):
            _fail("escalation_state_invalid")
    if record["updatedAt"] < record["createdAt"]:
        _fail("escalation_state_invalid")
    for field in ("agentId",):
        if field in record:
            _validate_agent(record[field])
    if "taskId" in record and (
        not isinstance(record["taskId"], str)
        or not TASK_ID.fullmatch(record["taskId"])
    ):
        _fail("escalation_state_invalid")
    for field in ("routingBeforeSha256", "routingCandidateSha256"):
        if field in record:
            try:
                _validate_sha256(record[field])
            except EscalationError as error:
                raise EscalationError("escalation_state_invalid") from error
    if "failure" in record and record["failure"] not in ELIGIBLE_FAILURES:
        _fail("escalation_state_invalid")
    for field in (
        "providerProfile",
        "fromModel",
        "toModel",
        "errorCode",
    ):
        if field in record:
            value = record[field]
            if (
                not isinstance(value, str)
                or not value
                or len(value) > 128
                or SAFE_TEXT_CONTROL.search(value)
                or SENSITIVE_LITERAL.search(value)
            ):
                _fail("escalation_state_invalid")
    if "continuationSent" in record and not isinstance(
        record["continuationSent"], bool
    ):
        _fail("escalation_state_invalid")
    return dict(record)


def write_transaction_state(root, request_id, phase, **fields) -> dict:
    request_id = _validate_request_id(request_id)
    if phase not in TRANSACTION_PHASES or not set(fields).issubset(
        TRANSACTION_FIELDS - {"requestId", "phase", "createdAt", "updatedAt"}
    ):
        _fail("escalation_state_invalid")
    paths = transaction_paths(root, request_id)
    state_path = Path(paths["state"])
    now = time.time()
    if state_path.exists():
        current = load_transaction_state(root, request_id)
        prior = current["phase"]
        if prior != phase:
            if prior in {"committed", "rolled_back", "recovery_required"}:
                _fail("escalation_state_invalid")
            if phase not in _TRANSACTION_TRANSITIONS.get(prior, frozenset()):
                _fail("escalation_state_invalid")
        record = dict(current)
        record.update(fields)
        record["phase"] = phase
        record["updatedAt"] = now
    else:
        if phase != "prepared":
            _fail("escalation_state_invalid")
        record = {
            "requestId": request_id,
            "phase": phase,
            "createdAt": now,
            "updatedAt": now,
            **fields,
        }
    record = _validate_transaction(record)
    _private_dir(paths["directory"])
    _atomic_bytes(paths["state"], _json_bytes(record))
    return record


def load_transaction_state(root, request_id) -> dict:
    paths = transaction_paths(root, request_id)
    try:
        return _validate_transaction(_load_json(paths["state"]))
    except EscalationError as error:
        if error.code == "escalation_record_missing":
            raise
        if error.code != "escalation_state_invalid":
            raise EscalationError("escalation_state_invalid") from error
        raise


def write_history_decision(root, decision) -> tuple[str, str]:
    raw = canonical_decision_bytes(decision)
    digest = hashlib.sha256(raw).hexdigest()
    root_path = _assert_no_symlinks(root)
    task_id = decision["taskId"]
    task_root = root_path / task_id
    target = task_root / (
        f"attempt-{decision['attemptCount']}-{digest[:12]}.json"
    )
    if task_root.parent != root_path or target.parent != task_root:
        _fail("escalation_path_invalid")
    if target.exists():
        existing = _private_file(target).read_bytes()
        if existing != raw:
            _fail("escalation_history_conflict")
        return str(target), digest
    _private_dir(root_path)
    _private_dir(task_root)
    try:
        descriptor = os.open(
            target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
    except FileExistsError:
        existing = _private_file(target).read_bytes()
        if existing != raw:
            _fail("escalation_history_conflict")
        return str(target), digest
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(target, 0o600)
    return str(target), digest


__all__ = [
    "ELIGIBLE_FAILURES",
    "REQUEST_FIELDS",
    "TERMINAL_STATES",
    "EscalationError",
    "create_request",
    "load_request",
    "write_request_state",
    "transaction_paths",
    "write_transaction_state",
    "load_transaction_state",
    "write_history_decision",
]
