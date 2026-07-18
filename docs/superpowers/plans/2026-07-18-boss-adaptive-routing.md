# Boss Adaptive Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route each new owner task to the least expensive policy-compliant Codex model using deterministic local rules and auditable budget ceilings.

**Architecture:** Add a pure `task_routing.py` policy engine, compile optional routing hints into TaskSpec, and integrate routing only into fresh owner-worker spawn. Persist canonical decision receipts atomically, bind them to roster records by SHA-256, post one idempotent task comment, and expose a non-mutating one-tier escalation calculation.

**Tech Stack:** Python 3 standard library, MyPeople `mp` CLI, JSON runtime contracts, `unittest`, Docker isolated verifier, PowerShell backup-first image upgrade.

**Execution choice:** The operator approved inline execution.

---

## File Map

- Create `bin/task_routing.py`: policy validation, classification, manual-model validation, canonical receipts, atomic persistence, and bounded next-route calculation.
- Create `verify/test_task_routing.py`: pure unit contracts for policy, bilingual signals, ceilings, determinism, persistence, and escalation.
- Modify `bin/project_context.py`: validate and compile optional task-card `routingHints`.
- Modify `verify/test_project_context.py`: TaskSpec hint validation and size contracts.
- Modify `bin/mp`: resolve/persist owner routes, bind receipts to roster, validate them on revive, and publish an idempotent routing comment.
- Create `verify/test_adaptive_owner_routing.py`: spawn integration and fail-closed mutation-order contracts.
- Create `examples/routing-policy.example.json`: public English default tier and project policy.
- Modify `bin/runtime-supervisor.sh`: seed the private runtime policy once when absent.
- Modify `verify/test_runtime_supervisor.py`: bootstrap policy contract.
- Modify `verify/run-suite.sh`: include both new focused suites.
- Modify `docs/USER-MANUAL.md`: operator behavior, zero-token claim, configuration, and current escalation boundary.

### Task 1: Pure routing policy and deterministic classifier

**Files:**
- Create: `verify/test_task_routing.py`
- Create: `bin/task_routing.py`

- [ ] **Step 1: Write the failing policy/classification tests**

Create fixtures with Luna/Terra/Sol tiers and assert the public API:

```python
POLICY = {
    "schemaVersion": 1,
    "tiers": {
        "economy": {"model": "gpt-5.6-luna", "rank": 1},
        "standard": {"model": "gpt-5.6-terra", "rank": 2},
        "strong": {"model": "gpt-5.6-sol", "rank": 3},
    },
    "defaults": {
        "tier": "economy",
        "maxAutomaticTier": "standard",
        "maxAttempts": 2,
        "maxEscalations": 1,
    },
    "projects": {
        "mypeople": {
            "allowedModels": [
                "gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"
            ],
            "maxAutomaticTier": "strong",
            "maxAttempts": 2,
            "maxEscalations": 1,
        }
    },
}

def spec(objective, **updates):
    value = {
        "schemaVersion": 1,
        "taskId": "task-1",
        "projectSlug": "mypeople",
        "objective": objective,
        "acceptanceCriteria": "",
        "verificationCommands": ["python3 -m unittest"],
        "allowedActions": ["read", "edit", "test"],
        "forbiddenActions": ["deploy", "push", "delete"],
        "evidencePolicy": "optional",
        "routingHints": {},
    }
    value.update(updates)
    return value

def test_simple_and_ambiguous_tasks_choose_economy():
    policy = task_routing.validate_policy(POLICY)
    for text in ("Translate the manual", "Investigate an unclear report"):
        decision = task_routing.route_task(
            spec(text), policy, "codex-primary"
        )
        assert decision["tier"] == "economy"
        assert decision["model"] == "gpt-5.6-luna"
        assert decision["aiUsage"] == "none"

def test_english_and_spanish_implementation_choose_standard():
    policy = task_routing.validate_policy(POLICY)
    for text in ("Fix the Docker API integration", "Corrige el bug de Docker"):
        decision = task_routing.route_task(
            spec(text), policy, "codex-primary"
        )
        assert decision["tier"] == "standard"
        assert "implementation_signal" in decision["reasonCodes"]

def test_critical_signal_uses_strong_only_when_ceiling_allows():
    policy = task_routing.validate_policy(POLICY)
    decision = task_routing.route_task(
        spec("Repair production authentication and prevent data loss"),
        policy,
        "codex-primary",
    )
    assert decision["tier"] == "strong"
    capped = spec(
        "Repair production authentication",
        routingHints={"maxTier": "standard"},
    )
    assert task_routing.route_task(
        capped, policy, "codex-primary"
    )["tier"] == "standard"

def test_manual_model_is_validated_without_substitution():
    policy = task_routing.validate_policy(POLICY)
    decision = task_routing.route_task(
        spec("Fix API integration"),
        policy,
        "codex-primary",
        requested_model="gpt-5.6-terra",
    )
    assert decision["selection"] == "manual"
    with pytest_raises_code("routing_model_denied"):
        task_routing.route_task(
            spec("Translate docs"),
            policy,
            "codex-primary",
            requested_model="unlisted-model",
        )
```

