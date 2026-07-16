#!/usr/bin/env python3
"""Provider-session identity primitives for managed MyPeople agents."""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import time


SESSION_ID = re.compile(r"[A-Za-z0-9._-]{8,160}")
SAFE_COMPONENT = re.compile(r"[A-Za-z0-9._-]{1,80}")
HANDOFF_SNAPSHOT_FIELDS = (
    "agent_id",
    "backend",
    "model",
    "provider_profile",
    "cwd",
    "lifecycle",
    "owner_task_id",
    "boss_id",
    "is_master",
    "taskspec_sha256",
    "role_contract_sha256",
    "role_contract_version",
)


class SessionError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def validate_session_id(value: str) -> str:
    candidate = str(value or "").strip()
    if not SESSION_ID.fullmatch(candidate):
        raise SessionError("session_id_invalid")
    return candidate


def _safe_component(value: str) -> str:
    candidate = str(value or "").strip()
    if not SAFE_COMPONENT.fullmatch(candidate) or candidate in {".", ".."}:
        raise SessionError("session_capture_path_invalid")
    return candidate


def _codex_sessions_root(codex_home: str) -> Path:
    return Path(os.path.realpath(codex_home)) / "sessions"


def snapshot_codex_sessions(codex_home: str) -> set[str]:
    root = _codex_sessions_root(codex_home)
    if not root.is_dir():
        return set()
    return {
        str(path.resolve())
        for path in root.glob("**/*.jsonl")
        if path.is_file()
    }


