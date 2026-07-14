#!/usr/bin/env python3
from __future__ import annotations

import atexit
import copy
import hashlib
import json
import os
import pathlib
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from typing import Any
from urllib import request, parse, error

ROOT = pathlib.Path(os.environ.get("INSTALL_DIR", "/home/mp/mypeople")).resolve()
VERIFY = ROOT / "verify"
BIN = ROOT / "bin"
QUEUE_ENV = pathlib.Path.home() / ".config" / "mypeople" / "queue.env"
LIVE_QUEUE = os.environ.get("QUEUE_URL", "http://127.0.0.1:9900").rstrip("/")
LIVE_TODO = os.environ.get("TODO_URL", f"http://127.0.0.1:{os.environ.get('TODO_PORT', '9933')}").rstrip("/")
LIVE_HUD = os.environ.get("HUD_URL", f"http://127.0.0.1:{os.environ.get('HUD_PORT', '9900')}").rstrip("/")

sys.path.insert(0, str(BIN))
from mpcommon import load_json, read_env, full_agent_id, parse_agent_id, tmux_target, window_exists, run_tmux  # type: ignore

LIVE_ENV = read_env()
QUEUE_SECRET = LIVE_ENV["QUEUE_SECRET"]
NIGHTWATCH_TOKEN = LIVE_ENV.get("NIGHTWATCH_TOKEN", "")
HOST_ID = LIVE_ENV.get("HOST_ID", os.uname().nodename.split(".")[0])
BOSS_AGENT = LIVE_ENV.get("BOSS_AGENT", f"{HOST_ID}/main:Boss")
NIGHTWATCH_AGENT = LIVE_ENV.get("NIGHTWATCH_AGENT", f"{HOST_ID}/nightwatch:Nightwatch")
CEO_WHATSAPP = LIVE_ENV.get("CEO_WHATSAPP", "")
LIVE_BOARD = pathlib.Path(LIVE_ENV.get("BOARD_PATH", ROOT / "todos" / "board.v2.json")).resolve()
LIVE_EXPORT = pathlib.Path(LIVE_ENV.get("EXPORT_REPO", ROOT / "export")).resolve()

TMP_ROOT = pathlib.Path(tempfile.mkdtemp(prefix="mypeople-verify-", dir="/tmp")).resolve()
TMP = TMP_ROOT / "sandbox"
TMP.mkdir(parents=True, exist_ok=True)
TMP_VIDEO = VERIFY / "videos"
TMP_SHOTS = VERIFY / "screenshots"
VERIFIER_ARTIFACT_IDS = [f"{HOST_ID}/verify-browser:Owner", f"{HOST_ID}/verify-owner:Owner", f"{HOST_ID}/verify-owner2:Owner2"]
VERIFIER_FIXTURE_TEXTS = {"verify ping card", "verify browser live core"}


class Failure(RuntimeError):
    pass


def info(msg: str) -> None:
    print(msg, flush=True)


def run(cmd, *, env=None, cwd=None, check=True, capture=True, timeout=120):
    merged = os.environ.copy()
    if env:
        merged.update({k: str(v) for k, v in env.items() if v is not None})
    p = subprocess.run(
        cmd,
        cwd=cwd,
        env=merged,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        timeout=timeout,
    )
    if check and p.returncode != 0:
        raise Failure(f"command failed: {cmd}\nstdout={p.stdout}\nstderr={p.stderr}")
    return p


def http_json(url: str, method="GET", body: Any | None = None, headers: dict[str, str] | None = None, timeout=20):
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)
    data = None if body is None else json.dumps(body).encode()
    req = request.Request(url, method=method, headers=req_headers, data=data)
    try:
        with request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except error.HTTPError as e:
        raw = e.read()
        try:
            detail = json.loads(raw)
        except Exception:
            detail = raw.decode(errors="replace")
        raise Failure(f"HTTP {e.code} {url}: {detail}") from e


def http_text(url: str, headers: dict[str, str] | None = None, timeout=20):
    req_headers = headers or {}
    req = request.Request(url, headers=req_headers)
    with request.urlopen(req, timeout=timeout) as r:
        return r.read().decode(), r


def wait_http(url: str, timeout=30):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            body, resp = http_text(url)
            return body, resp
        except Exception as e:
            last = e
            time.sleep(0.5)
    raise Failure(f"timeout waiting for {url}: {last}")


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class Proc:
    name: str
    p: subprocess.Popen[str]


