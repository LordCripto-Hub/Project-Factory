#!/usr/bin/env python3
"""Bounded project context contracts for MyPeople owner tasks."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import re
from urllib.parse import urlparse

MAX_CONTEXT_CHARS = 20_000
MAX_MEMORY_TOP_K = 3
MAX_MEMORY_HOPS = 0
MAX_MEMORY_TIMEOUT_SECONDS = 15
PROJECT_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ENV_REF_RE = re.compile(r"^env://([A-Z][A-Z0-9_]{1,63})$")
SECRET_KEY_RE = re.compile(r"token|secret|password|credentialvalue|apikey", re.I)

TOP_LEVEL_FIELDS = {
    "schemaVersion",
    "revision",
    "slug",
    "repository",
    "workingDirectory",
    "allowedBranches",
    "contextFiles",
    "verificationCommands",
    "allowedActions",
    "forbiddenActions",
    "limits",
    "memory",
}
LIMIT_FIELDS = {
    "contextChars",
    "memoryTopK",
    "memoryHops",
    "memoryTimeoutSeconds",
}
MEMORY_FIELDS = {"enabled", "serverUrl", "credentialRef"}


class ProfileError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def validate_project_slug(value) -> str:
    value = str(value or "").strip()
    if len(value) > 64 or not PROJECT_SLUG_RE.fullmatch(value):
        raise ProfileError("invalid_project_slug")
    return value


def _reject_secret_fields(value) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key != "credentialRef" and SECRET_KEY_RE.search(str(key)):
                raise ProfileError("plaintext_secret_forbidden")
            _reject_secret_fields(child)
    elif isinstance(value, list):
        for child in value:
            _reject_secret_fields(child)


def _require_fields(value: dict, required: set[str], scope: str) -> None:
    missing = sorted(required - set(value))
    if missing:
        raise ProfileError(f"missing_{scope}_field")


def _reject_unknown(value: dict, allowed: set[str]) -> None:
    if set(value) - allowed:
        raise ProfileError("unknown_field")


def _string_list(value, code: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise ProfileError(code)
    result = []
    for item in value:
        item = str(item or "").strip()
        if not item or len(item) > 500:
            raise ProfileError(code)
        result.append(item)
    return result


def _absolute_directory(value) -> str:
    value = str(value or "").strip()
    windows_absolute = bool(re.match(r"^[A-Za-z]:[\\/]", value))
    if not value or not (os.path.isabs(value) or windows_absolute):
        raise ProfileError("invalid_working_directory")
    return value


def _validate_memory_url(value: str) -> str:
    value = str(value or "").strip()
    parsed = urlparse(value)
    if parsed.scheme == "https" and parsed.netloc:
        return value
    allow_http = os.environ.get("MYPEOPLE_MEMORY_ALLOW_HTTP") == "1"
    if (
        allow_http
        and parsed.scheme == "http"
        and parsed.hostname in {"127.0.0.1", "localhost"}
        and parsed.netloc
    ):
        return value
    raise ProfileError("memory_https_required")


def validate_profile(value) -> dict:
    if not isinstance(value, dict):
        raise ProfileError("profile_object_required")
    _reject_secret_fields(value)
    _reject_unknown(value, TOP_LEVEL_FIELDS)
    _require_fields(value, TOP_LEVEL_FIELDS, "profile")
    if value.get("schemaVersion") != 1:
        raise ProfileError("unsupported_schema_version")
    if not isinstance(value.get("revision"), int) or value["revision"] < 1:
        raise ProfileError("invalid_revision")

    result = copy.deepcopy(value)
    result["slug"] = validate_project_slug(value.get("slug"))
    result["repository"] = str(value.get("repository") or "").strip()
    if not result["repository"]:
        raise ProfileError("repository_required")
    result["workingDirectory"] = _absolute_directory(value.get("workingDirectory"))
    for field in (
        "allowedBranches",
        "contextFiles",
        "verificationCommands",
        "allowedActions",
        "forbiddenActions",
    ):
        result[field] = _string_list(value.get(field), f"invalid_{field}")

    limits = value.get("limits")
    if not isinstance(limits, dict):
        raise ProfileError("invalid_limits")
    _reject_unknown(limits, LIMIT_FIELDS)
    _require_fields(limits, LIMIT_FIELDS, "limit")
    context_chars = limits.get("contextChars")
    top_k = limits.get("memoryTopK")
    hops = limits.get("memoryHops")
    timeout = limits.get("memoryTimeoutSeconds")
    if not isinstance(context_chars, int) or not 256 <= context_chars <= MAX_CONTEXT_CHARS:
        raise ProfileError("invalid_context_chars")
    if not isinstance(top_k, int) or not 1 <= top_k <= MAX_MEMORY_TOP_K:
        raise ProfileError("invalid_memory_top_k")
    if not isinstance(hops, int) or hops != MAX_MEMORY_HOPS:
        raise ProfileError("invalid_memory_hops")
    if not isinstance(timeout, (int, float)) or not 0 < timeout <= MAX_MEMORY_TIMEOUT_SECONDS:
        raise ProfileError("invalid_memory_timeout")
    result["limits"] = {
        "contextChars": context_chars,
        "memoryTopK": top_k,
        "memoryHops": hops,
        "memoryTimeoutSeconds": timeout,
    }

    memory = value.get("memory")
    if not isinstance(memory, dict):
        raise ProfileError("invalid_memory")
    _reject_unknown(memory, MEMORY_FIELDS)
    _require_fields(memory, MEMORY_FIELDS, "memory")
    if not isinstance(memory.get("enabled"), bool):
        raise ProfileError("invalid_memory_enabled")
    server_url = _validate_memory_url(memory.get("serverUrl"))
    credential_ref = str(memory.get("credentialRef") or "").strip()
    if not ENV_REF_RE.fullmatch(credential_ref):
        raise ProfileError("invalid_credential_reference")
    result["memory"] = {
        "enabled": memory["enabled"],
        "serverUrl": server_url,
        "credentialRef": credential_ref,
    }
    return result


def load_profile(directory, slug) -> dict:
    slug = validate_project_slug(slug)
    root = Path(directory).resolve()
    path = (root / f"{slug}.json").resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ProfileError("profile_path_escape") from error
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ProfileError("profile_not_found") from error
    except (OSError, json.JSONDecodeError) as error:
        raise ProfileError("invalid_profile_json") from error
    result = validate_profile(value)
    if result["slug"] != slug:
        raise ProfileError("profile_slug_mismatch")
    return result