def read_codex_session_meta(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as stream:
            event = json.loads(stream.readline())
        payload = event.get("payload", {})
        if event.get("type") != "session_meta" or not isinstance(payload, dict):
            raise SessionError("session_metadata_invalid")
        raw_cwd = str(payload.get("cwd") or "")
        if not raw_cwd:
            raise SessionError("session_metadata_invalid")
        return {
            "session_id": validate_session_id(
                payload.get("id") or payload.get("session_id")
            ),
            "cwd": os.path.realpath(raw_cwd),
            "path": str(path.resolve()),
        }
    except SessionError:
        raise
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
        raise SessionError("session_metadata_invalid") from error


def discover_codex_session(
    codex_home: str,
    cwd: str,
    before: set[str],
    *,
    timeout: float = 45.0,
    poll: float = 0.1,
) -> dict:
    expected_cwd = os.path.realpath(cwd)
    deadline = time.monotonic() + max(0.0, float(timeout))
    wrong_cwd = False
    while True:
        current = snapshot_codex_sessions(codex_home)
        candidates = sorted(current - set(before))
        if candidates:
            metadata = [read_codex_session_meta(Path(path)) for path in candidates]
            if len(metadata) != 1:
                raise SessionError("session_capture_ambiguous")
            if metadata[0]["cwd"] == expected_cwd:
                return metadata[0]
            wrong_cwd = True
        if time.monotonic() >= deadline:
            raise SessionError(
                "session_cwd_mismatch" if wrong_cwd else "session_capture_timeout"
            )
        time.sleep(max(0.001, float(poll)))


def _prepare_private_directory(path: Path) -> Path:
    candidate = os.path.abspath(path)
    try:
        os.makedirs(candidate, mode=0o700, exist_ok=True)
        if candidate != os.path.realpath(candidate):
            raise SessionError("session_capture_path_invalid")
        metadata = os.lstat(candidate)
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise SessionError("session_capture_path_invalid")
        os.chmod(candidate, 0o700)
        return Path(candidate)
    except SessionError:
        raise
    except OSError as error:
        raise SessionError("session_capture_path_invalid") from error


@contextlib.contextmanager
def capture_lock(
    lock_root: str,
    backend: str,
    profile: str,
    *,
    timeout: float = 5.0,
    poll: float = 0.05,
):
    backend_name = _safe_component(backend)
    profile_name = _safe_component(profile or "default")
    root = _prepare_private_directory(Path(os.path.abspath(lock_root)))
    directory = _prepare_private_directory(root / backend_name)
    path = directory / f"{profile_name}.lock"
    descriptor = os.open(
        path,
        os.O_CREAT
        | os.O_RDWR
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    os.fchmod(descriptor, 0o600)
    deadline = time.monotonic() + max(0.0, float(timeout))
    acquired = False
    try:
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError as error:
                if time.monotonic() >= deadline:
                    raise SessionError("session_capture_busy") from error
                time.sleep(max(0.001, float(poll)))
        yield str(path)
    finally:
        if acquired:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def apply_resume_args(
    backend: str,
    args: list[str],
    session_id: str,
) -> list[str]:
    sid = validate_session_id(session_id)
    if backend == "codex":
        if not args or args[0] != "codex":
            raise SessionError("resume_argv_invalid")
        return [args[0], "resume", *args[1:], sid]
    if backend == "claude":
        if not args or args[0] != "claude":
            raise SessionError("resume_argv_invalid")
        return [*args, "--resume", sid]
    raise SessionError("session_backend_unsupported")


def session_files(
    backend: str,
    session_id: str,
    *,
    codex_home: str = "",
    claude_config_dir: str = "",
) -> list[str]:
    sid = validate_session_id(session_id)
    if backend == "codex":
        if not codex_home:
            raise SessionError("session_identity_mismatch")
        root = _codex_sessions_root(codex_home)
        paths = [
            path
            for path in root.glob(f"**/*{sid}*.jsonl")
            if path.is_file()
        ]
    elif backend == "claude":
        root = Path(
            os.path.realpath(
                claude_config_dir
                or os.environ.get("CLAUDE_CONFIG_DIR")
                or os.path.expanduser("~/.claude")
            )
        )
        paths = [
            path
            for path in (root / "projects").glob(f"**/{sid}.jsonl")
            if path.is_file()
        ]
    else:
        raise SessionError("session_backend_unsupported")
    return sorted(str(path.absolute()) for path in paths)


def _strict_session_file(path: str, root: Path) -> Path:
    candidate = os.path.abspath(path)
    resolved = os.path.realpath(candidate)
    root_path = os.path.realpath(root)
    if (
        candidate != resolved
        or os.path.commonpath((root_path, resolved)) != root_path
    ):
        raise SessionError("session_identity_mismatch")
    try:
        metadata = os.lstat(candidate)
    except OSError as error:
        raise SessionError("session_missing") from error
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_mode & 0o077
    ):
        raise SessionError("session_identity_mismatch")
    return Path(candidate)


def _validate_claude_transcript(
    path: Path,
    session_id: str,
    expected_cwd: str,
) -> None:
    found_id = False
    found_cwd = False
    try:
        with path.open(encoding="utf-8") as stream:
            for index, raw in enumerate(stream):
                if index >= 100:
                    break
                if not raw.strip():
                    continue
                event = json.loads(raw)
                if not isinstance(event, dict):
                    continue
                payload = event.get("payload")
                if not isinstance(payload, dict):
                    payload = {}
                raw_id = (
                    event.get("sessionId")
                    or event.get("session_id")
                    or payload.get("sessionId")
                    or payload.get("session_id")
                )
                if raw_id:
                    if validate_session_id(raw_id) != session_id:
                        raise SessionError("session_identity_mismatch")
                    found_id = True
                raw_cwd = event.get("cwd") or payload.get("cwd")
                if raw_cwd:
                    if os.path.realpath(str(raw_cwd)) != expected_cwd:
                        raise SessionError("session_cwd_mismatch")
                    found_cwd = True
                if found_id and found_cwd:
                    return
    except SessionError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError) as error:
        raise SessionError("session_identity_mismatch") from error
    raise SessionError("session_identity_mismatch")


def validate_resume_evidence(
    backend: str,
    session_id: str,
    *,
    codex_home: str = "",
    claude_config_dir: str = "",
    expected_cwd: str = "",
) -> str:
    cwd = os.path.realpath(str(expected_cwd or ""))
    if not expected_cwd:
        raise SessionError("session_identity_mismatch")
    paths = session_files(
        backend,
        session_id,
        codex_home=codex_home,
        claude_config_dir=claude_config_dir,
    )
    if not paths:
        raise SessionError("session_missing")
    if len(paths) != 1:
        raise SessionError("session_identity_mismatch")
    if backend == "codex":
        root = _codex_sessions_root(codex_home)
        path = _strict_session_file(paths[0], root)
        metadata = read_codex_session_meta(path)
        if metadata["session_id"] != validate_session_id(session_id):
            raise SessionError("session_identity_mismatch")
        if metadata["cwd"] != cwd:
            raise SessionError("session_cwd_mismatch")
    elif backend == "claude":
        root = Path(
            os.path.realpath(
                claude_config_dir
                or os.environ.get("CLAUDE_CONFIG_DIR")
                or os.path.expanduser("~/.claude")
            )
        ) / "projects"
        path = _strict_session_file(paths[0], root)
        _validate_claude_transcript(
            path,
            validate_session_id(session_id),
            cwd,
        )
    else:
        raise SessionError("session_backend_unsupported")
    return str(path)


