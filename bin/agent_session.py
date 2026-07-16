#!/usr/bin/env python3
"""Provider-session identity primitives for managed MyPeople agents."""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import time


SESSION_ID = re.compile(r"[A-Za-z0-9._-]{8,160}")
SAFE_COMPONENT = re.compile(r"[A-Za-z0-9._-]{1,80}")


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
    root = Path(os.path.realpath(lock_root))
    directory = root / backend_name
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
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
    return sorted(str(path.resolve()) for path in paths)


def validate_resume_evidence(
    backend: str,
    session_id: str,
    *,
    codex_home: str = "",
    claude_config_dir: str = "",
) -> str:
    paths = session_files(
        backend,
        session_id,
        codex_home=codex_home,
        claude_config_dir=claude_config_dir,
    )
    if not paths:
        raise SessionError("session_missing")
    return paths[0]
