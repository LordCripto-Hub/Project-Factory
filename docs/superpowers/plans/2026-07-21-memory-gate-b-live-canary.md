# Memory Gate B Active Live Canary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run one explicit Project Factory task with bounded local memory, measured baseline/candidate context, honest provider/session telemetry, and no-restart rollback.

**Architecture:** A new `memory_canary.py` module owns the atomically read runtime gate and append-oriented receipts. Existing TaskSpec compilation remains authoritative and calls the existing MemoryGateway only for a task-level opt-in; an explicit Docker sidecar serves the locked public Gate B dataset over an internal-only network. Priorities exposes compact status and operator controls without giving workers a memory tool.

**Tech Stack:** Python 3 standard library, existing Node MCP gateway, Docker Compose, PowerShell 5.1, vanilla HTML/CSS/JavaScript, `unittest`, existing Playwright verifier.

---

## File Structure

- Create `bin/memory_canary.py`: validate/update the runtime gate, append receipts, calculate context deltas, and produce safe session aliases.
- Modify `bin/mp`: expose `memory-canary` control commands, compile baseline/candidate TaskSpecs, start/bypass attempts, and attach model/session completion metadata.
- Modify `bin/todo-server.py`: persist the opt-in Boolean and expose canary status/control endpoints.
- Modify `bin/todos.html`: render the memory strip and explicit controls.
- Modify `bin/project_context.py`: allow the exact reviewed internal HTTP canary endpoint without weakening remote HTTPS validation.
- Modify `memory-gateway/memory-gateway.mjs`: accept HTTP only when it exactly matches the process-provided canary URL.
- Create `experiments/memory-gate-b/docker/compose.live-canary.yml`: run the sidecar on an internal-only network with the locked dataset.
- Create `experiments/memory-gate-b/docker/live-canary-entrypoint.sh`: fail-closed sidecar entrypoint and health receipt.
- Modify `experiments/memory-gate-b/docker/taskspec-memory-server.mjs`: parameterize bind host/port while preserving isolated-fixture defaults.
- Create `windows/Start-MyPeopleMemoryCanary.ps1`: bounded sidecar/network/token activation and cleanup.
- Create focused tests under `verify/` and register them in `verify/run-suite.sh`.
- Modify `README.md` and `docs/USER-MANUAL.md`: document opt-in, metrics, limitation, and rollback.

## Task 1: Add the private runtime gate

**Files:**
- Create: `bin/memory_canary.py`
- Create: `verify/test_memory_canary_control.py`
- Modify: `bin/mp`

- [ ] **Step 1: Write the failing control tests**

Create `verify/test_memory_canary_control.py` with real temporary files. The core tests must express this API:

```python
control = memory_canary.load_control(root)
self.assertFalse(control["enabled"])
self.assertEqual(control["allowedProjects"], ["project-factory"])

enabled = memory_canary.set_control(
    root, enabled=True, project="project-factory", now=lambda: 100.0
)
self.assertTrue(enabled["enabled"])
self.assertEqual(enabled["revision"], 2)
self.assertEqual(os.stat(Path(root) / "memory-canary-control.json").st_mode & 0o777, 0o600)

same = memory_canary.set_control(
    root, enabled=True, project="project-factory", now=lambda: 200.0
)
self.assertEqual(same, enabled)
```

Also prove malformed JSON, unknown fields, a project other than
`project-factory`, a symlinked control file, and non-Boolean `enabled` all read
as `MemoryCanaryError("canary_control_invalid")`; the caller may convert a
missing file to the disabled default but must not silently accept corruption.

- [ ] **Step 2: Run the test and verify RED**

```powershell
python -B verify\test_memory_canary_control.py -v
```

Expected: FAIL because `bin/memory_canary.py` does not exist.

- [ ] **Step 3: Implement the minimal gate module**

Implement `DEFAULT_CONTROL` with exactly schema version 1, disabled state,
`["project-factory"]`, revision 1, and timestamp 0. Implement
`MemoryCanaryError(code)` with a public `code` property. The public function
signatures are exactly:

- `load_control(runtime_dir, *, missing_ok=True) -> dict`;
- `set_control(runtime_dir, *, enabled, project="project-factory", now=time.time) -> dict`;
- `assert_task_allowed(task, control) -> None`.

