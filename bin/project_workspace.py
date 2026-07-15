#!/usr/bin/env python3
"""Validated, idempotent Git workspace and tmux rehydration."""
from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
from typing import Callable

from mpcommon import atomic_json, load_json


SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
TMUX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
HTTPS_GIT = re.compile(r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.git$")


class WorkspaceError(RuntimeError):
    pass


def _run(args, **kwargs):
    return subprocess.run(
        args,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **kwargs,
    )


def _inside(path: str, root: str) -> bool:
    try:
        return os.path.commonpath((path, root)) == root and path != root
    except ValueError:
        return False


def validate_project(value: dict, workspace_root: str) -> dict:
    if not isinstance(value, dict) or value.get("schemaVersion") != 1:
        raise WorkspaceError("unsupported workspace project schema")
    root = os.path.realpath(workspace_root)
    workspace_value = str(value.get("workspace") or "")
    if not os.path.isabs(workspace_value):
        raise WorkspaceError("workspace must be absolute")
    workspace = os.path.realpath(workspace_value)
    normalized = {
        "schemaVersion": 1,
        "slug": str(value.get("slug") or ""),
        "repository": str(value.get("repository") or ""),
        "branch": str(value.get("branch") or ""),
        "workspace": workspace,
        "tmuxSession": str(value.get("tmuxSession") or ""),
    }
    if not SLUG.fullmatch(normalized["slug"]):
        raise WorkspaceError("invalid project slug")
    if not HTTPS_GIT.fullmatch(normalized["repository"]):
        raise WorkspaceError("repository must be an HTTPS GitHub .git URL")
    if not REF.fullmatch(normalized["branch"]) or ".." in normalized["branch"]:
        raise WorkspaceError("invalid project branch")
    if not TMUX.fullmatch(normalized["tmuxSession"]):
        raise WorkspaceError("invalid tmux session")
    if not _inside(workspace, root):
        raise WorkspaceError("workspace escapes the configured root")
    return normalized


def load_projects(manifest_path: str, workspace_root: str) -> list[dict]:
    manifest = load_json(manifest_path, None)
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1:
        raise WorkspaceError("unsupported project workspace manifest")
    projects = manifest.get("projects")
    if not isinstance(projects, list) or not projects:
        raise WorkspaceError("workspace manifest has no projects")
    normalized = [validate_project(item, workspace_root) for item in projects]
    slugs = [item["slug"] for item in normalized]
    sessions = [item["tmuxSession"] for item in normalized]
    if len(slugs) != len(set(slugs)) or len(sessions) != len(set(sessions)):
        raise WorkspaceError("workspace manifest has duplicate identities")
    return normalized


def _checked(result, action: str):
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise WorkspaceError(f"{action} failed: {detail[:300]}")
    return result


def ensure_workspace(project: dict, runner: Callable = _run) -> str:
    workspace = pathlib.Path(project["workspace"])
    if workspace.exists():
        if not workspace.is_dir():
            raise WorkspaceError("workspace path is not a directory")
        entries = list(workspace.iterdir())
        if not entries:
            workspace.rmdir()
        elif not (workspace / ".git").is_dir():
            raise WorkspaceError("existing workspace is not a Git checkout")
    if not workspace.exists():
        workspace.parent.mkdir(parents=True, exist_ok=True)
        result = runner([
            "git", "clone", "--origin", "origin", "--branch", project["branch"],
            "--single-branch", project["repository"], str(workspace),
        ])
        _checked(result, "git clone")
        return "cloned"
    remote = runner([
        "git", "-C", str(workspace), "remote", "get-url", "origin",
    ])
    _checked(remote, "git origin inspection")
    if (remote.stdout or "").strip().rstrip("/") != project["repository"].rstrip("/"):
        raise WorkspaceError("workspace origin does not match the manifest")
    return "existing"


def ensure_tmux_session(project: dict, runner: Callable = _run) -> bool:
    result = runner(["tmux", "has-session", "-t", project["tmuxSession"]])
    if result.returncode == 0:
        return False
    created = runner([
        "tmux", "new-session", "-d", "-s", project["tmuxSession"],
        "-c", project["workspace"],
    ])
    _checked(created, "tmux session creation")
    runner(["tmux", "set-option", "-t", project["tmuxSession"], "automatic-rename", "off"])
    return True


def project_profile(project: dict) -> dict:
    return {
        "schemaVersion": 1,
        "revision": 1,
        "slug": project["slug"],
        "repository": project["repository"],
        "workingDirectory": project["workspace"],
        "allowedBranches": [project["branch"]],
        "contextFiles": ["README.md", "AGENTS.md"],
        "verificationCommands": [
            "python3 verify/test_project_workspace.py",
            "python3 verify/test_project_publisher.py",
        ],
        "allowedActions": ["read", "edit", "test", "commit"],
        "forbiddenActions": ["deploy", "push", "delete"],
        "limits": {
            "contextChars": 6000,
            "memoryTopK": 3,
            "memoryHops": 0,
            "memoryTimeoutSeconds": 8,
        },
        "memory": {
            "enabled": False,
            "serverUrl": "https://memory.example.invalid/mcp",
            "credentialRef": "env://MYPEOPLE_MEMORY_TOKEN",
        },
    }


def ensure_project_profile(project: dict, profiles_dir: str) -> str:
    path = os.path.realpath(os.path.join(profiles_dir, project["slug"] + ".json"))
    expected = project_profile(project)
    current = load_json(path, None)
    if current is None:
        atomic_json(path, expected, mode=0o600)
        return "created"
    identity = ("slug", "repository", "workingDirectory", "allowedBranches")
    if any(current.get(key) != expected.get(key) for key in identity):
        raise WorkspaceError("existing ProjectProfile conflicts with workspace manifest")
    return "existing"

