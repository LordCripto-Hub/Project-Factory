#!/usr/bin/env python3
"""Supervise the opt-in, loopback-only hybrid-memory adapter."""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import time

from memory_canary import load_control
from memory_profile import update_memory_profile, MemoryProfileError


ROOT = Path(os.environ.get("INSTALL_DIR", Path.home() / "mypeople")).resolve()
RUNTIME = ROOT / "run"
SECRET = Path("/run/mypeople-secrets/MYPEOPLE_MEMORY_TOKEN")
READY = RUNTIME / "local-memory-ready.json"
URL = "http://127.0.0.1:18443/mcp"
PROJECT = "project-factory"


def _atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _ensure_secret() -> None:
    SECRET.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not SECRET.exists() or not SECRET.read_text(encoding="utf-8").strip():
        SECRET.write_text(secrets.token_urlsafe(32) + "\n", encoding="utf-8")
    os.chmod(SECRET, 0o600)


def _reconcile_profile() -> None:
    update_memory_profile(
        "enable",
        project=PROJECT,
        profiles_dir=Path(os.environ.get("PROJECT_PROFILES_DIR", RUNTIME / "project-profiles")),
        secret_path=SECRET,
        server_url=URL,
    )


def _server_environment() -> dict:
    source = ROOT / "experiments" / "memory-gate-b"
    env = os.environ.copy()
    env.update({
        "MYPEOPLE_LOCAL_MEMORY_TOKEN_FILE": str(SECRET),
        "MYPEOPLE_LOCAL_MEMORY_LEDGER": str(RUNTIME / "local-memory-ledger.jsonl"),
        "MYPEOPLE_LOCAL_MEMORY_READY": str(READY),
        "MYPEOPLE_LOCAL_MEMORY_QUERY": str(source / "scripts" / "query_automatic_memory.py"),
        "MYPEOPLE_LOCAL_MEMORY_DATASET": str(source / "datasets" / "project-factory-history-039a62988625"),
        "MYPEOPLE_LOCAL_MEMORY_LOCK": str(source / "docker" / "history-hybrid-039a62988625.dataset-lock.json"),
        "MYPEOPLE_LOCAL_MEMORY_RUNTIME": str(RUNTIME / "memory-emergency"),
        "MYPEOPLE_MEMORY_ALLOW_HTTP": "1",
    })
    return env


def _prepare_node_entrypoint() -> Path:
    modules = RUNTIME / "node_modules"
    source_modules = ROOT / "memory-gateway" / "node_modules"
    if not modules.exists():
        modules.symlink_to(source_modules, target_is_directory=True)
    entrypoint = RUNTIME / "local-memory-server.mjs"
    shutil.copy2(ROOT / "bin" / "local-memory-server.mjs", entrypoint)
    return entrypoint


def main() -> int:
    child = None
    stopping = False

    def stop(_signum=None, _frame=None):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stopping:
        mode = load_control(RUNTIME).get("mode", "off")
        if mode != "automatic":
            if child is not None:
                child.terminate()
                child.wait(timeout=10)
                child = None
            READY.unlink(missing_ok=True)
        elif child is None or child.poll() is not None:
            READY.unlink(missing_ok=True)
            try:
                _ensure_secret()
                _reconcile_profile()
                child = subprocess.Popen(
                    ["node", str(_prepare_node_entrypoint())],
                    env=_server_environment(),
                )
            except (OSError, MemoryProfileError):
                child = None
        time.sleep(1)
    if child is not None:
        child.terminate()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
    READY.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