`load_control` must reject symlinks, unknown fields, duplicate projects,
non-monotonic revisions, and any project except `project-factory`.
`set_control` writes a sibling temporary file with `O_EXCL`, fsyncs, chmods
`0600`, replaces atomically, and leaves the revision unchanged for an
idempotent request.

- [ ] **Step 4: Add the CLI contract to `bin/mp`**

Register one parser with required subcommands:

```python
canary = sub.add_parser("memory-canary")
canary_sub = canary.add_subparsers(dest="memory_canary_action", required=True)
canary_sub.add_parser("status")
enable = canary_sub.add_parser("enable")
enable.add_argument("--project", required=True)
canary_sub.add_parser("disable")
canary.set_defaults(fn=memory_canary_command)
```

`memory_canary_command` resolves only `ROOT/run`, calls the module, and prints
one JSON object containing `enabled`, `allowedProjects`, and `revision`.

- [ ] **Step 5: Verify GREEN and commit**

```powershell
python -B verify\test_memory_canary_control.py -v
python -B verify\test_public_repository.py -v
git diff --check
git add bin/memory_canary.py bin/mp verify/test_memory_canary_control.py
git commit -m "feat: add atomic memory canary control"
```

Expected: all focused tests pass and the diff check is empty.

## Task 2: Persist task-level opt-in without changing legacy cards

**Files:**
- Modify: `bin/todo-server.py`
- Modify: `bin/todos.html`
- Modify: `verify/test_task_project_fields.py`

- [ ] **Step 1: Write failing task-schema tests**

Extend `verify/test_task_project_fields.py` with:

```python
def test_memory_canary_defaults_false_and_requires_project_contract(self):
    legacy = self.server.normalize_task({"id": "legacy", "text": "Legacy"})
    self.assertIs(legacy["memoryCanary"], False)
    with self.assertRaisesRegex(ValueError, "memory_canary_requires_project_factory"):
        self.server.validate_memory_canary(True, "other", "Question?")
    with self.assertRaisesRegex(ValueError, "memory_canary_requires_question"):
        self.server.validate_memory_canary(True, "project-factory", "")
    self.assertTrue(
        self.server.validate_memory_canary(
            True, "project-factory", "Which verified constraint applies?"
        )
    )
```

Add update tests proving partial edits preserve `memoryCanary`, only CEO/Boss
authentication may change it, and setting it false never requires a question.

- [ ] **Step 2: Run and verify RED**

```powershell
python -B verify\test_task_project_fields.py -v
```

Expected: FAIL because `memoryCanary` and `validate_memory_canary` are absent.

- [ ] **Step 3: Implement the board contract**

Add `memoryCanary: False` to `normalize_task`. Implement:

```python
def validate_memory_canary(value, project_slug, context_question):
    if not isinstance(value, bool):
        raise ValueError("invalid_memory_canary")
    if not value:
        return False
    if project_slug != "project-factory":
        raise ValueError("memory_canary_requires_project_factory")
    if not context_question:
        raise ValueError("memory_canary_requires_question")
    return True
```

Validate the combined final card for both `add` and `set`, not each field in
isolation. Never infer opt-in from a context question or enabled profile.

- [ ] **Step 4: Add only the opt-in editor control**

Add an unchecked checkbox to the existing modal:

```html
<label class="memory-opt-in">
  <input id="memoryCanary" type="checkbox">
  Use Memory Gate B canary for this task
</label>
```

`openModal` reads `task.memoryCanary`; `saveDetails` sends the Boolean. Do not
add status buttons yet.

- [ ] **Step 5: Verify GREEN and commit**

```powershell
python -B verify\test_task_project_fields.py -v
node verify\test_browser_error_filter.js
git diff --check
git add bin/todo-server.py bin/todos.html verify/test_task_project_fields.py
git commit -m "feat: add task-level memory canary opt-in"
```

## Task 3: Compile baseline and candidate receipts before spawn

**Files:**
- Modify: `bin/memory_canary.py`
- Modify: `bin/project_context.py`
- Modify: `bin/mp`
- Create: `verify/test_memory_canary_runtime.py`
- Modify: `verify/test_project_context.py`
- Modify: `verify/test_taskspec_spawn.py`

