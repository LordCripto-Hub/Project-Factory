#!/usr/bin/env python3
import contextlib
import json
import os
import subprocess
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
MP_PATH = os.path.join(ROOT, "bin", "mp")
CORE_AGENT_IDS = ("node-1/main:Boss", "node-1/nightwatch:Nightwatch")
MODEL_ALLOWLIST = ("gpt-5.6-sol", "gpt-5.6-luna")
_OPERATION_LOCK = threading.Lock()
_ACTIVE_OPERATIONS = set()


class ControlError(Exception):
    def __init__(self, code, status=400):
        super().__init__(code)
        self.code = code
        self.status = status


def capabilities():
    return {"agents": list(CORE_AGENT_IDS), "models": list(MODEL_ALLOWLIST)}


def _agent_id(body):
    if not isinstance(body, dict):
        raise ControlError("invalid_request")
    value = body.get("agent_id")
    if not isinstance(value, str) or value not in CORE_AGENT_IDS:
        raise ControlError("unsupported_agent", 403)
    return value


def _record(agent_id, roster):
    matches = [row for row in roster if isinstance(row, dict) and row.get("agent_id") == agent_id]
    if not matches:
        raise ControlError("roster_record_missing", 404)
    if len(matches) != 1:
        raise ControlError("roster_record_ambiguous", 409)
    record = matches[0]
    if record.get("backend") != "codex":
        raise ControlError("backend_mismatch", 409)
    return record


def build_command(action, body, roster):
    agent_id = _agent_id(body)
    record = _record(agent_id, roster)
    if action == "kill":
        if record.get("state") != "alive" or record.get("retired"):
            raise ControlError("agent_not_alive", 409)
        return [MP_PATH, "kill", agent_id, "--reason", "hud-operator"]
    if action == "revive":
        if record.get("state") == "alive" and not record.get("retired"):
            raise ControlError("agent_already_alive", 409)
        return [MP_PATH, "revive", agent_id]
    if action == "switch":
        model = body.get("model")
        if not isinstance(model, str) or len(model) > 64 or model not in MODEL_ALLOWLIST:
            raise ControlError("unsupported_model", 400)
        return [MP_PATH, "switch", agent_id, "--backend", "codex", "--model", model]
    raise ControlError("unsupported_action", 404)


def load_roster(path):
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, ValueError):
        raise ControlError("roster_unavailable", 503)
    if not isinstance(value, list):
        raise ControlError("roster_invalid", 503)
    return value


@contextlib.contextmanager
def agent_operation(agent_id):
    with _OPERATION_LOCK:
        if agent_id in _ACTIVE_OPERATIONS:
            raise ControlError("operation_in_progress", 409)
        _ACTIVE_OPERATIONS.add(agent_id)
    try:
        yield
    finally:
        with _OPERATION_LOCK:
            _ACTIVE_OPERATIONS.discard(agent_id)


def _confirm(action, body, before, after):
    if action == "kill":
        ok = after.get("state") == "dead" and after.get("retired") is True
    elif action == "revive":
        ok = after.get("state") == "alive" and not after.get("retired") and after.get("model") == before.get("model")
    else:
        ok = after.get("state") == "alive" and not after.get("retired") and after.get("model") == body.get("model")
    if not ok:
        raise ControlError("state_not_confirmed", 409)


def execute(action, body, roster_path, runner=subprocess.run):
    agent_id = _agent_id(body)
    with agent_operation(agent_id):
        before = _record(agent_id, load_roster(roster_path))
        command = build_command(action, body, [before])
        try:
            completed = runner(command, capture_output=True, text=True, timeout=90, shell=False)
        except subprocess.TimeoutExpired:
            raise ControlError("control_timeout", 504)
        except OSError:
            raise ControlError("control_unavailable", 503)
        if completed.returncode:
            raise ControlError("control_failed", 409)
        after = _record(agent_id, load_roster(roster_path))
        _confirm(action, body, before, after)
        return {"ok": True, "agent_id": agent_id, "state": after.get("state", "unknown"), "model": after.get("model", "")}

