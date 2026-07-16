#!/usr/bin/env python3
"""Atomic activation updates for bounded project memory profiles."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

from project_context import (
    MAX_CREDENTIAL_BYTES,
    ProfileError,
    load_profile,
    validate_profile,
    validate_project_slug,
)

FILE_CREDENTIAL_REFERENCE = (
    "file:///run/mypeople-secrets/MYPEOPLE_MEMORY_TOKEN"
)
DEFAULT_SECRET_PATH = Path("/run/mypeople-secrets/MYPEOPLE_MEMORY_TOKEN")


class MemoryProfileError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _load_profile(profiles_dir, project: str) -> dict:
    try:
        return load_profile(profiles_dir, project)
    except ProfileError as error:
        raise MemoryProfileError(error.code) from error


def _require_secret(secret_path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(os.fspath(secret_path), flags)
        try:
            value = os.read(descriptor, MAX_CREDENTIAL_BYTES + 1)
        finally:
            os.close(descriptor)
    except OSError as error:
        raise MemoryProfileError("memory_secret_unavailable") from error
    if not value.strip() or len(value) > MAX_CREDENTIAL_BYTES:
        raise MemoryProfileError("memory_secret_unavailable")


def _atomic_profile_write(path: Path, value: dict) -> None:
    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def update_memory_profile(
    action: str,
    *,
    project: str,
    profiles_dir,
    secret_path=DEFAULT_SECRET_PATH,
    server_url: str | None = None,
) -> dict:
    if action not in {"enable", "disable"}:
        raise MemoryProfileError("invalid_memory_action")
    try:
        project = validate_project_slug(project)
    except ProfileError as error:
        raise MemoryProfileError(error.code) from error

    profiles_root = Path(profiles_dir).resolve()
    current = _load_profile(profiles_root, project)
    updated = copy.deepcopy(current)

    if action == "enable":
        _require_secret(secret_path)
        updated["memory"] = {
            "enabled": True,
            "serverUrl": str(server_url or "").strip(),
            "credentialRef": FILE_CREDENTIAL_REFERENCE,
        }
    else:
        updated["memory"] = copy.deepcopy(current["memory"])
        updated["memory"]["enabled"] = False
        if server_url is not None:
            updated["memory"]["serverUrl"] = str(server_url).strip()

    if updated["memory"] == current["memory"]:
        return {
            "project": project,
            "revision": current["revision"],
            "memoryEnabled": current["memory"]["enabled"],
        }

    updated["revision"] += 1
    try:
        updated = validate_profile(updated)
    except ProfileError as error:
        raise MemoryProfileError(error.code) from error
    path = profiles_root / f"{project}.json"
    _atomic_profile_write(path, updated)
    return {
        "project": project,
        "revision": updated["revision"],
        "memoryEnabled": updated["memory"]["enabled"],
    }