- [ ] **Step 1: Write the failing compilation tests**

In `verify/test_memory_canary_runtime.py`, use a real task/profile and injected
recall function to prove:

```python
result = memory_canary.compile_attempt(
    task=canary_task,
    profile=enabled_profile,
    control=enabled_control,
    compile_spec=project_context.compile_task_spec,
    recall=recall,
    now=lambda: 100.0,
)
self.assertEqual(result["candidate"]["memoryStatus"], "ok")
self.assertEqual(result["baseline"]["memoryStatus"], "disabled")
self.assertEqual(result["receipt"]["embeddedClaimCount"], 3)
self.assertEqual(
    result["receipt"]["memoryDeltaCharacters"],
    canonical_chars(result["candidate"]) - canonical_chars(result["baseline"]),
)
self.assertEqual(
    result["receipt"]["memoryDeltaTokensEstimated"],
    (result["receipt"]["memoryDeltaCharacters"] + 3) // 4,
)
```

Add tests proving a non-canary makes zero recall calls, disabled control fails
with `canary_disabled`, wrong project fails with `canary_project_denied`, and
`bypass=True` compiles the local TaskSpec while recording `rolled_back`.

- [ ] **Step 2: Run and verify RED**

```powershell
python -B verify\test_memory_canary_runtime.py -v
```

Expected: FAIL because `compile_attempt` is missing.

- [ ] **Step 3: Implement the compile result and receipt API**

Add these definitions to `memory_canary.py`:

```python
def canonical_char_count(document):
    return len(json.dumps(document, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":")))

def session_alias(backend, session_id):
    clean = str(session_id or "").strip()
    return f"{backend}:{clean[-8:]}" if clean else "unavailable"
```

The remaining public signatures are exactly
`compile_attempt(*, task, profile, control, compile_spec, recall, bypass=False,
now=time.time) -> dict`, `append_receipt(runtime_dir, event) -> None`, and
`latest_receipt(runtime_dir, task_id) -> dict | None`.

The baseline must be compiled from a deep copy of the profile with only
`memory.enabled=False`. Candidate compilation receives the same task, clock,
and local fields. `append_receipt` writes one bounded JSON line to
`run/memory-canary-events.jsonl`, rejects claim/question content recursively,
and fsyncs before returning.

- [ ] **Step 4: Connect the owner-spawn preflight**

Change `compile_owner_task_spec(task_id, *, bypass_memory=False)` so it:

1. loads the control for `memoryCanary=true`;
2. calls `compile_attempt`;
3. writes only the candidate or bypass TaskSpec;
4. appends the start receipt before the first tmux/process operation;
5. raises a typed `TaskSpecError` without writing a TaskSpec on failure.

Add `--without-memory` to `mp spawn`, valid only with `--owner-task`. It must
not clear the card's opt-in Boolean; it records an explicit bypass attempt.

- [ ] **Step 5: Verify compiler and spawn ordering GREEN**

```powershell
python -B verify\test_memory_canary_runtime.py -v
python -B verify\test_project_context.py -v
python -B verify\test_taskspec_spawn.py -v
git diff --check
git add bin/memory_canary.py bin/project_context.py bin/mp verify/test_memory_canary_runtime.py verify/test_project_context.py verify/test_taskspec_spawn.py
git commit -m "feat: compile measured memory canary attempts"
```

## Task 4: Attribute model, session, outcome, and provider tokens honestly

**Files:**
- Modify: `bin/memory_canary.py`
- Modify: `bin/mp`
- Create: `verify/test_memory_canary_telemetry.py`
- Modify: `bin/todo-server.py`

- [ ] **Step 1: Write failing telemetry tests**

Create transcript fixtures containing one provider usage event before the
attempt and one after it. Assert:

```python
usage = memory_canary.provider_usage_delta(before, after)
self.assertEqual(usage, {"inputTokens": 120, "outputTokens": 30})
self.assertEqual(memory_canary.provider_usage_delta({}, {}), "not_measured")
self.assertEqual(memory_canary.session_alias("codex", "session-1234567890"),
                 "codex:34567890")
```

