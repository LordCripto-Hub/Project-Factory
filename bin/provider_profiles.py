#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re


SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def validate_profile_id(value: str) -> str:
    value = str(value or "")
    if not SAFE_ID.fullmatch(value):
        raise ValueError("invalid provider profile id")
    return value


def load_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def resolve_profile(bindings: dict, agent_id: str) -> str:
    selected = (bindings.get("agentProfiles") or {}).get(agent_id) or bindings.get(
        "globalProfile"
    )
    return validate_profile_id(selected)


def resolve_model(profile: dict, role: str) -> str:
    model = (profile.get("roleModels") or {}).get(role) or profile.get(
        "defaultModel"
    )
    if not isinstance(model, str) or not model.strip():
        raise ValueError("provider profile has no model for role")
    return model.strip()


def codex_home(runtime_root: str, profile_id: str) -> str:
    root = os.path.realpath(runtime_root)
    path = os.path.realpath(
        os.path.join(root, "codex", validate_profile_id(profile_id))
    )
    if not path.startswith(root + os.sep):
        raise ValueError("provider home escapes runtime root")
    return path