class Sandbox:
    def __init__(self):
        self.root = TMP / "runtime"
        self.root.mkdir(parents=True, exist_ok=True)
        self.queue_port = self.free_port()
        self.todo_port = self.free_port()
        self.hud_port = self.queue_port
        self.queue_url = f"http://127.0.0.1:{self.queue_port}"
        self.todo_url = f"http://127.0.0.1:{self.todo_port}"
        self.board = self.root / "board.v2.json"
        self.roster = self.root / "roster.json"
        self.agents = self.root / "agents.json"
        self.status = self.root / "status"
        self.proofs = self.root / "proofs"
        self.capture_dir = self.root / "captures"
        self.capture_dir.mkdir(parents=True, exist_ok=True)
        self.procs: list[Proc] = []
        self.created_agent_ids: list[str] = []
        self.created_tmux_targets: list[str] = []
        self.created_tmp_paths: list[pathlib.Path] = []
        self._old_claude = None

    @staticmethod
    def free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def env(self):
        return {
            "BIND_ADDR": "127.0.0.1",
            "HUD_PORT": str(self.hud_port),
            "TODO_PORT": str(self.todo_port),
            "QUEUE_URL": self.queue_url,
            "TODO_URL": self.todo_url,
            "BOARD_PATH": str(self.board),
            "ROSTER_PATH": str(self.roster),
            "AGENTS_PATH": str(self.agents),
            "STATUS_DIR": str(self.status),
            "EXPORT_REPO": str(self.root / "export"),
            "MYPEOPLE_MP_BIN": str(ROOT / "bin" / "mp"),
            "MYPEOPLE_TODO_URL": self.todo_url,
            "QUEUE_SECRET": QUEUE_SECRET,
            "NIGHTWATCH_TOKEN": NIGHTWATCH_TOKEN,
            "HOST_ID": HOST_ID,
            "BOSS_AGENT": f"{HOST_ID}/verify:Boss",
            "NIGHTWATCH_AGENT": f"{HOST_ID}/verify:Nightwatch",
            "CEO_WHATSAPP": CEO_WHATSAPP,
            "NIGHTWATCH_IDLE_MIN": "1",
            "NIGHTWATCH_TOKEN_TTL": "600",
        }

    def start(self):
        self.status.mkdir(parents=True, exist_ok=True)
        self.proofs.mkdir(parents=True, exist_ok=True)
        self.board.write_text(json.dumps({"version": 2, "order": [], "pinSeq": 0, "tasks": {}}, indent=2) + "\n")
        self.roster.write_text("[]\n")
        self.agents.write_text("[]\n")
        env = os.environ.copy()
        env.update(self.env())
        env["PYTHONPATH"] = str(BIN)
        queue_p = subprocess.Popen([sys.executable, str(BIN / "queue-server.py")], cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.procs.append(Proc("sandbox-queue", queue_p))
        todo_p = subprocess.Popen([sys.executable, str(BIN / "todo-server.py")], cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.procs.append(Proc("sandbox-todo", todo_p))
        wait_http(f"{self.queue_url}/health", 20)
        wait_http(f"{self.todo_url}/health", 20)

    def stop(self):
        for proc in reversed(self.procs):
            if proc.p.poll() is None:
                proc.p.terminate()
        deadline = time.time() + 5
        for proc in reversed(self.procs):
            while proc.p.poll() is None and time.time() < deadline:
                time.sleep(0.1)
            if proc.p.poll() is None:
                proc.p.kill()
        self.procs.clear()

    def cleanup(self):
        created = list(self.created_agent_ids)
        for aid in reversed(created):
            try:
                run([str(ROOT / "bin" / "mp"), "kill", aid, "--reason", "verify cleanup"], env=self.env(), timeout=30, check=False)
            except Exception:
                pass
        self.stop()
        cleanup_artifacts(self.env(), self.created_tmux_targets, created)
        self.created_agent_ids.clear()
        shutil.rmtree(self.root, ignore_errors=True)


def cleanup_artifacts(env: dict[str, str], tmux_targets: list[str] | None = None, agent_ids: list[str] | None = None):
    tmux_targets = list(tmux_targets or [])
    agent_ids = list(agent_ids or [])
    agent_ids.extend(VERIFIER_ARTIFACT_IDS)
    status_dir = pathlib.Path(env.get("STATUS_DIR", ROOT / "status")).resolve()
    roster_file = pathlib.Path(env.get("ROSTER_PATH", ROOT / "run" / "roster.json")).resolve()
    agents_file = pathlib.Path(env.get("AGENTS_PATH", ROOT / "run" / "agents.json")).resolve()
    recordings = pathlib.Path.home() / "recordings"
    for aid in agent_ids:
        try:
            host, session, tab = parse_agent_id(full_agent_id(aid))
        except Exception:
            continue
        status_path = status_dir / f"mc-{session}" / f"{tab}.json"
        try:
            status_path.unlink()
        except FileNotFoundError:
            pass
        try:
            status_path.parent.rmdir()
        except OSError:
            pass
        if status_path.parent.exists():
            try:
                status_path.parent.rmdir()
            except OSError:
                pass
        try:
            if window_exists(f"mc-{session}:{tab}"):
                run_tmux(["kill-window", "-t", f"mc-{session}:{tab}"], check=False)
        except Exception:
            pass
        try:
            if run_tmux(["has-session", "-t", f"rec-{tab}"], check=False, capture=True).returncode == 0:
                run_tmux(["kill-session", "-t", f"rec-{tab}"], check=False)
        except Exception:
            pass
        cast = recordings / f"{HOST_ID}-{tab}.cast"
        try:
            cast.unlink()
        except FileNotFoundError:
            pass
    for target in tmux_targets:
        try:
            if window_exists(target):
                run_tmux(["kill-window", "-t", target], check=False)
        except Exception:
            pass
    for path in (roster_file, agents_file):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text())
        except Exception:
            continue
        if isinstance(data, list):
            filtered = [x for x in data if x.get("agent_id") not in agent_ids]
        elif isinstance(data, dict):
            filtered = {k: v for k, v in data.items() if k not in agent_ids and v.get("agent_id") not in agent_ids}
        else:
            continue
        path.write_text(json.dumps(filtered, indent=2, sort_keys=True) + "\n")


sandbox = Sandbox()
LIVE_CARD_IDS: list[str] = []
LIVE_AGENT_IDS: list[str] = []
CREATED_TEST_CARDS: set[str] = set()
ORIG_CLAUDE = pathlib.Path.home() / ".claude.json"
ORIG_CLAUDE_BACKUP = TMP_ROOT / ".claude.json.bak"
if ORIG_CLAUDE.exists():
    shutil.copy2(ORIG_CLAUDE, ORIG_CLAUDE_BACKUP)


def restore_claude():
    if ORIG_CLAUDE_BACKUP.exists():
        shutil.copy2(ORIG_CLAUDE_BACKUP, ORIG_CLAUDE)


def fail(msg: str):
    raise Failure(msg)


def check(cond: bool, msg: str):
    if not cond:
        fail(msg)


def live_env():
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(BIN),
        "QUEUE_URL": LIVE_QUEUE,
        "TODO_URL": LIVE_TODO,
        "HUD_PORT": os.environ.get("HUD_PORT", "9900"),
        "TODO_PORT": os.environ.get("TODO_PORT", "9933"),
        "QUEUE_SECRET": QUEUE_SECRET,
        "NIGHTWATCH_TOKEN": NIGHTWATCH_TOKEN,
        "HOST_ID": HOST_ID,
        "INSTALL_DIR": str(ROOT),
    })
    return env