Malformed, decreasing, cross-session, or provider-unattributable counters must
return `not_measured`, never zero.

- [ ] **Step 2: Run and verify RED**

```powershell
python -B verify\test_memory_canary_telemetry.py -v
```

- [ ] **Step 3: Implement bounded telemetry extraction**

Implement `provider_usage_delta(before, after)` only for validated numeric
provider-emitted counters. Add `complete_attempt(runtime_dir, *, attempt_id,
task_id, runtime_record, outcome, evidence_count, usage_before, usage_after,
completed_at) -> dict` that appends a second event with attempt ID, model,
provider profile, session alias, duration,
outcome, evidence count, retries, and usage or `not_measured`.

Hook the initial agent-session capture to the attempt without reading or
copying transcript content into receipts. Hook `mp complete` and task closure
to append completion metadata for the owning canary task.

- [ ] **Step 4: Expose a private status projection**

Add `/todo/memory-canary?task_id=<id>` for authenticated local requests. Return
only the latest joined start/completion receipt and global gate metadata. Never
include raw question, claim content, transcript path, or full session ID.

- [ ] **Step 5: Verify GREEN and commit**

```powershell
python -B verify\test_memory_canary_telemetry.py -v
python -B verify\test_agent_session.py -v
python -B verify\test_task_evidence.py -v
git diff --check
git add bin/memory_canary.py bin/mp bin/todo-server.py verify/test_memory_canary_telemetry.py
git commit -m "feat: record honest memory canary telemetry"
```

## Task 5: Add the local read-only sidecar and bounded Windows activation

**Files:**
- Modify: `experiments/memory-gate-b/docker/taskspec-memory-server.mjs`
- Create: `experiments/memory-gate-b/docker/live-canary-entrypoint.sh`
- Create: `experiments/memory-gate-b/docker/compose.live-canary.yml`
- Modify: `bin/project_context.py`
- Modify: `memory-gateway/memory-gateway.mjs`
- Create: `windows/Start-MyPeopleMemoryCanary.ps1`
- Create: `verify/test_memory_canary_sidecar.py`
- Create: `verify/test_windows_memory_canary.py`

- [ ] **Step 1: Write failing static and launcher contracts**

Assert the Compose service has `read_only: true`, `cap_drop: [ALL]`,
`no-new-privileges:true`, no published ports, no production volumes, no Docker
socket, a locked dataset mount, and one `internal: true` network. Assert the
PowerShell launcher:

- requires a running healthy `mypeople`;
- generates a random ephemeral bearer;
- writes it through stdin only to `/run/mypeople-secrets/MYPEOPLE_MEMORY_CANARY_TOKEN`;
- connects `mypeople` to the internal network only while enabled;
- waits for sidecar health;
- removes token, disconnects network, and stops sidecar on `-Disable`;
- never prints the bearer.

- [ ] **Step 2: Run and verify RED**

```powershell
python -B verify\test_memory_canary_sidecar.py -v
python -B verify\test_windows_memory_canary.py -v
```

- [ ] **Step 3: Parameterize the existing server safely**

Use environment values with closed defaults:

```javascript
const host = process.env.MYPEOPLE_GATE_B_HOST || '127.0.0.1';
const port = Number(process.env.MYPEOPLE_GATE_B_PORT || '18443');
if (!['127.0.0.1', '0.0.0.0'].includes(host) || !Number.isInteger(port)) {
  throw new Error('gate_b_configuration_invalid');
}
```

The live entrypoint binds `0.0.0.0` only on the internal Docker network and
uses the same locked recall command and server-side bounds.

- [ ] **Step 4: Permit only the exact internal canary URL**

In Python and Node gateway validation, remote URLs remain HTTPS. HTTP is
accepted only when all of these match:

```text
MYPEOPLE_MEMORY_CANARY_URL=http://memory-gate-b:18443/mcp
request.serverUrl == MYPEOPLE_MEMORY_CANARY_URL
request.projectSlug == project-factory
runtime canary control enabled
```

No suffix, alternate port, query, fragment, IP address, or caller-supplied
override is accepted. The gateway still requires the ephemeral bearer.

