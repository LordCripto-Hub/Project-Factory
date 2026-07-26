#!/usr/bin/env python3
"""Typed validation for the process hosted by a MyPeople tmux window."""
from __future__ import annotations

import os
import shlex
import subprocess
import time


IDENTITY_FIELDS = ("backend", "profile", "model")
ARGUMENT_FIELDS = ("cwd", "owner_task_id")


def _result(state: str, target: str, checks: dict[str, str]) -> dict:
    return {
        "ok": state == "ready",
        "state": state,
        "target": target,
        "observedAt": time.time(),
        "checks": checks,
    }


def validate_agent_identity(expected: dict, observation: dict) -> dict:
    target = str(expected.get("target") or observation.get("target") or "")
    checks = {
        "window": "pass",
        "process": "pass",
        "backend": "pass",
        "profile": "pass",
        "model": "pass",
        "arguments": "pass",
        "readiness": "pass",
    }
    if not observation.get("windowExists"):
        checks["window"] = "fail"
        return _result("window_missing", target, checks)
    if not observation.get("processAlive"):
        checks["process"] = "fail"
        return _result("process_missing", target, checks)
    for field in IDENTITY_FIELDS:
        wanted = str(expected.get(field) or "")
        seen = str(observation.get(field) or "")
        if wanted and seen != wanted:
            checks[field] = "fail"
            return _result(f"{field}_mismatch", target, checks)
    for field in ARGUMENT_FIELDS:
        wanted = os.path.realpath(str(expected.get(field) or "")) if field == "cwd" else str(expected.get(field) or "")
        seen = os.path.realpath(str(observation.get(field) or "")) if field == "cwd" else str(observation.get(field) or "")
        if wanted and seen != wanted:
            checks["arguments"] = "fail"
            return _result("arguments_mismatch", target, checks)
    if not observation.get("ready"):
        checks["readiness"] = "fail"
        return _result("not_ready", target, checks)
    return _result("ready", target, checks)


def _process_rows() -> list[tuple[int, int, str]]:
    result = subprocess.run(
        ["ps", "-eo", "pid=,ppid=,args="],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    rows = []
    for raw in result.stdout.splitlines():
        parts = raw.strip().split(None, 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            rows.append((int(parts[0]), int(parts[1]), parts[2]))
    return rows


def _descendants(root_pid: int) -> list[tuple[int, str]]:
    rows = _process_rows()
    children: dict[int, list[tuple[int, str]]] = {}
    for pid, ppid, command in rows:
        children.setdefault(ppid, []).append((pid, command))
    processes = []
    pending = [root_pid]
    seen = set()
    while pending:
        parent = pending.pop()
        if parent in seen:
            continue
        seen.add(parent)
        for pid, command in children.get(parent, []):
            processes.append((pid, command))
            pending.append(pid)
    return processes


def _command_backend(commands: list[str]) -> str:
    tokens = [shlex.split(command, posix=True) for command in commands]
    executables = {os.path.basename(parts[0]) for parts in tokens if parts}
    if "codex" in executables:
        return "codex"
    if "claude" in executables:
        return "claude"
    return ""


def _provider_process(processes: list[tuple[int, str]]) -> tuple[int, list[str]]:
    for pid, command in processes:
        try:
            parts = shlex.split(command, posix=True)
        except ValueError:
            continue
        if parts and os.path.basename(parts[0]) in {"codex", "claude"}:
            return pid, parts
    return 0, []


def _process_environment(pid: int) -> dict[str, str]:
    if not pid:
        return {}
    try:
        raw = open(f"/proc/{pid}/environ", "rb").read()
    except OSError:
        return {}
    result = {}
    for item in raw.split(b"\0"):
        if b"=" not in item:
            continue
        key, value = item.split(b"=", 1)
        if key in {b"MYPEOPLE_PROVIDER_PROFILE", b"OWNER_TASK_ID", b"CODEX_HOME"}:
            result[key.decode()] = value.decode(errors="replace")
    return result


def _argument(parts: list[str], name: str) -> str:
    try:
        return parts[parts.index(name) + 1]
    except (ValueError, IndexError):
        return ""


def observe_tmux_agent(target: str, runner) -> dict:
    display = runner(
        ["display-message", "-p", "-t", target, "#{pane_pid}\t#{pane_current_path}"],
        check=False,
        capture=True,
    )
    if display.returncode != 0:
        return {"target": target, "windowExists": False, "processAlive": False, "ready": False}
    raw = (display.stdout or "").strip().split("\t", 1)
    pane_pid = int(raw[0]) if raw and raw[0].isdigit() else 0
    cwd = raw[1] if len(raw) == 2 else ""
    processes = _descendants(pane_pid) if pane_pid else []
    commands = [command for _, command in processes]
    provider_pid, provider_args = _provider_process(processes)
    environment = _process_environment(provider_pid)
    capture = runner(
        ["capture-pane", "-p", "-S", "-80", "-t", target],
        check=False,
        capture=True,
    )
    text = capture.stdout or ""
    ready = capture.returncode == 0 and any(
        marker in text
        for marker in ("OpenAI Codex", "Claude Code", "bypass permissions on", "› ")
    )
    return {
        "target": target,
        "windowExists": True,
        "processAlive": bool(provider_pid),
        "backend": _command_backend(commands),
        "profile": environment.get("MYPEOPLE_PROVIDER_PROFILE", ""),
        "model": _argument(provider_args, "--model"),
        "cwd": cwd,
        "owner_task_id": environment.get("OWNER_TASK_ID", ""),
        "ready": ready,
    }


def validate_tmux_agent(target: str, expected: dict, runner) -> dict:
    return validate_agent_identity(
        {**expected, "target": target},
        observe_tmux_agent(target, runner),
    )