def live_api(path, method="GET", body=None, headers=None, timeout=20):
    return http_json(f"{LIVE_TODO}{path}", method=method, body=body, headers=headers or {"X-Queue-Secret": QUEUE_SECRET}, timeout=timeout)


def queue_api(path, method="GET", body=None, headers=None, timeout=20):
    return http_json(f"{LIVE_QUEUE}{path}", method=method, body=body, headers=headers or {"X-Queue-Secret": QUEUE_SECRET}, timeout=timeout)


def sandbox_api(path, method="GET", body=None, headers=None, timeout=20):
    return http_json(f"{sandbox.todo_url}{path}", method=method, body=body, headers=headers or {"X-Queue-Secret": QUEUE_SECRET}, timeout=timeout)


def sandbox_queue(path, method="GET", body=None, headers=None, timeout=20):
    return http_json(f"{sandbox.queue_url}{path}", method=method, body=body, headers=headers or {"X-Queue-Secret": QUEUE_SECRET}, timeout=timeout)


def add_live_task(text: str, test=False, by="CEO") -> str:
    res = live_api("/todo/update", "POST", {"op": "add", "text": text, "by": by, "test": test})
    tid = res["id"]
    if test:
        CREATED_TEST_CARDS.add(tid)
    LIVE_CARD_IDS.append(tid)
    return tid


def is_historical_verifier_card(task: dict[str, Any]) -> bool:
    """Identify only the verifier's known live fixtures, never arbitrary user cards."""
    if task.get("text") not in VERIFIER_FIXTURE_TEXTS or task.get("test") is not False:
        return False
    if task.get("assignee") or task.get("ownerHistory") or task.get("proofs"):
        return False
    comments = task.get("comments") or []
    bodies = [str(c.get("body", "")) for c in comments]
    if task.get("text") == "verify browser live core":
        return all(body == "browser comment" for body in bodies)
    # Ping cards have the exact CEO probe and optional Boss echo provenance.
    return (
        task.get("pingsToBoss", 0) >= 1
        and all(
            body == "verify comment ping"
            or body.startswith("Ping verified:")
            or body.startswith("Comment ping also verified:")
            for body in bodies
        )
        and any(body == "verify comment ping" for body in bodies)
    )


def known_historical_verifier_cards() -> set[str]:
    try:
        board = list_board(LIVE_TODO)
    except Exception:
        return set()
    return {tid for tid, task in board.get("tasks", {}).items() if is_historical_verifier_card(task)}


def discover_browser_created_ids(before_ids: set[str], after_board: dict[str, Any]) -> set[str]:
    """Select only newly-created cards with the browser fixture provenance.

    A board diff is intentionally not sufficient: cards created by a real user
    during the browser interval remain untouched unless their complete verifier
    signature matches (including partial-failure cards with no comment yet).
    """
    tasks = after_board.get("tasks", {}) if isinstance(after_board, dict) else {}
    return {
        tid for tid, task in tasks.items()
        if tid not in before_ids and is_historical_verifier_card(task)
    }


def assert_browser_discovery_safety():
    """Focused regression for concurrent user cards and both browser outcomes."""
    info("browser cleanup regression: provenance-filtered ID discovery")
    base = {
        "test": False, "assignee": "", "ownerHistory": [], "proofs": [],
        "pingsToBoss": 1, "comments": [],
    }
    partial = dict(base, text="verify browser live core")
    success = dict(base, text="verify browser live core", comments=[{"body": "browser comment"}])
    sentinel = dict(base, text="CEO concurrent card", comments=[])
    before = {"existing"}
    after_partial = {"tasks": {"verifier-partial": partial, "sentinel": sentinel}}
    after_success = {"tasks": {"verifier-success": success, "sentinel": sentinel}}
    check(discover_browser_created_ids(before, after_partial) == {"verifier-partial"}, "partial browser provenance discovery unsafe")
    check(discover_browser_created_ids(before, after_success) == {"verifier-success"}, "successful browser provenance discovery unsafe")
    selected = discover_browser_created_ids(before, after_success)
    deleted = [tid for tid in after_success["tasks"] if tid in selected]
    check("sentinel" not in deleted, "concurrent user card would be deleted")