- [ ] **Step 5: Implement the PowerShell lifecycle**

The script accepts only `-Enable`, `-Disable`, or `-Status`, plus reviewed
deployment/image paths. Use `docker compose` with a unique fixed project name,
`docker network connect/disconnect`, and hidden stdin redirection. Failure
cleanup is in `finally`; it must never restart MyPeople.

- [ ] **Step 6: Verify GREEN and commit**

```powershell
python -B verify\test_memory_canary_sidecar.py -v
python -B verify\test_windows_memory_canary.py -v
npm.cmd test --prefix memory-gateway
python -B verify\test_project_context.py -v
git diff --check
git add experiments/memory-gate-b/docker bin/project_context.py memory-gateway windows/Start-MyPeopleMemoryCanary.ps1 verify/test_memory_canary_sidecar.py verify/test_windows_memory_canary.py
git commit -m "feat: add isolated local memory canary sidecar"
```

## Task 6: Add Priorities status, controls, and assessment

**Files:**
- Modify: `bin/todo-server.py`
- Modify: `bin/todos.html`
- Create: `verify/test_memory_canary_priorities.py`
- Modify: `verify/test_browser_error_filter.js`

- [ ] **Step 1: Write failing API and markup tests**

Test these authenticated operations:

```json
{"op":"run","taskId":"task-1"}
{"op":"retry_without_memory","taskId":"task-1"}
{"op":"disable"}
{"op":"assess","taskId":"task-1","assessment":"useful","rationale":"Verified constraint prevented rework."}
```

Valid assessments are exactly `useful`, `neutral`, `harmful`, and
`not_demonstrated`. Rationale is control-character-cleaned and bounded to 500
characters. Nightwatch and unauthenticated callers cannot mutate canary state.

- [ ] **Step 2: Run and verify RED**

```powershell
python -B verify\test_memory_canary_priorities.py -v
```

- [ ] **Step 3: Implement the endpoints**

Add `POST /todo/memory-canary` with explicit operations. `run` notifies Boss
with one deterministic spawn instruction; `retry_without_memory` uses the same
task ID and explicit CLI flag; `disable` calls the atomic gate module;
`assess` appends the structured completion assessment. No endpoint invokes a
shell command assembled from user input.

- [ ] **Step 4: Render the compact strip**

Render only for `task.memoryCanary === true`. The strip exposes status, 0–3
claim count, retrieval milliseconds, estimated delta, measured provider tokens
or `not measured`, model, shortened session alias, and receipt link. Add buttons
with confirmation for bypass and disable. Use existing Scorpion tokens and no
new icon dependency.

- [ ] **Step 5: Verify GREEN and commit**

```powershell
python -B verify\test_memory_canary_priorities.py -v
python -B verify\test_task_project_fields.py -v
node verify\test_browser_error_filter.js
git diff --check
git add bin/todo-server.py bin/todos.html verify/test_memory_canary_priorities.py verify/test_browser_error_filter.js
git commit -m "feat: expose memory canary controls in Priorities"
```

## Task 7: Prove rollback in disposable Docker and document operation

**Files:**
- Create: `verify/test_memory_canary_e2e.py`
- Modify: `verify/run-suite.sh`
- Modify: `verify/test_public_repository.py`
- Modify: `README.md`
- Modify: `docs/USER-MANUAL.md`

- [ ] **Step 1: Write the failing E2E registration contract**

Add a fast root test proving the suite registers the new focused contracts and
the live canary is never invoked by install, normal startup, or the default
Compose deployment.

- [ ] **Step 2: Run and verify RED**

```powershell
python -B verify\test_public_repository.py -v
```

- [ ] **Step 3: Implement the disposable E2E**

The E2E creates only synthetic cards and proves:

1. positive Project Factory canary embeds at most three grounded claims;
2. non-canary task makes zero gateway calls;
3. cross-project task fails before recall;
4. timeout creates no worker or TaskSpec;
5. bypass recompiles the same card without claims;
6. disable takes effect without restart;
7. receipt contains measured/estimated distinctions and no content/secrets;
8. sidecar/network/token cleanup succeeds.

- [ ] **Step 4: Document exact operator commands**

