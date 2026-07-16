# Exact Agent Session Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist provider session identity and make deliberate stop, exact revive, bounded reconcile, and provider-changing handoff behavior truthful and recoverable.

**Architecture:** Add a standard-library-only session module that owns session discovery, transcript validation, resume argv, and capture locks. Keep tmux/task orchestration in `bin/mp`, persist lifecycle intent in the roster before process mutation, and make `mp reconcile` strict and bounded. Same backend/profile resumes exactly; backend/profile changes require the existing provider transaction plus an explicitly authorized fresh handoff.

**Tech Stack:** Python 3.11 standard library, Linux `fcntl` locks, tmux, Codex CLI 0.144.3, Claude Code 2.1.209, Bash supervisor, JSON roster/status files, Docker isolated verification, Windows PowerShell 5.1 upgrade tooling.

---

## File Map

- Create `bin/agent_session.py`: provider-neutral session validation, Codex discovery, transcript checks, capture locks, resume argv, and fresh-handoff authorization.
- Modify `bin/mpcommon.py`: atomic roster session update helper used by hooks and runtime.
- Modify `bin/mp`: fresh-session capture, strict exact revive, deliberate stop, model switching, fresh-handoff command, and bounded reconcile.
- Modify `plugins/tmux-boss-hooks/scripts/emit-event`: persist Claude hook session IDs into roster as well as status.
- Modify `bin/provider-session`: use authorized fresh handoffs for identity-changing switches and exact revive for rollback.
- Modify `bin/boss-supervisor.sh`: bootstrap only absent internal roles and delegate recovery to `mp reconcile`.
- Create `verify/test_agent_session.py`: isolated session-module unit tests.
- Create `verify/test_exact_session_recovery.py`: lifecycle and reconcile contract tests.
- Create `verify/test_claude_session_hook.py`: subprocess-level Claude hook persistence test.
- Modify `verify/test_codex_boss_switch.py`: same-profile model switch and resume argv coverage.
- Modify `verify/test_boss_supervisor_backend.py`: deliberate-stop and reconcile delegation coverage.
- Modify `verify/test_provider_session.py`: authorized fresh-handoff and exact rollback coverage.
- Modify `docs/USER-MANUAL.md`: replace the known fresh-revive limitation with the exact lifecycle contract.
- Modify `README.md`: document session persistence and bounded recovery in the public overview.

## Test Environment

The runtime imports `fcntl` and must be tested in Linux. Use this read-only isolated wrapper for focused baseline and regression tests:

```powershell
$image = docker inspect mypeople --format '{{.Config.Image}}'
$repo = (Resolve-Path '.').Path
docker run --rm --entrypoint bash -v "${repo}:/work:ro" $image -lc "
  cd /work &&
  export PYTHONPATH=/work/bin +    MYPEOPLE_MP_BIN=/work/bin/mp +    MYPEOPLE_SUPERVISOR=/work/bin/boss-supervisor.sh &&
  python3 -B verify/test_agent_session.py
"
```

Do not treat native Windows `ModuleNotFoundError: fcntl` as a product failure.

### Task 1: Build session identity and discovery primitives

**Files:**
- Create: `verify/test_agent_session.py`
- Create: `bin/agent_session.py`

- [ ] **Step 1: Write failing validation, discovery, lock, and resume-argv tests**

Create tests that use only temporary directories:

```python
class AgentSessionContract(unittest.TestCase):
    def test_session_id_rejects_paths_and_control_characters(self):
        for value in ("", "../escape", "a/b", "a\\b", "bad\nvalue"):
            with self.assertRaisesRegex(runtime.SessionError, "session_id_invalid"):
                runtime.validate_session_id(value)

    def test_codex_discovery_accepts_one_new_matching_session(self):
        before = runtime.snapshot_codex_sessions(self.codex_home)
        write_session_meta(
            self.codex_home,
            "019f0000-0000-7000-8000-000000000001",
            self.cwd,
        )
        found = runtime.discover_codex_session(
            self.codex_home, self.cwd, before, timeout=0.2, poll=0.01
        )
        self.assertEqual(found["session_id"], "019f0000-0000-7000-8000-000000000001")

    def test_resume_arguments_keep_session_id_last_for_codex(self):
        args = runtime.apply_resume_args(
            "codex", ["codex", "--model", "gpt-test"], "session-1234"
        )
        self.assertEqual(args, ["codex", "resume", "--model", "gpt-test", "session-1234"])

    def test_resume_arguments_append_claude_resume(self):
        self.assertEqual(
            runtime.apply_resume_args("claude", ["claude", "--model", "test"], "session-1234"),
            ["claude", "--model", "test", "--resume", "session-1234"],
        )
```

