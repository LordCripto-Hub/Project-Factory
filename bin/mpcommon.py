#!/usr/bin/env python3
"""Shared, standard-library-only helpers for the MyPeople runtime."""
from __future__ import annotations
import contextlib, fcntl, json, os, pathlib, shlex, subprocess, tempfile, time
import urllib.error, urllib.parse, urllib.request

CONFIG = os.environ.get("MYPEOPLE_CONFIG_PATH", os.path.expanduser("~/.config/mypeople/queue.env"))
DEFAULT_ENG_MODEL = "claude-opus-4-8"

def read_env(path: str = CONFIG) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        lines = pathlib.Path(path).read_text().splitlines()
    except FileNotFoundError:
        lines = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        out[k.strip()] = v
    # Process-local overrides enable isolated verification without mutating queue.env.
    for k, v in os.environ.items():
        if k in out or k in {"BOARD_PATH","ROSTER_PATH","AGENTS_PATH","STATUS_DIR","EXPORT_REPO","CEO_WHATSAPP","HERMES_SEND_URL","NIGHTWATCH_IDLE_MIN","NIGHTWATCH_TOKEN_TTL","BOSS_AGENT","NIGHTWATCH_AGENT","HUD_PORT","TODO_PORT","QUEUE_URL","BIND_ADDR","INSTALL_DIR","HOST_ID","QUEUE_SECRET","NIGHTWATCH_TOKEN","PROJECT_PROFILES_DIR","TASKSPECS_DIR","MEMORY_GATEWAY_PATH","MYPEOPLE_MEMORY_ALLOW_HTTP"}:
            out[k] = v
    return out

ENV = read_env()
ROOT = os.path.realpath(ENV.get("INSTALL_DIR", os.path.expanduser("~/mypeople")))

def atomic_json(path: str, obj, mode: int = 0o600) -> None:
    path = os.path.realpath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.{time.time_ns()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
        f.flush(); os.fsync(f.fileno())
    os.chmod(tmp, mode)
    os.replace(tmp, path)

@contextlib.contextmanager
def json_lock(path: str):
    lock = path + ".lock"
    os.makedirs(os.path.dirname(lock), exist_ok=True)
    with open(lock, "a+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try: yield
        finally: fcntl.flock(f, fcntl.LOCK_UN)

def load_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError): return default

def parse_agent_id(agent_id: str):
    if "/" not in agent_id or ":" not in agent_id.split("/", 1)[1]:
        raise ValueError("agent_id must be <host>/<session>:<tab>")
    host, rest = agent_id.split("/", 1)
    session, tab = rest.split(":", 1)
    if not all(x.strip() for x in (host, session, tab)) or any(c in session + tab for c in " \t\n/;\""):
        raise ValueError("invalid agent_id")
    return host, session, tab

def full_agent_id(value: str) -> str:
    if not value or not value.strip(): raise ValueError("empty agent id")
    value = value.strip()
    return value if "/" in value else f"{ENV.get('HOST_ID', os.uname().nodename.split('.')[0])}/{value}"

def tmux_target(agent_id: str) -> str:
    _, session, tab = parse_agent_id(full_agent_id(agent_id)); return f"mc-{session}:{tab}"

def http_json(path: str, method="GET", body=None, base=None, token=None, timeout=15):
    base = (base or ENV.get("QUEUE_URL", "http://127.0.0.1:9900")).rstrip("/")
    headers = {"X-Queue-Secret": token or ENV.get("QUEUE_SECRET", ""), "Content-Type": "application/json"}
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    req = urllib.request.Request(base + path, method=method, headers=headers, data=data)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(); return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read()
        try: detail = json.loads(raw)
        except Exception: detail = raw.decode(errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {detail}") from e

def run_tmux(args, *, check=True, capture=False, env=None):
    e = os.environ.copy(); e.pop("TMUX", None)
    if env: e.update(env)
    return subprocess.run(["tmux", *args], check=check, text=True,
                          stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.PIPE if capture else None, env=e)

def window_exists(target: str) -> bool:
    return run_tmux(["has-session", "-t", target], check=False, capture=True).returncode == 0

def tmux_send_message(target: str, message, runner=run_tmux, delay=.4, submit_delay=.08) -> bool:
    """Paste exactly one nonempty payload and submit once; retry only a stuck multiline paste."""
    if message is None or not str(message).strip():
        return False
    msg = str(message)
    runner(["set-buffer", "--", msg])
    runner(["paste-buffer", "-d", "-t", target])
    time.sleep(submit_delay)
    runner(["send-keys", "-t", target, "Enter"])
    if "\n" in msg:
        time.sleep(delay)
        cap = runner(["capture-pane", "-p", "-t", target], capture=True)
        if "[Pasted text" in (cap.stdout or ""):
            runner(["send-keys", "-t", target, "Enter"])
    return True

def roster_path(): return os.path.realpath(ENV.get("ROSTER_PATH", os.path.join(ROOT, "run", "roster.json")))
def agents_path(): return os.path.realpath(ENV.get("AGENTS_PATH", os.path.join(ROOT, "run", "agents.json")))

def load_roster():
    data = load_json(roster_path(), [])
    return data if isinstance(data, list) else list(data.values()) if isinstance(data, dict) else []

def save_roster(rows): atomic_json(roster_path(), rows)

def update_roster(record: dict):
    with json_lock(roster_path()):
        rows = [x for x in load_roster() if x.get("agent_id") != record["agent_id"]]
        rows.append(record); save_roster(rows)

def remove_roster(agent_id: str):
    with json_lock(roster_path()):
        save_roster([x for x in load_roster() if x.get("agent_id") != agent_id])

def trust_claude(cwd: str):
    path = os.path.expanduser("~/.claude.json")
    data = load_json(path, {})
    data["hasCompletedOnboarding"] = True
    data.setdefault("lastOnboardingVersion", "2.0.0")
    data.setdefault("theme", "dark")
    data.setdefault("projects", {}).setdefault(os.path.realpath(cwd), {})["hasTrustDialogAccepted"] = True
    atomic_json(path, data)

def status_path(agent_id: str):
    _, s, t = parse_agent_id(agent_id); return os.path.join(os.path.realpath(ENV.get("STATUS_DIR", os.path.join(ROOT, "status"))), f"mc-{s}", t + ".json")

ACTIVITY_STATES={"starting","working","idle","blocked"}

def write_status(agent_id, status, summary="", **extra):
    if status not in ACTIVITY_STATES:raise ValueError(f"invalid activity status: {status}")
    old = load_json(status_path(agent_id), {})
    old.update(status=status, summary=summary or old.get("summary", ""), timestamp=time.time(),activity_updated_at=time.time(),
               session_id=old.get("session_id", ""), state="alive", **extra)
    atomic_json(status_path(agent_id), old)

def shell_export(values: dict[str, str | None]) -> str:
    bits=[]
    for k,v in values.items():
        bits.append(f"unset {k}" if v is None else f"export {k}={shlex.quote(str(v))}")
    return "; ".join(bits)
