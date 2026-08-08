#!/usr/bin/env python3
"""Deterministic, opt-in terminal recording policy."""
from __future__ import annotations

from pathlib import Path
import shlex


def recording_mode(agent, profile, environment) -> str:
    value = agent.get("recording") or profile.get("recording") or environment.get("MYPEOPLE_RECORDING_DEFAULT", "off")
    return value if value in {"on", "off"} else "off"


def reconcile_recorder(run_tmux, session: str, tab: str, mode: str, cast_path: str) -> str:
    name = "rec-" + tab
    if mode != "on":
        run_tmux(["kill-session", "-t", name], check=False)
        return "off"
    if run_tmux(["has-session", "-t", name], check=False).returncode == 0:
        return "recording"
    cast = Path(cast_path).expanduser()
    cast.parent.mkdir(parents=True, exist_ok=True)
    command = f"asciinema rec --quiet --append -c {shlex.quote(f'TMUX= tmux attach -rt mc-{session}:{tab}')} {shlex.quote(str(cast))}"
    result = run_tmux(["new-session", "-d", "-s", name, command], check=False)
    return "recording" if result.returncode == 0 else "unknown"