Add fixtures that reject stale, malformed, ambiguous, and wrong-cwd metadata
with exact typed codes. Add a two-process lock test: the first process holds the
profile lock and the second fails with `session_capture_busy` inside a
bounded timeout.

- [ ] **Step 2: Run the new test and observe RED**

Run the isolated wrapper with `verify/test_agent_session.py`.

Expected: FAIL because `bin/agent_session.py` does not exist.

- [ ] **Step 3: Implement the minimal standard-library session module**

Implement these public units:

```python
class SessionError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)

def validate_session_id(value: str) -> str:
    candidate = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]{8,160}", candidate):
        raise SessionError("session_id_invalid")
    return candidate

def snapshot_codex_sessions(codex_home: str) -> set[str]:
    root = Path(os.path.realpath(codex_home)) / "sessions"
    return {str(path.resolve()) for path in root.glob("**/*.jsonl") if path.is_file()}

def read_codex_session_meta(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        event = json.loads(stream.readline())
    payload = event.get("payload", {})
    if event.get("type") != "session_meta" or not isinstance(payload, dict):
        raise SessionError("session_metadata_invalid")
    return {
        "session_id": validate_session_id(payload.get("id") or payload.get("session_id")),
        "cwd": os.path.realpath(str(payload.get("cwd") or "")),
        "path": str(path.resolve()),
    }

def apply_resume_args(backend: str, args: list[str], session_id: str) -> list[str]:
    sid = validate_session_id(session_id)
    if backend == "codex":
        if not args or args[0] != "codex":
            raise SessionError("resume_argv_invalid")
        return [args[0], "resume", *args[1:], sid]
    if backend == "claude":
        return [*args, "--resume", sid]
    raise SessionError("session_backend_unsupported")
```

Use `fcntl.flock(LOCK_EX | LOCK_NB)` on a private file derived from backend
and profile, for example `run/session-capture/codex/codex-primary.lock`. Implement
`discover_codex_session` as bounded polling that requires exactly one new,
valid, real-cwd-matching candidate.

Add `session_files` and `validate_resume_evidence` for Codex
`$CODEX_HOME/sessions/**/*session-1234*.jsonl` and Claude
`$CLAUDE_CONFIG_DIR/projects/**/session-1234.jsonl`, with the validated real
session ID substituted by the implementation, falling back to
`~/.claude/projects`.

- [ ] **Step 4: Run the new test and observe GREEN**

Expected: all `AgentSessionContract` tests pass with no warnings.

- [ ] **Step 5: Commit**

```bash
git add bin/agent_session.py verify/test_agent_session.py
git commit -m "feat: add provider session identity primitives"
```

### Task 2: Capture fresh Codex sessions and persist identity

**Files:**
- Modify: `bin/mp`
- Modify: `bin/mpcommon.py`
- Create: `verify/test_exact_session_recovery.py`

- [ ] **Step 1: Write failing spawn-capture tests**

Load `bin/mp` with tmux, roster, status, provider profiles, and composer
polling mocked. Assert:

```python
def test_fresh_codex_spawn_persists_discovered_session(self):
    self.mp.spawn(namespace())
    record = self.records[-1]
    self.assertEqual(record["session_id"], SESSION_ID)
    self.assertEqual(record["session_backend"], "codex")
    self.assertEqual(record["session_profile"], "codex-primary")
    self.assertEqual(record["session_cwd"], os.path.realpath(self.cwd))
    self.assertEqual(record["resume_state"], "available")

def test_capture_timeout_keeps_window_but_never_guesses_session(self):
    self.mp.spawn(namespace())
    record = self.records[-1]
    self.assertEqual(record["session_id"], "")
    self.assertEqual(record["resume_state"], "unavailable")
    self.assertEqual(record["last_recovery_error"], "session_capture_timeout")
```

Assert the capture lock is acquired before the first tmux creation event and
released after the identity update.

- [ ] **Step 2: Run the focused test and observe RED**

Expected: FAIL because spawn does not call the session runtime or populate the
new roster fields.

- [ ] **Step 3: Add one atomic roster identity updater**

In `bin/mpcommon.py` add:

```python
def record_session_identity(agent_id: str, identity: dict) -> dict:
    with json_lock(roster_path()):
        rows = load_roster()
        current = next((dict(row) for row in rows if row.get("agent_id") == agent_id), None)
        if current is None:
            raise ValueError("unknown_agent")
        current.update(identity)
        save_roster([current if row.get("agent_id") == agent_id else row for row in rows])
    return current
```

- [ ] **Step 4: Integrate Codex capture into fresh spawn**

In `bin/mp` initialize `resume_state=pending` and recovery defaults.
For fresh Codex launch, acquire the profile capture lock before tmux creation,
snapshot, launch, discover, then update roster/status atomically. On typed
capture failure, retain the live window and store only the typed code. Disable
capture when exact-resuming.

- [ ] **Step 5: Run Task 1 and Task 2 tests**

Also re-run `verify/test_taskspec_spawn.py` and
`verify/test_worker_handoff.py`.

- [ ] **Step 6: Commit**

```bash
git add bin/mp bin/mpcommon.py verify/test_exact_session_recovery.py
git commit -m "feat: persist fresh Codex session identity"
```

### Task 3: Persist Claude hook session IDs

**Files:**
- Modify: `plugins/tmux-boss-hooks/scripts/emit-event`
- Create: `verify/test_claude_session_hook.py`

- [ ] **Step 1: Write a subprocess-level failing hook test**

Use temporary `ROSTER_PATH` and `STATUS_DIR`, set `AGENT_ID`,
`INSTALL_DIR`, and `PYTHONPATH`, then feed:

```python
payload = {"hook_event_name": "SessionStart", "session_id": "claude-session-1234"}
completed = subprocess.run(
    [sys.executable, str(HOOK)],
    input=json.dumps(payload),
    text=True,
    env=environment,
    capture_output=True,
)
self.assertEqual(completed.returncode, 0)
self.assertEqual(load_roster()[0]["session_id"], "claude-session-1234")
self.assertEqual(load_roster()[0]["session_backend"], "claude")
self.assertEqual(load_roster()[0]["resume_state"], "available")
```

Assert invalid session input leaves roster unchanged and hook stdout empty.

- [ ] **Step 2: Run the hook test and observe RED**

Expected: status receives the ID, but roster does not.

- [ ] **Step 3: Update the hook**

Call `record_session_identity` only for a validated session ID:

```python
record_session_identity(
    AGENT,
    {
        "session_id": validate_session_id(session_id),
        "session_backend": "claude",
        "session_profile": os.environ.get("MYPEOPLE_PROVIDER_PROFILE", ""),
        "session_cwd": os.path.realpath(os.getcwd()),
        "session_recorded_at": time.time(),
        "resume_state": "available",
        "last_recovery_error": "",
    },
)
```

Keep `UserPromptSubmit` stdout empty and preserve atomic status writes.

- [ ] **Step 4: Run hook, worker, and provider tests**

Expected: hook test, `test_worker_handoff.py`, and
`test_provider_session.py` pass.

- [ ] **Step 5: Commit**

```bash
git add plugins/tmux-boss-hooks/scripts/emit-event verify/test_claude_session_hook.py
git commit -m "feat: persist Claude session identity from hooks"
```

### Task 4: Make kill deliberate and revive exact

**Files:**
- Modify: `bin/mp`
- Modify: `verify/test_exact_session_recovery.py`
- Modify: `verify/test_codex_boss_switch.py`

- [ ] **Step 1: Write failing deliberate-stop ordering tests**

Record every roster and tmux event. Require:

```python
self.mp.kill(argparse.Namespace(agent_id=AGENT, reason="operator-request"))
self.assertEqual(events[0][0], "persist")
self.assertTrue(events[0][1]["retired"])
self.assertEqual(events[0][1]["stop_intent"], "deliberate")
self.assertEqual(events[0][1]["state"], "stopping")
self.assertGreater(
    next(i for i, event in enumerate(events) if event[0] == "tmux"),
    0,
)
```

Then assert the final record is `dead/stopped` and preserves session,
TaskSpec, role, cwd, backend, profile, and model fields.

- [ ] **Step 2: Write failing strict-revive tests**

Cover:

- missing session ID fails before tmux with `session_missing`;
- missing transcript fails before tmux;
- backend/profile/cwd mismatch fails before tmux;
- closed or reassigned owner task remains rejected;
- a valid Codex record invokes `codex resume ... session-1234`;
- a valid Claude record invokes `claude ... --resume session-1234`;
- failed launch restores the previous deliberate tombstone;
- successful launch clears `stop_intent` and preserves task/role receipts.

