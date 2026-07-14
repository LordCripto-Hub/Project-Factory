
# Codex Boss Backend Switch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run `node-1/main:Boss` on authenticated Codex with `gpt-5.6-sol` and make later backend/model changes persistent across tmux death and supervisor recovery.

**Architecture:** `mp` becomes the single source of truth for launch arguments and adds an atomic `switch` operation. The desired backend and model are written to `run/roster.json` before the old tmux window is stopped; `boss-supervisor.sh` revives that record instead of recreating Claude. Codex Boss receives the existing doctrine through `run/boss/AGENTS.md`.

**Tech Stack:** Python 3 standard library, Bash, tmux, Codex CLI 0.144.3, JSON roster, focused Python regression tests.

---

### Task 1: Define the Codex launch and switch contract

**Files:**
- Create: `/home/mp/mypeople/verify/test_codex_boss_switch.py`
- Modify: `/home/mp/mypeople/bin/mp`

- [ ] **Step 1: Write the failing test**

The test must import `bin/mp` and assert:

```python
launch = shlex.split(mp.build_launch(
    "node-1/main:Boss", boss_dir, "", True, "gpt-5.6-sol", "codex"
))
assert launch[0] == "codex"
assert ["--sandbox", "danger-full-access"] == launch[launch.index("--sandbox"):launch.index("--sandbox") + 2]
assert ["--ask-for-approval", "never"] == launch[launch.index("--ask-for-approval"):launch.index("--ask-for-approval") + 2]
assert launch[launch.index("-C") + 1] == os.path.realpath(boss_dir)
assert launch[launch.index("--model") + 1] == "gpt-5.6-sol"
assert "claude" not in launch
assert "--plugin-dir" not in launch
```

It must also monkeypatch roster and tmux helpers, invoke `switch_backend`, and prove the first event persists `backend=codex, model=gpt-5.6-sol` while the final event invokes `revive`.

- [ ] **Step 2: Run test to verify RED**

Run:

```bash
PYTHONPATH=/home/mp/mypeople/bin python3 /home/mp/mypeople/verify/test_codex_boss_switch.py
```

Expected: FAIL because Codex still launches through `claude` and `switch_backend` does not exist.

- [ ] **Step 3: Implement the real Codex launch**

Add a backend branch equivalent to:

```python
if backend == "codex":
    args = [
        "codex", "--sandbox", "danger-full-access",
        "--ask-for-approval", "never", "-C", cwd,
    ]
    if model:
        args += ["--model", model]
    if is_managed_codex_cwd(cwd):
        args += ["--config", f'projects.{json.dumps(os.path.realpath(cwd))}.trust_level = "trusted"']
else:
    args = ["claude", "--dangerously-skip-permissions", "--plugin-dir", plugin_dir]
```

Keep Claude behavior unchanged and accept `--backend codex` in the parser.

- [ ] **Step 4: Implement the atomic switch**

Add:

```python
def switch_backend(ns):
    aid = full_agent_id(ns.agent_id)
    rec = next((row for row in load_roster() if row.get("agent_id") == aid), None)
    if rec is None:
        raise SystemExit("unknown agent")
    desired = {**rec, "backend": ns.backend, "model": ns.model or "", "retired": False,
               "state": "switching", "switched_at": time.time()}
    update_roster(desired)
    _, session, tab = parse_agent_id(aid)
    run_tmux(["kill-window", "-t", f"mc-{session}:{tab}"], check=False)
    run_tmux(["kill-session", "-t", f"rec-{tab}"], check=False)
    main(["revive", aid])
```

Parser contract:

```python
q = sub.add_parser("switch")
q.add_argument("agent_id")
q.add_argument("--backend", required=True, choices=["claude", "codex"])
q.add_argument("--model", required=True)
q.set_defaults(fn=switch_backend)
```

- [ ] **Step 5: Run focused test to verify GREEN**

Run the Task 1 command. Expected: `PASS Codex Boss launch and atomic backend switch`.

### Task 2: Load Boss doctrine through Codex-native instructions

**Files:**
- Modify: `/home/mp/mypeople/verify/test_codex_boss_switch.py`
- Modify: `/home/mp/mypeople/bin/mp`
- Create: `/home/mp/mypeople/run/boss/AGENTS.md`

- [ ] **Step 1: Extend the test and watch it fail**

```python
mp.ensure_codex_doctrine(boss_dir, source)
assert (Path(boss_dir) / "AGENTS.md").read_text() == Path(source).read_text()
```

Expected: FAIL because `ensure_codex_doctrine` does not exist.

- [ ] **Step 2: Add the minimal doctrine writer**

```python
def ensure_codex_doctrine(cwd, source=None):
    source = source or os.path.join(ROOT, "boss-CLAUDE.md")
    body = pathlib.Path(source).read_text(encoding="utf-8")
    target = os.path.join(os.path.realpath(cwd), "AGENTS.md")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        handle.write(body)
```

Call it before launching a Codex master. Expected focused test: PASS.

### Task 3: Make supervisor recovery backend-aware

**Files:**
- Create: `/home/mp/mypeople/verify/test_boss_supervisor_backend.py`
- Modify: `/home/mp/mypeople/bin/boss-supervisor.sh`

- [ ] **Step 1: Write and run the failing supervisor regression**

The test reads the supervisor and requires a roster lookup, `mp revive "$boss_id"`, and a default `mp spawn ... --master` only when the roster has no Boss record. Expected initial result: FAIL because the script hardcodes Claude spawn.

- [ ] **Step 2: Implement roster-aware recovery**

```bash
boss_id="$HOST_ID/main:Boss"
if jq -e --arg aid "$boss_id" '.[] | select(.agent_id == $aid)' "$ROOT/run/roster.json" >/dev/null 2>&1; then
  "$ROOT/bin/mp" revive "$boss_id"
else
  "$ROOT/bin/mp" spawn "$boss_id" --master
fi
```

Do not fall back to Claude when a persisted Codex revive fails; retry on the next supervisor loop.

- [ ] **Step 3: Verify**

Run the focused supervisor test and `bash -n /home/mp/mypeople/bin/boss-supervisor.sh`. Expected: both PASS.

### Task 4: Deploy and switch live Boss to Sol

**Files:**
- Modify: `/home/mp/mypeople/run/roster.json` through `mp switch`
- Replace live tmux window: `mc-main:Boss`

- [ ] **Step 1: Install the tested files atomically from the local staging directory**
- [ ] **Step 2: Run `mp switch node-1/main:Boss --backend codex --model gpt-5.6-sol`**
- [ ] **Step 3: Capture the pane and verify it shows Codex and `gpt-5.6-sol`**
- [ ] **Step 4: Kill only `mc-main:Boss` and verify the supervisor revives Codex Sol from roster**

### Task 5: Verify user-visible behavior and regressions

**Files:**
- Test: `/tmp/mypeople-upstream-tests/test_codex_trust.py`
- Test: `/home/mp/mypeople/verify/verify.sh`
- Runtime evidence: TODO card `78a8f812cabd36ca`

- [ ] **Step 1: Run all four focused upstream regressions**
- [ ] **Step 2: Run the new Codex Boss and supervisor tests**
- [ ] **Step 3: Run the full J1-J52 verifier**
- [ ] **Step 4: Send the existing `test boss` card to Boss and observe a new Boss comment**
- [ ] **Step 5: Confirm roster says `backend=codex`, `model=gpt-5.6-sol`, tmux is alive, and the dashboard remains reachable**

Rollback command after Claude is re-enabled:

```bash
mp switch node-1/main:Boss --backend claude --model sonnet
```
