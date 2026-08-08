#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import time

from mpcommon import load_json
from provider_profiles import validate_profile_id


__all__ = ["SwitchBusy", "acquire_lock", "release_lock"]


class SwitchBusy(RuntimeError):
    pass


def _private_dir(path: str) -> None:
    os.makedirs(path, mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)


def acquire_lock(path: str, transaction_id: str) -> None:
    transaction_id = validate_profile_id(transaction_id)
    path = os.path.realpath(path)
    _private_dir(os.path.dirname(path))
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise SwitchBusy("a provider switch is already active") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(
                {"transaction": transaction_id, "created": time.time()},
                handle,
                sort_keys=True,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(path, 0o600)
    except Exception:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        raise


def release_lock(path: str, transaction_id: str) -> None:
    transaction_id = validate_profile_id(transaction_id)
    path = os.path.realpath(path)
    current = load_json(path, {})
    if current.get("transaction") != transaction_id:
        return
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