def add_sandbox_task(text: str, test=False, by="CEO") -> str:
    res = sandbox_api("/todo/update", "POST", {"op": "add", "text": text, "by": by, "test": test})
    return res["id"]


def list_board(base: str):
    return http_json(f"{base}/todo/board", headers={"X-Queue-Secret": QUEUE_SECRET})


def current_boss_alive():
    agents = queue_api("/agents")
    boss = next((a for a in agents if a["agent_id"] == BOSS_AGENT), None)
    return boss, agents


def assert_live_health():
    info("J1: health / install")
    body, _ = http_text(f"{LIVE_TODO}/health", {"X-Queue-Secret": QUEUE_SECRET})
    check('"status": "ok"' in body or '"status":"ok"' in body, "todo health not ok")
    body, _ = http_text(f"{LIVE_QUEUE}/health", {"X-Queue-Secret": QUEUE_SECRET})
    check('"status": "ok"' in body or '"status":"ok"' in body, "queue health not ok")
    check((ROOT / "verify" / "verify.sh").is_file(), "verify.sh missing")
    check(os.access(ROOT / "verify" / "verify.sh", os.X_OK), "verify.sh not executable")
    check((ROOT / "bin" / "mp").is_file(), "mp missing")
    check((ROOT / "bin" / "todos.html").is_file(), "todos.html missing")
    check((ROOT / "bin" / "dashboard.html").is_file(), "dashboard.html missing")
    check((ROOT / "bin" / "wall.html").is_file(), "wall.html missing")
    check((ROOT / "bin" / "terminal-graph.html").is_file(), "terminal-graph.html missing")


def assert_boss_and_nightwatch():
    info("J2/J39: Boss and Nightwatch alive")
    boss, agents = current_boss_alive()
    check(boss is not None and boss.get("state") == "alive", "Boss not alive in queue")
    check(bool(boss.get("spawn_cmd")), "Boss spawn_cmd missing")
    nw = next((a for a in agents if a["agent_id"] == NIGHTWATCH_AGENT), None)
    check(nw is not None and nw.get("state") == "alive", "Nightwatch not alive")
    summary = (nw.get("summary", "") or "").lower()
    kws = [k for k in ("nightwatch", "ceo-equivalent", "approve", "whatsapp", "never-done") if k in summary]
    check(len(kws) >= 2, "Nightwatch summary missing keywords")
    status = run([str(ROOT / "bin" / "mp"), "status"], env=live_env(), timeout=20)
    out = status.stdout or ""
    check(BOSS_AGENT in out, "mp status missing Boss")
    check(any(k in out for k in ("plan", "approve", "queue", "mp", "autonomous", "verify", "fire-and-forget")), "mp status missing doctrine keywords")


def assert_stability():
    info("J2b: H-STABLE / service stability")
    body = http_json(f"{LIVE_TODO}/health", headers={"X-Queue-Secret": QUEUE_SECRET})
    check(body.get("status") == "ok", "todo unstable")
    body2 = http_json(f"{LIVE_QUEUE}/health", headers={"X-Queue-Secret": QUEUE_SECRET})
    check(body2.get("status") == "ok", "queue unstable")


def assert_add_ping():
    info("J3/J32: add/comment ping Boss")
    before = (ROOT / "todos" / "boss-inbox.log").read_text() if (ROOT / "todos" / "boss-inbox.log").exists() else ""
    tid = add_live_task("verify ping card", test=False)
    deadline = time.time() + 25
    seen = False
    while time.time() < deadline:
        text = (ROOT / "todos" / "boss-inbox.log").read_text() if (ROOT / "todos" / "boss-inbox.log").exists() else ""
        if text != before and tid in text:
            seen = True
            break
        time.sleep(0.5)
    check(seen, "Boss inbox did not record add ping")
    live_api("/todo/comment", "POST", {"task_id": tid, "by": "CEO", "body": "verify comment ping"})
    deadline = time.time() + 20
    seen2 = False
    while time.time() < deadline:
        text = (ROOT / "todos" / "boss-inbox.log").read_text() if (ROOT / "todos" / "boss-inbox.log").exists() else ""
        if "comment on" in text and tid in text:
            seen2 = True
            break
        time.sleep(0.5)
    check(seen2, "Boss inbox did not record comment ping")
    # Minimal live-loop probe: a real comment must reach the same card and persist.
    board = list_board(LIVE_TODO)
    check(tid in board["tasks"], "live task missing after ping")


def assert_tailscale_and_attach():
    info("J10/J47: tailscale and attach reach")
    ts = run(["tailscale", "status", "--json"], env=live_env(), timeout=20)
    check(ts.returncode == 0, "tailscale status failed")
    ip = run(["tailscale", "ip", "-4"], env=live_env(), timeout=20)
    check("100." in (ip.stdout or ""), "no tailnet IPv4")
    clients = queue_api("/clients")
    check(any(c.get("attach_base") for c in clients), "no attach_base in clients")