Use a local context-manager helper instead of adding pytest:

```python
@contextlib.contextmanager
def pytest_raises_code(code):
    try:
        yield
    except task_routing.RoutingError as error:
        assert error.code == code
    else:
        raise AssertionError(f"expected {code}")
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
python -B verify\test_task_routing.py
```

Expected: import/load failure because `bin/task_routing.py` does not exist.

- [ ] **Step 3: Implement the minimal pure engine**

Implement `RoutingError(code)` with a public `code` attribute and these
public API contracts: `validate_policy(value: dict) -> dict`,
`route_task(task_spec, policy, provider_profile, requested_model=None) -> dict`,
`next_route(decision, failure, policy) -> dict`,
`canonical_decision_bytes(decision) -> bytes`, and
`write_decision(root, decision) -> tuple[str, str]`. Each validation failure
raises `RoutingError` with one of the typed codes in the design.

Use fixed signal sets and deterministic reason-code ordering:

```python
SIMPLE = {
    "document", "documentation", "explain", "format", "translate",
    "documentar", "explicar", "formato", "traducir", "revision",
}
IMPLEMENTATION = {
    "implement", "fix", "bug", "refactor", "api", "database", "docker",
    "integration", "implementar", "corregir", "refactorizar", "base de datos",
    "integracion",
}
CRITICAL = {
    "security", "authentication", "secret", "production", "deploy",
    "payment", "data loss", "rollback", "architecture",
    "seguridad", "autenticacion", "secreto", "produccion", "desplegar",
    "pago", "perdida de datos", "reversion", "arquitectura",
}
```

Normalize with Unicode NFKD, remove combining marks, lowercase, and collapse
non-alphanumeric separators. Critical signal wins over implementation;
implementation wins over simple; ambiguous input uses the configured default.
Apply task `maxTier` and project `maxAutomaticTier` after classification.

Reject unknown fields, invalid schemas, duplicate/non-monotonic ranks, unknown
project slugs, models outside `allowedModels`, invalid hints, negative budgets,
and tier/model mismatches with typed `RoutingError` codes.

- [ ] **Step 4: Run GREEN and add validation edge cases**

Run:

```powershell
python -B verify\test_task_routing.py
```

Expected: all routing tests pass. Add table-driven cases proving malformed
policies return `routing_policy_invalid` and missing projects return
`routing_project_missing`, then rerun.

- [ ] **Step 5: Commit**

```powershell
git add bin/task_routing.py verify/test_task_routing.py
git commit -m "feat: add deterministic task routing engine"
```

### Task 2: TaskSpec routing hints

**Files:**
- Modify: `bin/project_context.py`
- Modify: `verify/test_project_context.py`

- [ ] **Step 1: Write failing TaskSpec hint tests**

```python
def test_task_spec_compiles_valid_routing_hints(self):
    result = project_context.compile_task_spec(
        self.task(routingHints={
            "taskClass": "implementation",
            "risk": "medium",
            "maxTier": "standard",
        }),
        profile(),
    )
    self.assertEqual(result["routingHints"], {
        "taskClass": "implementation",
        "risk": "medium",
        "maxTier": "standard",
    })

def test_task_spec_rejects_invalid_routing_hints(self):
    invalid = [
        "strong",
        {"unknown": "value"},
        {"taskClass": "large"},
        {"risk": "extreme"},
        {"maxTier": "premium"},
    ]
    for hints in invalid:
        with self.subTest(hints=hints), self.assertRaisesRegex(
            project_context.TaskSpecError, "invalid_routing_hints"
        ):
            project_context.compile_task_spec(
                self.task(routingHints=hints), profile()
            )
```

