#!/usr/bin/env python3
"""Private runtime control and receipts for the bounded memory canary."""
from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
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