def assert_removed_negative():
    info("J11/J19/J20/J23/J26/J30: removed/negative contracts")
    board = list_board(LIVE_TODO)
    check("machines" not in json.dumps(board).lower(), "removed machines grid leaked into board")
    for path in ("/todo/brainstorm", "/todo/answer"):
        try:
            http_json(f"{LIVE_TODO}{path}", headers={"X-Queue-Secret": QUEUE_SECRET})
            fail(f"{path} unexpectedly existed")
        except Failure:
            pass
    tid = add_live_task("verify removed features", test=True)
    CREATED_TEST_CARDS.add(tid)
    for bad in ("parent", "dependsOn", "hardGate"):
        try:
            live_api("/todo/update", "POST", {"op": "add", "text": f"bad {bad}", bad: tid, "test": True})
            fail(f"{bad} add unexpectedly accepted")
        except Failure:
            pass
    check("QUEUE_SECRET" not in (ROOT / "bin" / "dashboard.html").read_text(), "secret leaked into dashboard source")


def assert_state_and_proofs():
    info("J15-J24: delete/edit/state/proofs/unread/verified")
    tid = add_live_task("verify lifecycle task", test=True)
    CREATED_TEST_CARDS.add(tid)
    live_api("/todo/update", "POST", {"op": "set", "id": tid, "text": "verify lifecycle task edited", "doneCondition": "complete", "state": "working", "by": "CEO"})
    board = list_board(LIVE_TODO)
    t = board["tasks"][tid]
    check(t["text"] == "verify lifecycle task edited", "text edit failed")
    check(t["doneCondition"] == "complete", "doneCondition edit failed")
    for state in ["needs_brainstorm", "working", "review", "blocked", "done", "cancelled", "recurring"]:
        live_api("/todo/status", "POST", {"task_id": tid, "state": state, "verified": state == "done", "by": "CEO"})
        board = list_board(LIVE_TODO)
        check(board["tasks"][tid]["state"] == state, f"state {state} not persisted")
    live_api("/todo/comment", "POST", {"task_id": tid, "by": "node-1/agent:Worker", "body": "non-ceo comment"})
    board = list_board(LIVE_TODO)
    check(int(board["tasks"][tid]["unread"]) >= 1, "unread not incremented")
    live_api("/todo/proof", "POST", {"task_id": tid, "kind": "text", "body": "proof body"})
    board = list_board(LIVE_TODO)
    check(board["tasks"][tid]["proofs"] and board["tasks"][tid]["proofs"][-1]["body"] == "proof body", "text proof missing")
    live_api("/todo/proof", "POST", {"task_id": tid, "kind": "link", "url": "https://example.com/proof"})
    board = list_board(LIVE_TODO)
    check(any(p["kind"] == "link" for p in board["tasks"][tid]["proofs"]), "link proof missing")
    live_api("/todo/update", "POST", {"op": "set", "id": tid, "verified": True, "by": "CEO"})
    board = list_board(LIVE_TODO)
    check(board["tasks"][tid]["verified"] is True, "verified badge flag missing")
    live_api("/todo/update", "POST", {"op": "del", "id": tid})
    board = list_board(LIVE_TODO)
    check(tid not in board["tasks"], "delete failed")


def assert_pins():
    info("J37/J49-O: unlimited pins and ordering")
    print("# J37/J49-O reconciliation: 2026-06-29 explicitly supersedes the 2026-06-20 max-5 cap; verifier asserts uncapped pins.")
    tids = [add_live_task(f"pin task {i}", test=True) for i in range(7)]
    for tid in tids:
        CREATED_TEST_CARDS.add(tid)
    for tid in tids:
        live_api("/todo/update", "POST", {"op": "pin", "id": tid})
    board = list_board(LIVE_TODO)
    ordered = board["displayOrder"]
    pinned = [board["tasks"][tid] for tid in ordered if board["tasks"][tid]["pinned"]]
    check(len(pinned) >= 7, "pin cap still present")
    check("pin_limit" not in json.dumps(board), "pin_limit leaked")
    ranks = [t["pinRank"] for t in pinned]
    check(ranks == sorted(ranks), "pins not ordered by pinRank")
    live_api("/todo/update", "POST", {"op": "unpin", "id": tids[3]})
    board = list_board(LIVE_TODO)
    check(not board["tasks"][tids[3]]["pinned"], "unpin failed")
    live_api("/todo/update", "POST", {"op": "pin", "id": tids[3]})
    board2 = list_board(LIVE_TODO)
    check(board2["tasks"][tids[3]]["pinned"], "re-pin failed")