Document enable, status, card opt-in, run, assessment, bypass, disable, and
cleanup. State that the dataset is public, the shared `mp` identity is not a
private-memory boundary, Cloudflare is not active, and one canary is not
statistical proof.

- [ ] **Step 5: Run focused verification and commit**

```powershell
python -B verify\test_memory_canary_control.py -v
python -B verify\test_memory_canary_runtime.py -v
python -B verify\test_memory_canary_telemetry.py -v
python -B verify\test_memory_canary_sidecar.py -v
python -B verify\test_windows_memory_canary.py -v
python -B verify\test_memory_canary_priorities.py -v
python -B verify\test_memory_canary_e2e.py -v
python -B verify\test_public_repository.py -v
git diff --check
git add verify README.md docs/USER-MANUAL.md
git commit -m "docs: verify active memory Gate B canary"
```

## Task 8: Full isolation, one live canary, rollback, and publication

**Files:**
- Create after execution: `experiments/memory-gate-b/artifacts/live-canary-receipt.json`
- Create after execution: `experiments/memory-gate-b/artifacts/live-canary-report.md`
- Modify: `experiments/memory-gate-b/README.md`

- [ ] **Step 1: Build the exact candidate image**

```powershell
$sha = (git rev-parse --short=12 HEAD).Trim()
$candidateImage = "project-factory-memory-canary:$sha"
docker build --tag $candidateImage .
docker image inspect $candidateImage --format '{{.Id}}'
```

Expected: build exit 0 and one immutable local image ID.

- [ ] **Step 2: Run the complete isolated verifier**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File verify\Invoke-IsolatedVerify.ps1 -Image $candidateImage -TimeoutSeconds 1800
```

Expected: exit 0. Record `$candidateImage` and its inspected image ID in the
private execution receipt.

- [ ] **Step 3: Preflight the live runtime**

Record container image, start time, restart count, health, Boss/Nightwatch
roster, active owner tasks, and provider-session bindings. Stop if user-owned
work is active or if any health check is already failing.

- [ ] **Step 4: Upgrade through the existing transactional launcher**

Run the repository's reviewed image-upgrade path against the clean committed
candidate:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File windows\Upgrade-MyPeopleDockerImage.ps1 -CandidateImage $candidateImage
```

Expected: the launcher preserves board and stable-roster hashes, rehydrates
provider sessions, records rollback evidence, and returns exit 0. If it fails,
stop and use its own rollback evidence; do not copy files into the live
container manually.

- [ ] **Step 5: Back up only changed runtime paths and durable metadata**

Create a timestamped backup under `C:\tmp` containing hashes and the files that
will be replaced. Do not copy provider credentials, transcripts, recordings,
or private TaskSpec contents into Git.

- [ ] **Step 6: Activate the local sidecar and one synthetic card**

Use `Start-MyPeopleMemoryCanary.ps1 -Enable`, enable the runtime gate, create
one `test=true`, `memoryCanary=true` Project Factory card, and dispatch exactly
one Codex owner through the normal Boss path. Do not reuse an existing task.

- [ ] **Step 7: Assess and roll back**

Verify the task evidence, record one structured utility assessment, disable the
gate, stop the sidecar, remove only the synthetic card/resources, and prove
Boss, Nightwatch, queue, HUD, terminals, sessions, and restart count are
unchanged.

- [ ] **Step 8: Sanitize and commit evidence**

Public artifacts contain the task-independent metric summary, exact software
SHAs, typed outcomes, and pseudonymized session alias. They contain no raw
question, claims, local paths, account identity, or credential material.

```powershell
python -B verify\test_public_repository.py -v
git diff --check
git status --short --branch
git add experiments/memory-gate-b/artifacts experiments/memory-gate-b/README.md
git commit -m "test: record active memory Gate B canary"
```

- [ ] **Step 9: Publish as a dependent draft PR**

Push `feat/memory-gate-b-live-canary` and open a draft PR against
`feat/memory-gate-b-experiment` while PR 10 is unmerged. After PR 10 merges,
retarget the canary PR to `main` and verify the diff contains only this phase.

The PR body must report focused tests, full isolated verifier, live health,
rollback evidence, actual tokens only when measured, and the explicit
single-canary limitation.
