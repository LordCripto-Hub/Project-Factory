#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time


def pause(path: str | Path, reason: str) -> dict:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "schemaVersion": 1,
        "paused": True,
        "reason": str(reason or "operator requested").strip(),
        "pausedAt": datetime.now(timezone.utc).isoformat(),
    }
    temporary = target.with_name(
        f"{target.name}.{os.getpid()}.{time.time_ns()}.tmp"
    )
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(record, stream, ensure_ascii=False, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        os.chmod(target, 0o600)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return record


def resume(path: str | Path) -> None:
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass


def status(path: str | Path) -> dict:
    target = Path(path)
    if not target.is_file():
        return {"paused": False}
    try:
        record = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"paused": True, "reason": "pause marker unreadable"}
    return record if isinstance(record, dict) else {"paused": True}