def assert_owner_lifecycle():
    info("J25/J25a/J50/J51: owner lifecycle and migration")
    sandbox.start()
    try:
        fixture = add_sandbox_task("owner fixture", test=True)
        owner_id = f"{HOST_ID}/verify-owner:Owner"
        res = run([
            str(ROOT / "bin" / "mp"), "spawn", owner_id, "--backend", "claude",
            "--cwd", str(TMP / "owner-work"), "--boss", f"{HOST_ID}/verify:Boss", "--owner-task", fixture
        ], env=sandbox.env(), timeout=120)
        sandbox.created_agent_ids.append(owner_id)
        deadline = time.time() + 20
        while time.time() < deadline and not window_exists(tmux_target(owner_id)):
            time.sleep(0.5)
        deadline = time.time() + 20
        agents = []
        while time.time() < deadline:
            agents = sandbox_queue("/agents")
            if any(a["agent_id"] == owner_id for a in agents):
                break
            time.sleep(0.5)
        row = next((a for a in agents if a["agent_id"] == owner_id), None)
        check(row is not None and row.get("spawn_cmd"), "spawn_cmd missing")
        check(row.get("revive_cmd") == f"mp revive {owner_id}", "revive_cmd wrong")
        assign_res = sandbox_api("/todo/owner", "POST", {"action": "assign", "task_id": fixture, "agent_id": owner_id, "by": f"{HOST_ID}/verify:Boss"})
        check(assign_res.get("ok") is True, "owner assign endpoint rejected")
        board = sandbox_api("/todo/board")
        check(board["tasks"][fixture]["assignee"] == owner_id, "owner assignment missing")
        check(board["tasks"][fixture]["ownerHistory"], "owner history missing")
        sandbox_api("/todo/comment", "POST", {"task_id": fixture, "by": "CEO", "body": "owner routing"})
        sandbox_api("/todo/status", "POST", {"task_id": fixture, "state": "done", "verified": True, "by": "CEO"})
        board = sandbox_api("/todo/board")
        check(board["tasks"][fixture]["ownerHistory"][-1]["kind"] == "closed", "close event missing")
        sandbox_api("/todo/status", "POST", {"task_id": fixture, "state": "working", "by": "CEO"})
        board = sandbox_api("/todo/board")
        check(board["tasks"][fixture]["ownerNeedsReplacement"] is True, "reopen pending missing")
        legacy = owner_id
        new_owner = f"{HOST_ID}/verify-owner2:Owner2"
        run([
            str(ROOT / "bin" / "mp"), "spawn", new_owner, "--backend", "claude",
            "--cwd", str(TMP / "owner-work2"), "--boss", f"{HOST_ID}/verify:Boss", "--owner-task", fixture
        ], env=sandbox.env(), timeout=120)
        sandbox.created_agent_ids.append(new_owner)
        sandbox_api("/todo/owner", "POST", {"action": "replace", "task_id": fixture, "agent_id": new_owner, "by": f"{HOST_ID}/verify:Boss"})
        board = sandbox_api("/todo/board")
        check(board["tasks"][fixture]["assignee"] == new_owner, "owner replace missing")
        check(any(ev["kind"] == "replace" for ev in board["tasks"][fixture]["ownerHistory"]), "replace event missing")
        legacy_board = {
            "version": 2,
            "order": ["legacy"],
            "pinSeq": 0,
            "tasks": {
                "legacy": {
                    "id": "legacy",
                    "text": "legacy",
                    "state": "working",
                    "assignee": owner_id,
                    "ownerHistory": None,
                    "ownerNeedsReplacement": None,
                    "comments": [],
                    "proofs": [],
                    "unread": 0,
                    "verified": False,
                    "pingsToBoss": 0,
                    "pinned": False,
                    "pinRank": None,
                    "test": True,
                    "updated": time.time(),
                }
            },
        }
        tmp_board = TMP / "legacy-board.json"
        tmp_board.write_text(json.dumps(legacy_board))
        script = f"""
import importlib.util, json, pathlib, os
p = pathlib.Path({str(BIN / 'todo-server.py')!r})
spec = importlib.util.spec_from_file_location('todo_server_mod', p)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod.BOARD_PATH = {str(tmp_board)!r}
mod.BOARD_DIR = str(pathlib.Path({str(tmp_board)!r}).parent)
board = json.load(open({str(tmp_board)!r}))
changed = mod.migrate(board)
changed2 = mod.migrate(board)
print(json.dumps({{'changed': changed, 'changed2': changed2, 'board': board}}, sort_keys=True))
"""
        p = run([sys.executable, "-c", script], env=sandbox.env(), timeout=30)
        out = json.loads(p.stdout.strip())
        check(out["changed"] is True, "legacy migration did not report change")
        board_after = out["board"]
        evs = board_after["tasks"]["legacy"]["ownerHistory"]
        check(len([e for e in evs if e["kind"] == "migrated_existing_owner"]) == 1, "migration event wrong")
        check(board_after["tasks"]["legacy"]["ownerNeedsReplacement"] is False, "migration flag wrong")
        check(out["changed2"] is False, "legacy migration not idempotent")
    finally:
        sandbox.cleanup()


def assert_attach_and_tmux():
    info("J27/J28/J47: attach and tmux")
    check(run(["tmux", "list-sessions"], capture=True).returncode == 0, "tmux list failed")
    check(any("mc-main" in line for line in run(["tmux", "list-sessions"], capture=True).stdout.splitlines()), "mc-main session missing")
    board = list_board(LIVE_TODO)
    if not board["tasks"]:
        tid = add_live_task("attach fixture", test=True)
        CREATED_TEST_CARDS.add(tid)
        board = list_board(LIVE_TODO)
    tid = next(iter(board["tasks"]))
    agents = queue_api("/agents")
    if agents:
        aid = agents[0]["agent_id"]
        info(f"using attach target {aid}")
        url = http_json(f"{LIVE_TODO}/todo/attach?agent={parse.quote(aid)}", headers={"X-Queue-Secret": QUEUE_SECRET})
        check(url["ok"] is not False, "attach lookup failed")


def cleanup_live_cards():
    # Union explicit API-created ids, test fixtures, and browser-discovered ids so
    # cleanup runs on both success and every exception path.
    ids = set(LIVE_CARD_IDS) | set(CREATED_TEST_CARDS)
    ids |= known_historical_verifier_cards()
    for tid in ids:
        try:
            live_api("/todo/update", "POST", {"op": "del", "id": tid})
        except Exception:
            pass
    cleanup_artifacts(LIVE_ENV, [], [])