- [ ] **Step 2: Run RED**

Run `python -B verify\test_project_context.py`.
Expected: valid hints are absent from the compiled TaskSpec.

- [ ] **Step 3: Implement strict hint validation**

Add `_routing_hints(value)` that accepts only the three fields and enumerated
values in the approved design. Add
`"routingHints": _routing_hints(task.get("routingHints"))` to the canonical
TaskSpec before size validation.

- [ ] **Step 4: Run GREEN and commit**

```powershell
python -B verify\test_project_context.py
git add bin/project_context.py verify/test_project_context.py
git commit -m "feat: compile bounded task routing hints"
```

### Task 3: Canonical routing receipts and bounded escalation

**Files:**
- Modify: `verify/test_task_routing.py`
- Modify: `bin/task_routing.py`

- [ ] **Step 1: Write failing persistence and escalation tests**

```python
def test_receipt_is_deterministic_private_and_secret_free():
    policy = task_routing.validate_policy(POLICY)
    decision = task_routing.route_task(
        spec("Fix Docker integration"), policy, "codex-primary"
    )
    with tempfile.TemporaryDirectory() as temp:
        first_path, first_hash = task_routing.write_decision(temp, decision)
        second_path, second_hash = task_routing.write_decision(temp, decision)
        assert first_path == second_path
        assert first_hash == second_hash
        assert stat.S_IMODE(os.stat(first_path).st_mode) == 0o600
        body = Path(first_path).read_text(encoding="utf-8")
        assert "session_id" not in body
        assert "token" not in body.lower()

def test_next_route_advances_once_and_respects_budget():
    policy = task_routing.validate_policy(POLICY)
    decision = task_routing.route_task(
        spec("Fix Docker integration"), policy, "codex-primary"
    )
    escalated = task_routing.next_route(
        decision, "verification_failed", policy
    )
    assert escalated["tier"] == "strong"
    assert escalated["model"] == "gpt-5.6-sol"
    assert escalated["escalationCount"] == 1
    with pytest_raises_code("routing_budget_exhausted"):
        task_routing.next_route(
            escalated, "verification_failed", policy
        )

def test_infrastructure_and_provider_failures_never_escalate_model():
    policy = task_routing.validate_policy(POLICY)
    decision = task_routing.route_task(
        spec("Fix Docker integration"), policy, "codex-primary"
    )
    for failure in ("provider_exhausted", "authentication_failed",
                    "infrastructure_failed", "context_missing"):
        with pytest_raises_code("routing_failure_not_escalatable"):
            task_routing.next_route(decision, failure, policy)
```

- [ ] **Step 2: Run RED**

Run `python -B verify\test_task_routing.py`.
Expected: persistence/escalation assertions fail because the behavior is absent.

- [ ] **Step 3: Implement atomic receipts and one-tier next-route**

Serialize with sorted keys and compact separators. Write a same-directory
private temporary file, flush, `fsync`, `chmod 0600`, then `os.replace`.
Return the absolute path and SHA-256. Remove the temporary file on every error.

Allow only `verification_failed`, `implementation_blocked`, and
`model_capability_insufficient`. Increment `attemptCount` and
`escalationCount`, advance exactly one rank, and rerun project/task ceiling
and allowlist checks. Do not call tmux or provider code.

- [ ] **Step 4: Run GREEN and commit**

```powershell
python -B verify\test_task_routing.py
git add bin/task_routing.py verify/test_task_routing.py
git commit -m "feat: persist bounded routing decisions"
```

### Task 4: Fresh owner-spawn integration

**Files:**
- Create: `verify/test_adaptive_owner_routing.py`
- Modify: `bin/mp`

- [ ] **Step 1: Write failing integration tests**

Load `bin/mp` with `SourceFileLoader`, mock only network/tmux boundaries,
and assert:

```python
def test_fresh_owner_spawn_uses_automatic_route_and_receipt(self):
    ns = owner_namespace(model=None)
    mp.compile_owner_task_spec = lambda _task: self.taskspec_path
    mp.resolve_provider_runtime = lambda *args: (
        args[4], "codex-primary", self.provider_home
    )
    mp.load_routing_policy = lambda _path=None: self.policy
    mp.window_exists = lambda _target: False
    mp.run_tmux = self.capture_tmux
    mp.wait_for_composer = lambda *_args, **_kwargs: False
    mp.load_roster = lambda: []
    mp.update_roster = self.records.append
    mp.queue_register = lambda _rec: None
    mp.recorder = lambda *_args: None
    mp.ensure_routing_comment = self.comments.append

    mp.spawn(ns)

    record = self.records[-1]
    self.assertEqual(record["routing_tier"], "standard")
    self.assertEqual(record["model"], "gpt-5.6-terra")
    self.assertRegex(record["routing_sha256"], r"^[0-9a-f]{64}$")
    self.assertTrue(Path(record["routing_path"]).is_file())

def test_policy_denial_precedes_tmux_and_roster_mutation(self):
    ns = owner_namespace(model="unlisted-model")
    with self.assertRaisesRegex(SystemExit, "routing_model_denied"):
        mp.spawn(ns)
    self.assertEqual(self.tmux_calls, [])
    self.assertEqual(self.records, [])

def test_revive_reuses_and_validates_original_route(self):
    mp.validate_record_receipt(
        self.record,
        "routing_path",
        "routing_sha256",
        "routing_receipt_mismatch",
    )
    self.assertEqual(self.record["model"], "gpt-5.6-terra")
```

Also assert an explicit allowed model records `selection=manual`, temporary
workers do not load routing policy, and routing comments use a marker based on
the receipt hash.

- [ ] **Step 2: Run RED**

Run `python -B verify\test_adaptive_owner_routing.py`.
Expected: routing fields/functions are absent.

- [ ] **Step 3: Integrate routing before any process mutation**

Import the routing functions. Add `document` to
`resolve_owner_task_context`. Resolve Codex provider identity for a fresh
owner worker with `model_explicit=True` so provider role defaults cannot
preempt routing. Load policy, call `route_task`, persist it, then pass the
selected model through the existing launch flow.

Add these roster fields:

```python
{
    "routing_path": routing_path,
    "routing_sha256": routing_sha256,
    "routing_tier": decision["tier"],
    "routing_selection": decision["selection"],
    "routing_reason_codes": decision["reasonCodes"],
    "routing_max_attempts": decision["maxAttempts"],
    "routing_max_escalations": decision["maxEscalations"],
}
```

For revive, validate the existing receipt and reuse the recorded model without
reclassification. Map `RoutingError.code` to a sanitized `SystemExit` before
tmux creation or roster mutation.

- [ ] **Step 4: Implement idempotent task comment**

Render:

```text
[routing:{routing_sha256[:12]}] class=implementation risk=medium tier=standard model=gpt-5.6-terra selection=automatic reasons=implementation_signal,project_policy_allowed aiUsage=none
```

Fetch the board and skip posting when the marker already exists. Comment failure
prints a warning and does not invalidate an otherwise persisted route; the
receipt and roster remain authoritative.

- [ ] **Step 5: Run GREEN and regression suites**

```powershell
python -B verify\test_adaptive_owner_routing.py
python -B verify\test_taskspec_spawn.py
python -B verify\test_codex_boss_switch.py
python -B verify\test_exact_session_recovery.py
```

Expected: all pass.

- [ ] **Step 6: Commit**

```powershell
git add bin/mp verify/test_adaptive_owner_routing.py
git commit -m "feat: route fresh owner workers by policy"
```

### Task 5: Runtime bootstrap and public example

**Files:**
- Create: `examples/routing-policy.example.json`
- Modify: `bin/runtime-supervisor.sh`
- Modify: `verify/test_runtime_supervisor.py`

- [ ] **Step 1: Write the failing supervisor contract**

Add a static/runtime fixture asserting that supervisor creates
`run/routing-policy.json` from the bundled example only when absent, uses a
same-directory temporary file plus atomic rename, and applies mode `0600`.
Run:

```powershell
python -B verify\test_runtime_supervisor.py
```

Expected: FAIL because no routing policy bootstrap exists.

- [ ] **Step 2: Add the public example**

Write the exact Luna/Terra/Sol policy from the approved design, using project
slug `mypeople`, maximum automatic tier `strong`, two attempts, and one
escalation. Keep all text and keys in English and include no credentials.

- [ ] **Step 3: Seed runtime policy once**

Before services start, create `run/routing-decisions` with mode `0700`.
When `run/routing-policy.json` is absent, copy the bundled example to a
temporary file, set `0600`, and atomically rename it. Never overwrite an
existing operator policy.

- [ ] **Step 4: Run GREEN and commit**

