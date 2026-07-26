# Upstream-Informed Runtime Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add five fail-closed runtime contracts to MyPeople while preserving Gate B, exact session recovery, provider profiles, routing, and persistence.

**Architecture:** Introduce four small pure modules for identity, evidence, provider health, and backend resolution, then integrate them at existing CLI/server boundaries. Prove restart persistence with the real todo server and a disposable runtime directory; run Docker integration only once after all focused tests pass.

**Tech Stack:** Python 3 standard library, tmux process inspection, existing JSON receipts/roster, vanilla browser JavaScript, Docker Compose, standalone Python verifier scripts.

---

### Task 1: Existing tmux agent identity

**Files:**
- Create: `bin/agent_identity.py`
- Modify: `bin/mpcommon.py`
- Modify: `bin/mp`
- Test: `verify/test_agent_identity.py`

- [ ] **Step 1: Write the failing identity tests**

Create tests for `validate_agent_identity(expected, observation)` covering:

```python
assert validate_agent_identity(expected, matching)["state"] == "ready"
assert validate_agent_identity(expected, {**matching, "processAlive": False})["state"] == "process_missing"
assert validate_agent_identity(expected, {**matching, "backend": "claude"})["state"] == "backend_mismatch"
assert validate_agent_identity(expected, {**matching, "profile": "other"})["state"] == "profile_mismatch"
assert validate_agent_identity(expected, {**matching, "model": "other"})["state"] == "model_mismatch"
assert validate_agent_identity(expected, {**matching, "ready": False})["state"] == "not_ready"
```

Also assert that structured required arguments (`cwd`, `owner_task_id`) are compared exactly.

- [ ] **Step 2: Verify RED**

Run:

```powershell
python verify\test_agent_identity.py
```

Expected: failure because `agent_identity` does not exist.

- [ ] **Step 3: Implement the pure contract**

Implement:

```python
def validate_agent_identity(expected: dict, observation: dict) -> dict
def observe_tmux_agent(target: str, runner=run_tmux) -> dict
def validate_tmux_agent(target: str, expected: dict, runner=run_tmux) -> dict
```

Return stable `state`, `checks`, `target`, and `observedAt`. Inspect pane PID,
descendants, executable/arguments, roster identity, and readiness. Do not store
unsanitized command lines.

- [ ] **Step 4: Integrate at reuse/recovery boundaries**

Keep `window_exists()` as the low-level existence primitive. Add
`require_matching_agent()` in `mpcommon.py`; use it before messaging or reusing
an existing window in `mp`, revive, switch, and exact recovery paths. Mismatch
blocks without killing the target.

- [ ] **Step 5: Verify GREEN and commit**

Run:

```powershell
python verify\test_agent_identity.py
python verify\test_provider_session.py
python verify\test_runtime_supervisor.py
```

Commit: `feat: validate existing tmux agent identity`

### Task 2: Evidence validation and visible media errors

**Files:**
- Create: `bin/evidence_validation.py`
- Modify: `bin/todo-server.py`
- Modify: `bin/todos.html`
- Modify: `bin/mp`
- Test: `verify/test_task_evidence.py`

- [ ] **Step 1: Write failing evidence tests**

Add assertions:

```python
for value in ("file:///tmp/x.png", r"C:\tmp\x.png", "C:/tmp/x.png",
              r"\\host\share\x.png", "/home/mp/x.png"):
    assert validate_evidence_url(value)["error"] == "local_evidence_path_rejected"
assert validate_evidence_url("https://example.test/x.png")["ok"] is True
```

Exercise `/todo/proof` and assert HTTP 400 with
`action == "use_proof_file"`. Assert `todos.html` attaches media `error`
listeners and renders the visible failure message.

- [ ] **Step 2: Verify RED**

Run:

```powershell
python verify\test_task_evidence.py
```

Expected: local-path cases are accepted and media error contract is absent.

- [ ] **Step 3: Implement server-side validation**

Implement:

```python
def validate_evidence_url(value: str) -> dict
```

Allow only `http` and `https` link evidence. Reject local/scheme-relative paths
before classification or dereference. Return the typed error and
`use_proof_file` action. Preserve upload hashes and metadata.

- [ ] **Step 4: Implement visible browser failure**

For image/video evidence, attach `error` handlers that add an
`evidence-preview-error` element with:

```text
Evidence preview could not be loaded. Open or download the original artifact.
```

Map the API error to `Use --proof-file <path> to upload local evidence.`

- [ ] **Step 5: Verify GREEN and commit**

Run:

```powershell
python verify\test_task_evidence.py
python verify\test_todo_ui.py
```

Commit: `fix: reject local evidence links`

### Task 3: Typed provider health

**Files:**
- Create: `bin/provider_health.py`
- Modify: `bin/provider-session`
- Modify: `bin/mp`
- Modify: `bin/todo-server.py`
- Test: `verify/test_provider_health.py`
- Test: `verify/test_provider_profiles.py`

- [ ] **Step 1: Write failing classification tests**

Test `classify_provider_health(evidence)` for:

```python
processAlive=False                         # process_dead
authRejected=True                         # expired
quotaRejected=True                        # quota_exhausted
transportFailure=True                     # unreachable
authenticatedInteraction=True             # authenticated
{}                                        # unknown
```