- [ ] **Step 3: Run the lifecycle tests and observe RED**

Expected: current kill mutates roster after tmux and current revive calls fresh
spawn.

- [ ] **Step 4: Implement strict lifecycle helpers**

Refactor record reconstruction into:

```python
def namespace_from_record(record: dict) -> argparse.Namespace:
    return argparse.Namespace(
        agent_id=record["agent_id"],
        backend=record["backend"],
        cwd=record["cwd"],
        boss=record.get("boss_id") or None,
        master=bool(record.get("is_master")),
        model=record.get("model") or None,
        owner_task=record.get("owner_task_id") if record.get("lifecycle") == "owner" else None,
        temporary=record.get("lifecycle") == "temporary",
    )
```

Let `spawn(ns, resume_session="")` apply the existing worker contract before
`apply_resume_args` so the Codex session ID remains the final positional
argument.

Make `revive`:

1. validate task and immutable receipts;
2. resolve effective backend/profile/cwd;
3. validate exact resume evidence;
4. persist `recovering` without deleting the prior tombstone snapshot;
5. call `spawn(..., resume_session=session_id)`;
6. restore the snapshot on any failure;
7. clear stop intent only after a live window and matching session identity.

- [ ] **Step 5: Implement same-profile model switching**

In `switch_backend`, compare current and requested backend plus effective
profile. When identity is unchanged, persist the desired model, stop only
tmux/recorder without creating a deliberate tombstone, call strict exact revive,
and verify the UUID did not change.

Reject identity-changing direct `mp switch` with
`fresh_handoff_required`; Task 6 supplies the authorized route.

- [ ] **Step 6: Run focused lifecycle tests**

Expected: exact recovery, Codex switch, TaskSpec spawn, worker handoff, and
review-resume tests pass.

- [ ] **Step 7: Commit**

```bash
git add bin/mp verify/test_exact_session_recovery.py verify/test_codex_boss_switch.py
git commit -m "feat: make agent stop and revive lossless"
```

### Task 5: Add bounded reconcile and supervisor delegation

**Files:**
- Modify: `bin/mp`
- Modify: `bin/boss-supervisor.sh`
- Modify: `verify/test_exact_session_recovery.py`
- Modify: `verify/test_boss_supervisor_backend.py`

- [ ] **Step 1: Write failing reconcile state-machine tests**

Use injected time and mocked `window_exists`/`revive`:

```python
def test_reconcile_skips_deliberate_stop(self):
    self.assertEqual(self.run_reconcile(deliberately_stopped()), [])

def test_reconcile_uses_exact_resume_and_never_fresh_spawn(self):
    self.run_reconcile(missing_window_with_session())
    self.assertEqual(calls, [("revive", AGENT)])
    self.assertNotIn("spawn", [call[0] for call in calls])

def test_reconcile_honors_cooldown_and_blocks_after_three_failures(self):
    record = missing_window_with_session(recovery_attempts=3)
    self.run_reconcile(record)
    self.assertEqual(saved["recovery_state"], "blocked")
    self.assertEqual(saved["last_recovery_error"], "recovery_attempts_exhausted")

def test_starting_without_session_has_three_labeled_bootstrap_retries(self):
    record = never_started(recovery_attempts=2)
    self.run_reconcile(record)
    self.assertEqual(calls[0][0], "bootstrap_retry")
```

Require defaults: 30-second cooldown, three recovery attempts, 90-second
starting threshold, and three bootstrap retries.

- [ ] **Step 2: Run reconcile tests and observe RED**

Expected: parser has no `reconcile` command and supervisor owns unbounded
revival behavior.

- [ ] **Step 3: Implement `mp reconcile`**

Add injectable defaults:

```python
RECOVERY_COOLDOWN = float(os.environ.get("MYPEOPLE_RECOVERY_COOLDOWN_SEC", "30"))
RECOVERY_MAX = int(os.environ.get("MYPEOPLE_RECOVERY_MAX", "3"))
STARTING_STALE = float(os.environ.get("MYPEOPLE_STARTING_STALE_SEC", "90"))
BOOTSTRAP_MAX = int(os.environ.get("MYPEOPLE_BOOTSTRAP_RETRY_MAX", "3"))
```

For each record, atomically transition through `recovering`,
`cooldown`, or `blocked`. Use strict revive when session evidence
exists. Permit `bootstrap_retry` only for a stale `starting` record that
never had a session. Persist a bounded typed error and next attempt time.