```powershell
python -B verify\test_runtime_supervisor.py
git add examples/routing-policy.example.json bin/runtime-supervisor.sh verify/test_runtime_supervisor.py
git commit -m "feat: bootstrap private routing policy"
```

### Task 6: Documentation and verifier registration

**Files:**
- Modify: `verify/run-suite.sh`
- Modify: `docs/USER-MANUAL.md`
- Modify: `README.md`

- [ ] **Step 1: Add focused suites to the isolated verifier**

Insert after TaskSpec tests:

```bash
python3 "$VERIFY/test_task_routing.py"
python3 "$VERIFY/test_adaptive_owner_routing.py"
```

- [ ] **Step 2: Document the operator contract**

Document:

- owner tasks without `--model` use deterministic routing;
- Luna is economy, Terra standard, and Sol strong in the default example;
- classification makes no provider call and records `aiUsage: none`;
- manual `--model` remains policy-gated;
- policy path and environment override;
- exact revive preserves the original decision;
- this phase calculates bounded escalation but does not kill/switch a worker;
- HUD/provider hybrid controls remain future work.

- [ ] **Step 3: Run public-repository and focused tests**

```powershell
python -B verify\test_public_repository.py
python -B verify\test_task_routing.py
python -B verify\test_adaptive_owner_routing.py
```

Expected: all pass and public content remains English.

- [ ] **Step 4: Commit**

```powershell
git add verify/run-suite.sh docs/USER-MANUAL.md README.md
git commit -m "docs: explain adaptive boss routing"
```

### Task 7: Full verification, review, Docker canary, and publication

**Files:**
- Modify only when a failing test proves a defect in files already listed.

- [ ] **Step 1: Run the focused matrix**

```powershell
python -B verify\test_task_routing.py
python -B verify\test_project_context.py
python -B verify\test_adaptive_owner_routing.py
python -B verify\test_taskspec_spawn.py
python -B verify\test_provider_profiles.py
python -B verify\test_worker_handoff.py
python -B verify\test_exact_session_recovery.py
python -B verify\test_runtime_supervisor.py
python -B verify\test_public_repository.py
```

Expected: every suite passes.

- [ ] **Step 2: Build and run the packaged isolated verifier**

Build a candidate image from the exact branch HEAD using
`docker/Dockerfile.runtime-image`. Run the repository's isolated verification
entrypoint with `MP_VERIFY_ISOLATED=1`. Expected: new routing suites and
contracts J1-J52 pass without network downloads.

- [ ] **Step 3: Perform independent code review**

Review the diff from `origin/main` for security, fail-closed ordering, secret
exposure, exact-session compatibility, and missing tests. Fix only findings
reproduced by a RED test, then rerun the focused and packaged suites.

- [ ] **Step 4: Upgrade live Docker transactionally**

Use `windows/Upgrade-MyPeopleDockerImage.ps1` so named volumes, board SHA, and
stable roster SHA are backed up and compared. Require transaction
`stage=complete` and `rollbackAttempted=false`.

- [ ] **Step 5: Run a disposable live routing canary**

Create a temporary owner task with a bounded implementation objective, spawn a
temporary named engineer through owner routing, and verify:

- model is Terra for implementation;
- routing receipt exists and hash matches roster;
- task contains one routing marker comment;
- provider session capture succeeds;
- deliberate stop and exact revive preserve tier/model/receipt;
- canary task, agent, tmux window, and proof artifacts are removed.

Do not expose provider session IDs or credentials in the evidence.

- [ ] **Step 6: Verify Windows launcher**

Run the installed launcher with `-NoBrowser -NonInteractive` and require
`READY http://localhost:9933/`, Boss alive, Nightwatch alive, provider gate
unpaused, and localhost-only ports.

- [ ] **Step 7: Publish**

```powershell
git status --short
git push -u origin feat/boss-adaptive-routing
gh pr create --repo LordCripto-Hub/Project-Factory --base main --head feat/boss-adaptive-routing --title "Add deterministic Boss model routing" --body "Adds zero-token deterministic owner-task routing, policy ceilings, canonical receipts, bounded escalation calculation, focused tests, packaged verification, and live Docker canary evidence."
```

Verify the PR head equals local HEAD and merge only after all checks and live
evidence pass. Record the PR, commits, image, transaction, and remaining HUD /
hybrid-provider work in the canonical MyPeople Roadmap OS item without storing
credentials or session identifiers.