Assert precedence, especially transport failure never becoming `expired`.
Test atomic receipt projection, stale calculation, and sanitization.

- [ ] **Step 2: Verify RED**

Run:

```powershell
python verify\test_provider_health.py
```

Expected: failure because `provider_health` does not exist.

- [ ] **Step 3: Implement health receipts**

Implement:

```python
def classify_provider_health(evidence: dict) -> str
def build_health_receipt(provider, profile, agent_id, evidence, source, now=None) -> dict
def write_health_receipt(runtime_dir, receipt: dict) -> str
def read_health_receipts(runtime_dir, stale_after, now=None) -> list[dict]
```

Store only state, reason code, provider/profile/agent references, timestamps,
source, and sanitized diagnostic references.

- [ ] **Step 4: Integrate event/manual refresh**

Write/update receipts on spawn, revive, switch/start, and classified failures.
Add `mp providers-status [--refresh]`; ordinary reads never contact a provider.
Manual refresh inspects local process/session evidence and is rate-limited.
Expose the same projection through the todo server for Priorities diagnostics.

- [ ] **Step 5: Verify GREEN and commit**

Run:

```powershell
python verify\test_provider_health.py
python verify\test_provider_profiles.py
python verify\test_provider_session.py
python verify\test_provider_shared_primitives.py
```

Commit: `feat: classify provider health`

### Task 4: Explicit fail-closed backend resolution

**Files:**
- Create: `bin/backend_resolution.py`
- Modify: `bin/mp`
- Modify: `bin/queue-server.py`
- Test: `verify/test_backend_resolution.py`
- Test: `verify/test_provider_profiles.py`

- [ ] **Step 1: Write failing resolution tests**

Test:

```python
resolve_backend(explicit="codex", profile="claude", policy="claude")
resolve_backend(explicit="", profile="codex", policy="claude")
resolve_backend(explicit="", profile="", policy="claude")
```

and assert respectively `explicit`, `profile`, and `routing_policy` sources.
Missing inputs raise `backend_unresolved`; conflicting inputs at the same
precedence raise `backend_ambiguous`. No test may observe a default Claude
selection.

- [ ] **Step 2: Verify RED**

Run:

```powershell
python verify\test_backend_resolution.py
```

Expected: failure because the resolver does not exist.

- [ ] **Step 3: Implement resolver and receipts**

Implement:

```python
class BackendResolutionError(ValueError):
    code: str

def resolve_backend(*, explicit="", profile="", policy="") -> dict
```

Supported values are `codex` and `claude`. Return `backend` and
`resolutionSource`. Update spawn receipts and remote payloads to record and
verify the source.

- [ ] **Step 4: Remove implicit defaults**

Change CLI parsing so an omitted backend remains unset until the resolver runs.
Resolve from explicit command/task, assigned profile, then routing decision.
Fail visibly when unresolved; retain explicit Claude support.

- [ ] **Step 5: Verify GREEN and commit**

Run:

```powershell
python verify\test_backend_resolution.py
python verify\test_provider_profiles.py
python verify\test_codex_boss_switch.py
python verify\test_boss_adaptive_routing.py
```

Commit: `fix: resolve agent backends explicitly`

### Task 5: Restart persistence E2E and integrated gate

**Files:**
- Modify: `verify/test_docker_persistence.py`
- Create: `verify/test_todo_restart_persistence.py`
- Modify: `verify/verify.sh`
- Modify: `docs/MANUAL.md`

- [ ] **Step 1: Write the failing restart E2E**

Start a real isolated todo server with temporary `BOARD_PATH`, `PROOFS_DIR`,
roster, and project profiles. Create a task with project, context question,
state, evidence policy, owner/history, comments, one uploaded artifact, unread,
and verification fields. Stop and restart the server, then assert exact
canonical equality, readable identical artifact SHA-256, and no duplicate
events/tasks.

- [ ] **Step 2: Verify RED**

Run:

```powershell
python verify\test_todo_restart_persistence.py
```

Expected: fail on any missing persistence contract or missing test support.

- [ ] **Step 3: Apply the minimum persistence corrections**

Correct only demonstrated persistence defects. Keep atomic board writes and
existing volume paths; do not introduce a second store.

- [ ] **Step 4: Verify focused and full isolated suites**

Run:

```powershell
python verify\test_todo_restart_persistence.py
python verify\test_docker_persistence.py
bash verify/verify.sh
```

Then build/run the disposable Docker verifier once and confirm J1-J52 plus Gate
B regressions without reading or writing the live board.

- [ ] **Step 5: Document and commit**

Document `mp providers-status`, local-evidence upload guidance, explicit backend
resolution, and restart persistence. Commit:

```text
test: prove runtime hardening persistence
```

### Final review

- [ ] Re-read the approved design and map every acceptance criterion to a test.
- [ ] Run `git diff --check` and inspect every changed file.
- [ ] Run the complete verifier once more only if code changed after the
  integrated gate.
- [ ] Present bug reproduction, RED evidence, implementation, GREEN evidence,
  Gate B interaction, and deployment recommendation.
- [ ] Do not merge, push, or deploy until explicit approval.