def _read_private_json(path: str):
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
            raise SessionError("fresh_handoff_not_authorized")
        with os.fdopen(descriptor, encoding="utf-8") as stream:
            descriptor = -1
            return json.load(stream)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _require_private_directory(path: str) -> None:
    metadata = os.lstat(path)
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_mode & 0o077
    ):
        raise SessionError("fresh_handoff_not_authorized")


def validate_fresh_handoff(
    transactions_root: str,
    switch_lock: str,
    transaction_id: str,
    handoff_path: str,
    agent_id: str,
) -> dict:
    try:
        transaction = _safe_component(transaction_id)
        root = os.path.realpath(transactions_root)
        transaction_candidate = os.path.abspath(
            os.path.join(root, transaction)
        )
        transaction_dir = os.path.realpath(transaction_candidate)
        if (
            transaction_candidate != transaction_dir
            or
            transaction_dir == root
            or os.path.commonpath((root, transaction_dir)) != root
        ):
            raise SessionError("fresh_handoff_not_authorized")
        _require_private_directory(transaction_dir)

        lock_candidate = os.path.abspath(switch_lock)
        resolved_lock = os.path.realpath(lock_candidate)
        if lock_candidate != resolved_lock:
            raise SessionError("fresh_handoff_not_authorized")
        lock = _read_private_json(resolved_lock)
        state = _read_private_json(
            os.path.join(transaction_dir, "state.json")
        )
        if (
            not isinstance(lock, dict)
            or lock.get("transaction") != transaction
            or not isinstance(state, dict)
            or state.get("transaction") != transaction
            or state.get("phase") != "stopped"
        ):
            raise SessionError("fresh_handoff_not_authorized")

        handoff_candidate = os.path.abspath(handoff_path)
        resolved_handoff = os.path.realpath(handoff_candidate)
        if (
            handoff_candidate != resolved_handoff
            or
            resolved_handoff == transaction_dir
            or os.path.commonpath((transaction_dir, resolved_handoff))
            != transaction_dir
        ):
            raise SessionError("fresh_handoff_not_authorized")
        _require_private_directory(os.path.dirname(resolved_handoff))
        handoff = _read_private_json(resolved_handoff)

        roster = _read_private_json(
            os.path.join(transaction_dir, "roster.json")
        )
        if not isinstance(roster, list):
            raise SessionError("fresh_handoff_not_authorized")
        matches = [
            row
            for row in roster
            if isinstance(row, dict) and row.get("agent_id") == agent_id
        ]
        if len(matches) != 1:
            raise SessionError("fresh_handoff_not_authorized")
        record = matches[0]
        if (
            not isinstance(handoff, dict)
            or not isinstance(handoff.get("agent"), dict)
            or handoff["agent"].get("agent_id") != agent_id
            or not isinstance(handoff.get("snapshot"), dict)
        ):
            raise SessionError("fresh_handoff_not_authorized")
        snapshot = handoff["snapshot"]
        for field in HANDOFF_SNAPSHOT_FIELDS:
            if field not in snapshot:
                raise SessionError("fresh_handoff_not_authorized")
            expected = record.get(field)
            actual = snapshot.get(field)
            if field == "cwd":
                expected = os.path.realpath(str(expected or ""))
                actual = os.path.realpath(str(actual or ""))
            if actual != expected:
                raise SessionError("fresh_handoff_not_authorized")
        target_backend = state.get("targetBackend")
        if target_backend and target_backend not in {"codex", "claude"}:
            raise SessionError("fresh_handoff_not_authorized")
        effective_backend = target_backend or record.get("backend")
        target_profile = str(state.get("targetProfile") or "")
        if effective_backend == "codex":
            _safe_component(target_profile)
        elif target_profile:
            raise SessionError("fresh_handoff_not_authorized")
        return {"record": record, "handoff": handoff, "state": state}
    except SessionError as error:
        if error.code == "fresh_handoff_not_authorized":
            raise
        raise SessionError("fresh_handoff_not_authorized") from error
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        raise SessionError("fresh_handoff_not_authorized") from error