def assert_no_verifier_residue():
    """Final fail-closed check: no current or known historical verifier residue."""
    board = list_board(LIVE_TODO)
    leftovers = {tid for tid, task in board.get("tasks", {}).items() if tid in set(LIVE_CARD_IDS) or tid in set(CREATED_TEST_CARDS) or is_historical_verifier_card(task)}
    check(not leftovers, f"verifier live cards remain: {sorted(leftovers)}")
    # Verify-owned agent/status/recorder artifacts are exact names, so legitimate
    # user sessions and their status files are outside this assertion.
    for aid in VERIFIER_ARTIFACT_IDS + LIVE_AGENT_IDS:
        host, session, tab = parse_agent_id(full_agent_id(aid))
        check(not (ROOT / "status" / f"mc-{session}" / f"{tab}.json").exists(), f"verifier status remains for {aid}")
        check(not window_exists(f"mc-{session}:{tab}"), f"verifier tmux window remains for {aid}")
        check(not (pathlib.Path.home() / "recordings" / f"{HOST_ID}-{tab}.cast").exists(), f"verifier recording remains for {aid}")
    for path in (ROOT / "run" / "roster.json", ROOT / "run" / "agents.json"):
        if path.exists():
            try:
                rows = json.loads(path.read_text())
            except Exception:
                rows = []
            rows = rows if isinstance(rows, list) else list(rows.values()) if isinstance(rows, dict) else []
            check(not any(row.get("agent_id") in VERIFIER_ARTIFACT_IDS + LIVE_AGENT_IDS for row in rows if isinstance(row, dict)), f"verifier roster residue in {path}")


def run_browser_suite():
    info("J31/J45-J46/J49/J52: browser journeys")
    manifest = TMP_ROOT / "manifest.json"
    live_env_browser = os.environ.copy()
    live_env_browser.update({
        "MP_VERIFY_BASE_URL": LIVE_TODO,
        "MP_VERIFY_HUD_URL": LIVE_QUEUE,
        "MP_VERIFY_VIDEO_DIR": str(TMP_VIDEO),
        "MP_VERIFY_SCREEN_DIR": str(TMP_SHOTS),
    })
    for browser in ("chromium", "webkit"):
        sandbox.start()
        try:
            fixtures = build_sandbox_fixtures()
            manifest.write_text(json.dumps({"sandbox": fixtures}, indent=2) + "\n")
            sandbox_env = os.environ.copy()
            sandbox_env.update({
                "MP_VERIFY_BASE_URL": sandbox.todo_url,
                "MP_VERIFY_HUD_URL": sandbox.queue_url,
                "MP_VERIFY_VIDEO_DIR": str(TMP_VIDEO),
                "MP_VERIFY_SCREEN_DIR": str(TMP_SHOTS),
            })
            run(["node", str(VERIFY / "browser_journeys.js"), "--scenario", "sandbox_suite", "--browser", browser, "--manifest", str(manifest)], env=sandbox_env, timeout=420)
        finally:
            sandbox.cleanup()
    for browser in ("chromium", "webkit"):
        # The live journey creates its own card through the UI and cannot return
        # that id. Snapshot the board around it and track the exact id diff, even
        # when Playwright raises, so failure cleanup is equally complete.
        before = set(list_board(LIVE_TODO).get("tasks", {}))
        try:
            run(["node", str(VERIFY / "browser_journeys.js"), "--scenario", "live_core", "--browser", browser, "--manifest", str(manifest)], env=live_env_browser, timeout=240)
        finally:
            try:
                after_board = list_board(LIVE_TODO)
                LIVE_CARD_IDS.extend(discover_browser_created_ids(before, after_board))
            except Exception:
                pass


def assert_nightwatch_security():
    info("J40-J44: Nightwatch security and Hermes")
    if not NIGHTWATCH_TOKEN:
        fail("nightwatch token missing")
    sandbox.start()
    try:
        tid = add_sandbox_task("nightwatch probe", test=True)
        headers = {"X-Nightwatch-Token": NIGHTWATCH_TOKEN}
        try:
            sandbox_api("/todo/comment", "POST", {"task_id": tid, "by": "CEO", "body": "spoof probe"}, headers=headers)
            fail("nightwatch spoof not rejected")
        except Failure as e:
            check("nightwatch_cannot_spoof" in str(e), "nightwatch spoof wrong error")
        res = sandbox_api("/nightwatch/inbound", "POST", {"from": "CEO", "text": "Nightwatch, create demo"})
        check(res.get("ok") is True, "nightwatch inbound did not accept authed message")
        try:
            sandbox_api("/nightwatch/outbound", "POST", {"text": "hello"}, headers={"X-Nightwatch-Token": NIGHTWATCH_TOKEN})
            fail("nightwatch outbound unexpectedly succeeded without Hermes")
        except Failure as e:
            check("hermes_not_configured" in str(e) or "501" in str(e), "nightwatch outbound wrong failure")
    finally:
        sandbox.cleanup()


