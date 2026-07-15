#!/usr/bin/env python3
"""Keep configured Git workspaces and their shell-only tmux sessions available."""
from __future__ import annotations

import os
import signal
import time

from mpcommon import ROOT, atomic_json
from project_workspace import (
    WorkspaceError,
    ensure_project_profile,
    ensure_tmux_session,
    ensure_workspace,
    load_projects,
)


running = True


def stop(_signum, _frame):
    global running
    running = False


def main() -> int:
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    workspace_root = os.path.realpath(
        os.environ.get("PROJECT_WORKSPACES_ROOT", "/home/mp/workspaces")
    )
    manifest = os.path.realpath(
        os.environ.get(
            "PROJECT_WORKSPACES_MANIFEST",
            os.path.join(ROOT, "docker", "project-workspaces.json"),
        )
    )
    profiles_dir = os.path.realpath(
        os.environ.get(
            "PROJECT_PROFILES_DIR", os.path.join(ROOT, "run", "project-profiles")
        )
    )
    status_dir = os.path.realpath(os.path.join(ROOT, "run", "workspaces"))
    while running:
        try:
            projects = load_projects(manifest, workspace_root)
            for project in projects:
                workspace_state = ensure_workspace(project)
                profile_state = ensure_project_profile(project, profiles_dir)
                session_created = ensure_tmux_session(project)
                atomic_json(
                    os.path.join(status_dir, project["slug"] + ".json"),
                    {
                        "slug": project["slug"],
                        "workspace": project["workspace"],
                        "tmuxSession": project["tmuxSession"],
                        "workspaceState": workspace_state,
                        "profileState": profile_state,
                        "sessionState": "created" if session_created else "alive",
                        "status": "ready",
                        "timestamp": time.time(),
                    },
                )
        except (WorkspaceError, OSError) as error:
            atomic_json(
                os.path.join(status_dir, "supervisor.json"),
                {
                    "status": "blocked",
                    "error": str(error)[:500],
                    "timestamp": time.time(),
                },
            )
        deadline = time.monotonic() + 5
        while running and time.monotonic() < deadline:
            time.sleep(0.25)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