- [ ] **Step 4: Simplify the Bash supervisor**

After provider pause/switch guards:

- bootstrap Boss or Nightwatch only when no roster record exists;
- never bootstrap over an existing stopped record;
- call `mp reconcile` once per loop;
- sleep 15 seconds;
- log only typed concise failures.

Do not add a second daemon or independent recovery database.

- [ ] **Step 5: Run focused supervisor and reconcile tests**

Also run `bash -n bin/boss-supervisor.sh` in the isolated container.

Expected: all tests pass and the supervisor contains no direct `mp revive`
fallback for an existing agent.

- [ ] **Step 6: Commit**

```bash
git add bin/mp bin/boss-supervisor.sh verify/test_exact_session_recovery.py verify/test_boss_supervisor_backend.py
git commit -m "feat: reconcile failed agents with bounded exact recovery"
```

### Task 6: Preserve explicit provider switching with fresh handoffs

**Files:**
- Modify: `bin/agent_session.py`
- Modify: `bin/mp`
- Modify: `bin/provider-session`
- Modify: `verify/test_provider_session.py`
- Modify: `verify/test_exact_session_recovery.py`

- [ ] **Step 1: Write failing fresh-handoff authorization tests**

Require all of these before fresh launch:

- provider-switch lock names the requested transaction;
- transaction state is `stopped`;
- handoff resolves below that private transaction directory;
- handoff contains the selected agent;
- selected task/cwd/role receipts match the snapshot;
- direct invocation without the transaction fails.

Assert forward revival calls:

```python
[
    "fresh-handoff",
    agent_id,
    "--transaction",
    transaction_id,
    "--handoff",
    handoff_path,
]
```

Assert rollback restores old bindings before strict `revive`.

- [ ] **Step 2: Run provider-session tests and observe RED**

Expected: forward provider switching still calls `mp revive`.

- [ ] **Step 3: Implement transaction-bound authorization**

Add `validate_fresh_handoff` in `agent_session.py` using
`realpath/commonpath`, private regular-file checks, transaction ID
validation, lock ownership, state phase, and agent match.

Add a narrow parser command:

```python
q = sub.add_parser("fresh-handoff")
q.add_argument("agent_id")
q.add_argument("--transaction", required=True)
q.add_argument("--handoff", required=True)
q.set_defaults(fn=fresh_handoff)
```

The command reconstructs a fresh spawn from the roster snapshot, preserves
TaskSpec/role/task fields, sets `resume_state=pending`, injects the bounded
handoff as the first user message, and records a new session honestly.

- [ ] **Step 4: Update provider-session forward and rollback paths**

Write one private handoff file per selected agent during `prepare`.
`command_revive` uses `fresh-handoff` after identity change.
`rollback` restores bindings/roster and uses strict `revive` because the
old profile home still contains the exact session.

- [ ] **Step 5: Run provider transaction and lifecycle tests**

Expected: forward switch reports a new session; rollback reports the original
session; no path permits `reconcile` to call `fresh-handoff`.

- [ ] **Step 6: Commit**

```bash
git add bin/agent_session.py bin/mp bin/provider-session verify/test_provider_session.py verify/test_exact_session_recovery.py
git commit -m "feat: require explicit handoffs for provider changes"
```

### Task 7: Update public documentation and verification contracts

**Files:**
- Modify: `docs/USER-MANUAL.md`
- Modify: `README.md`
- Modify: `verify/test_public_repository.py`

- [ ] **Step 1: Write a failing public contract**

Require the manual and README to contain:

- `exact session resume`;
- `deliberate stop`;
- `mp reconcile`;
- `three recovery attempts`;
- explicit fresh handoff for backend/profile changes;
- no silent fresh fallback.

Remove the old sentence claiming `mp revive` always opens a new Codex
conversation.

- [ ] **Step 2: Run the public test and observe RED**

Expected: FAIL because the current manual documents fresh revive as a known
limitation.

- [ ] **Step 3: Update the manual and README**

Document operator commands:

```powershell
docker exec mypeople /home/mp/mypeople/bin/mp kill main:Boss --reason operator-request
docker exec mypeople /home/mp/mypeople/bin/mp revive main:Boss
docker exec mypeople /home/mp/mypeople/bin/mp reconcile
docker exec mypeople /home/mp/mypeople/bin/mp switch main:Boss --backend codex --model gpt-5.6-luna
```

Explain that deliberate kill stays stopped, revive is exact only with matching
session identity, same-profile model switch is exact, provider/profile switch
is fresh with sanitized handoff, and blocked recovery requires inspection rather
than automatic expensive retry.