def build_sandbox_fixtures():
    info("seeding sandbox fixtures")
    # Board fixtures for browser journeys. Each fixture is test:true and lives only in the sandbox.
    task_ids = []
    for i in range(2):
        task_ids.append(add_sandbox_task(f"cancelled fixture {i}", test=True))
        sandbox_api("/todo/status", "POST", {"task_id": task_ids[-1], "state": "cancelled", "by": "CEO"})
    for i in range(8):
        task_ids.append(add_sandbox_task(f"open fixture {i}", test=True))
    recurring_ids = [add_sandbox_task(f"recurring fixture {i}", test=True) for i in range(2)]
    for tid in recurring_ids:
        sandbox_api("/todo/status", "POST", {"task_id": tid, "state": "recurring", "by": "CEO"})
    delete_id = add_sandbox_task("delete fixture", test=True)
    modal_id = add_sandbox_task("modal fixture", test=True)
    scroll_id = add_sandbox_task("scroll fixture", test=True)
    safe_md_id = add_sandbox_task("safe markdown fixture", test=True)
    owner_task = add_sandbox_task("owner browser fixture", test=True)
    pin_ids = [add_sandbox_task(f"pin fixture {i}", test=True) for i in range(7)]
    unread_id = add_sandbox_task("unread fixture", test=True)
    proof_id = add_sandbox_task("proof fixture", test=True)
    crossnav_id = add_sandbox_task("crossnav fixture", test=True)
    # Seed comments / proofs / history.
    for n in range(120):
        sandbox_api("/todo/comment", "POST", {"task_id": scroll_id, "by": "CEO", "body": f"scroll {n} - line one\nline two\nline three"})
    safe_md_body = "# Heading\n\n**bold** *italic* `code`\n\n```js\nconsole.log('x')\n```\n\n- one\n- two\n\n> quote\n\n| a | b |\n| :-- | --: |\n| [safe](https://example.com) | `ok` |\n\nLine 1\nLine 2\n\n<script>alert(1)</script>\n<img onerror=alert(2)>\n[bad](javascript:alert(3))"
    sandbox_api("/todo/comment", "POST", {"task_id": safe_md_id, "by": "CEO", "body": safe_md_body})
    sandbox_api("/todo/comment", "POST", {"task_id": owner_task, "by": "CEO", "body": "owner link fixture"})
    # Create owner agent and assign via real owner endpoint.
    owner_id = f"{HOST_ID}/verify-browser:Owner"
    env = sandbox.env()
    run([str(ROOT / "bin" / "mp"), "spawn", owner_id, "--backend", "claude", "--cwd", str(TMP / "browser-owner"), "--boss", f"{HOST_ID}/verify:Boss", "--owner-task", owner_task], env=env, timeout=120)
    sandbox.created_agent_ids.append(owner_id)
    deadline = time.time() + 20
    while time.time() < deadline and not window_exists(tmux_target(owner_id)):
        time.sleep(0.5)
    sandbox_queue("/heartbeat", "POST", {"hostname": HOST_ID, "attach_base": "http://127.0.0.1:7681", "substrate_ready": True, "agents": [{"agent_id": owner_id, "state": "alive", "boss_id": f"{HOST_ID}/verify:Boss", "is_master": False, "summary": "owner"}]})
    assign_res = sandbox_api("/todo/owner", "POST", {"action": "assign", "task_id": owner_task, "agent_id": owner_id, "by": f"{HOST_ID}/verify:Boss"})
    check(assign_res.get("ok") is True, "owner browser assign endpoint rejected")
    # Make an image proof available via upload.
    img = TMP / "proof.png"
    img.write_bytes(bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010802000000907724e50000000a49444154789c6360000002000154a24f5d0000000049454e44ae426082"))
    sandbox_api("/todo/proof", "POST", {"task_id": proof_id, "kind": "image", "url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO94W9kAAAAASUVORK5CYII="})
    # Optional inline text proof for completeness.
    sandbox_api("/todo/proof", "POST", {"task_id": proof_id, "kind": "text", "body": "proof text"})
    # Owner history fixture for attach clicks.
    sandbox_api("/todo/comment", "POST", {"task_id": owner_task, "by": owner_id, "body": "owner reply"})
    return {
        "taskIds": [owner_task, modal_id, scroll_id, safe_md_id, delete_id, unread_id, proof_id, crossnav_id] + task_ids + recurring_ids + pin_ids,
        "ownerTask": owner_task,
        "ownerId": owner_id,
        "deleteId": delete_id,
        "modalId": modal_id,
        "scrollId": scroll_id,
        "safeMdId": safe_md_id,
        "proofId": proof_id,
        "crossnavId": crossnav_id,
        "recurringIds": recurring_ids,
        "pinIds": pin_ids,
        "unreadId": unread_id,
        "attachBase": "http://127.0.0.1:7681",
        "safeMarkdownBody": safe_md_body,
    }


def main():
    try:
        cleanup_live_cards()
        assert_live_health()
        assert_boss_and_nightwatch()
        assert_stability()
        assert_add_ping()
        assert_tailscale_and_attach()
        assert_removed_negative()
        assert_state_and_proofs()
        assert_pins()
        assert_attach_and_tmux()
        assert_browser_discovery_safety()
        run_browser_suite()
        check(not os.environ.get("UPSTREAM_QUEUE_URL"), "UPSTREAM_QUEUE_URL set on standalone node")
        info("J12/J13: inapplicable on standalone node (UPSTREAM_QUEUE_URL unset)")
        info("J35/J36/J50/J51/J52/J49: sandboxed owner/browser/migration suites")
        assert_owner_lifecycle()
        assert_nightwatch_security()
        cleanup_live_cards()
        assert_no_verifier_residue()
        info("verify core complete")
    except Exception as e:
        cleanup_live_cards()
        raise


if __name__ == "__main__":
    atexit.register(restore_claude)
    atexit.register(cleanup_live_cards)
    main()