- [ ] **Step 4: Run public, lifecycle, and secret checks**

```powershell
python -B verify\test_public_repository.py
python -B verify\test_public_history.py
git diff --check
```

If `scripts/check-secrets.ps1` exists, run it in strict mode; otherwise use
the existing public-history and token-pattern verifier.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/USER-MANUAL.md verify/test_public_repository.py
git commit -m "docs: explain exact agent recovery"
```

### Task 8: Complete isolated verification, review, rollout, and live canary

**Files:**
- Verify: all changed runtime, tests, and docs
- Runtime state: Docker volumes through the existing backup-first upgrade script
- GitHub: feature branch and pull request after verification

- [ ] **Step 1: Run every focused test from the isolated source mount**

Run Task 1–7 tests plus:

```text
verify/test_taskspec_spawn.py
verify/test_worker_handoff.py
verify/test_codex_boss_switch.py
verify/test_boss_supervisor_backend.py
verify/test_provider_session.py
verify/test_provider_launch_pause.py
verify/test_review_resume_revive.py
verify/test_queue_agent_reconciliation.py
verify/test_runtime_supervisor.py
verify/test_public_repository.py
```

Expected: zero failures.

- [ ] **Step 2: Run the full isolated verifier**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File verify\Invoke-IsolatedVerify.ps1
```

Expected: the complete verifier passes without writing to the live board,
provider homes, roster, or workspaces.

- [ ] **Step 3: Request an independent code review**

Review the complete feature diff against the design. Require explicit review
of session attribution races, transcript/path validation, tombstone ordering,
retry caps, no fresh reconcile fallback, provider-switch authorization, and
secret/public-state boundaries.

Fix every Critical or Important finding with a new RED/GREEN test cycle.

- [ ] **Step 4: Build and verify the candidate image**

```powershell
$base = docker inspect mypeople --format '{{.Config.Image}}'
$sha = git rev-parse --short HEAD
$image = "mypeople-node:exact-session-$sha"
docker build -f docker/Dockerfile.runtime-image --build-arg BASE_IMAGE=$base -t $image .
```

Run the packaged-source focused tests and full isolated verifier against
`$image`. Record image ID and source commit.

- [ ] **Step 5: Perform the backup-first live image upgrade**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File windows\Upgrade-MyPeopleDockerImage.ps1 -CandidateImage $image
```

Expected:

- upgrade transaction reports PASS;
- Priorities, queue/HUD, terminal, workspace, Boss, and Nightwatch are healthy;
- board, evidence, provider bindings, and workspaces are unchanged;
- previous image remains available for rollback.

- [ ] **Step 6: Run the disposable exact-resume canary**

Create one temporary non-owner Codex worker with a unique non-secret marker.
Verify:

1. roster has a nonempty session UUID and `resume_state=available`;
2. `mp kill` leaves it stopped for at least two supervisor cycles;
3. `mp revive` restores the same UUID;
4. the provider conversation can report the marker;
5. Boss/Nightwatch UUIDs and windows were never used as test subjects.

Then deliberately retire the canary. Remove only its disposable tmux, status,
roster, and recording artifacts after verifying it owns no task or workspace.

- [ ] **Step 7: Re-run the one-click launcher smoke**

Run the installed Desktop launcher and confirm the log ends with
`READY http://localhost:9933/`. Confirm the upgraded image remains active and
provider status is not paused.

- [ ] **Step 8: Commit any verification-only documentation**

If verification produced tracked documentation changes, commit only those
reviewed files:

```bash
git add README.md docs/USER-MANUAL.md
git commit -m "test: verify exact agent session recovery"
```

Do not commit runtime state, transcripts, provider homes, recordings, tokens, or
machine-specific paths.

- [ ] **Step 9: Push, open an English PR, and merge after clean review**

```powershell
git push -u origin feat/exact-session-recovery
gh pr create --repo LordCripto-Hub/Project-Factory --base main --head feat/exact-session-recovery --title "Add exact agent session recovery" --body "Adds provider session capture, deliberate stop intent, strict exact revive, bounded reconcile, and transaction-authorized fresh handoffs. Verification: focused lifecycle suites, isolated full verifier, packaged-image checks, disposable same-UUID canary, and launcher smoke."
```

Verify exact head SHA, clean merge state, public-content checks, and reviewer
approval before merging. Do not delete the worktree while PR iteration remains
possible.
