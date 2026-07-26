# Lossless Routing Escalation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn an explicit eligible worker failure into a bounded transaction that resumes the same Codex session, agent, and task on exactly one higher policy-compliant model and then submits one compact continuation message.

**Architecture:** Keep request validation, private records, immutable receipt history, and transaction state in a focused `routing_escalation.py` module. Reuse extracted provider lock and handoff primitives, while `bin/mp` owns live roster/tmux/exact-resume orchestration and `queue-client.py` owns asynchronous worker-triggered delivery. The existing routing engine remains the only tier/budget authority.

**Tech Stack:** Python 3 standard library, tmux, Codex CLI exact resume, JSON receipts, MyPeople queue/Priorities HTTP contracts, Docker isolated verifier, PowerShell backup-first image upgrade.

---

## File Map

- Create `bin/provider_handoff.py`: shared redaction and bounded handoff construction.
- Create `bin/provider_transaction.py`: shared provider/model mutation lock.
- Create `bin/routing_escalation.py`: closed request schema, private records, transaction states, and immutable routing-history receipts.
- Modify `bin/provider-session`: import shared primitives without changing provider-switch behavior.
- Modify `bin/mp`: add worker/Boss commands and exact-session forward/rollback orchestration.
- Modify `bin/queue-client.py`: deliver opaque request IDs outside the worker.
- Create focused tests for primitives, requests, CLI, queue, forward resume, rollback, and recovery-required.
- Modify `verify/run-suite.sh`, public docs, and public-repository tests.

### Task 1: Extract Shared Provider Primitives

**Files:**
- Create: `bin/provider_handoff.py`
- Create: `bin/provider_transaction.py`
- Modify: `bin/provider-session:1-180`
- Create: `verify/test_provider_shared_primitives.py`
- Test: `verify/test_provider_session.py`

- [ ] **Step 1: Write failing shared-primitive tests**

```python
class ProviderSharedPrimitiveContract(unittest.TestCase):
    def test_handoff_is_bounded_and_redacts_secret_material(self):
        record = {
            "agent_id": "node-1/main:Worker-1",
            "backend": "codex",
            "model": "gpt-5.6-luna",
            "owner_task_id": "task-1",
            "session_id": "must-not-leak",
        }
        handoff = provider_handoff.build_handoff(
            record, "OPENAI_API_KEY=secret\nwork completed"
        )
        rendered = json.dumps(handoff)
        self.assertNotIn("secret", rendered)
        self.assertNotIn("must-not-leak", rendered)
        self.assertLessEqual(len(handoff["terminalTail"]), 4000)

    def test_provider_lock_is_owned_and_exclusive(self):
        provider_transaction.acquire_lock(self.lock_path, "tx-one")
        with self.assertRaises(provider_transaction.SwitchBusy):
            provider_transaction.acquire_lock(self.lock_path, "tx-two")
        provider_transaction.release_lock(self.lock_path, "tx-two")
        self.assertTrue(Path(self.lock_path).exists())
        provider_transaction.release_lock(self.lock_path, "tx-one")
        self.assertFalse(Path(self.lock_path).exists())
```

- [ ] **Step 2: Run RED**

```powershell
$repo=(Get-Location).Path
docker run --rm -v "${repo}:/repo:ro" -w /repo -e PYTHONPATH=/repo/bin mypeople-node:routing-c0c6a36 python3 verify/test_provider_shared_primitives.py
```

Expected: import failure for `provider_handoff` or
`provider_transaction`.

- [ ] **Step 3: Create the shared modules**

Move the current `PUBLIC_HANDOFF_FIELDS`, `redact`,
`sanitize_terminal_tail`, and `build_handoff` definitions byte-for-byte
from `provider-session` into `provider_handoff.py`. Export:

```python
__all__ = [
    "PUBLIC_HANDOFF_FIELDS",
    "build_handoff",
    "redact",
    "sanitize_terminal_tail",
]
```

Move the current `SwitchBusy`, `_private_dir`, `acquire_lock`, and
`release_lock` definitions byte-for-byte into `provider_transaction.py`.
Export:

```python
__all__ = ["SwitchBusy", "acquire_lock", "release_lock"]
```

`provider-session` imports the names:

```python
from provider_handoff import (
    PUBLIC_HANDOFF_FIELDS, build_handoff, redact, sanitize_terminal_tail,
)
from provider_transaction import SwitchBusy, acquire_lock, release_lock
```

Delete only the duplicated definitions. Do not change regexes, modes, lock
ownership, provider selection, or rollback behavior.

- [ ] **Step 4: Run GREEN plus provider-switch regression**

Run the new test and `verify/test_provider_session.py) inside Linux.
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add bin/provider_handoff.py bin/provider_transaction.py bin/provider-session verify/test_provider_shared_primitives.py
git commit -m "refactor: share provider transaction primitives"
```

### Task 2: Add Closed Requests And Immutable Receipt History

**Files:**
- Create: `bin/routing_escalation.py`
- Create: `verify/test_routing_escalation.py`
- Test: `verify/test_task_routing.py`

- [ ] **Step 1: Write RED schema, permission, and history tests**

```python
def test_worker_request_is_private_closed_and_queue_safe(self):
    path, request = escalation.create_request(
        self.root,
        request_id="a" * 32,
        agent_id="node-1/main:Worker-1",
        task_id="task-1",
        boss_id="node-1/main:Boss",
        requested_by="node-1/main:Worker-1",
        actor_class="worker",
        failure="verification_failed",
        summary="Verifier still fails.",
        proofs=["python3 verify/example.py: 1 failed"],
        routing_sha256="b" * 64,
        now=10.0,
    )
    self.assertEqual(set(request), escalation.REQUEST_FIELDS)
    self.assertEqual(stat.S_IMODE(Path(path).stat().st_mode), 0o600)
    self.assertNotIn("session", json.dumps(request).lower())

def test_request_rejects_ineligible_or_sensitive_input(self):
    for failure in ("provider_exhausted", "timeout", "crash"):
        with self.assertRaisesRegex(
            escalation.EscalationError,
            "routing_failure_not_escalatable",
        ):
            self.make_request(failure=failure)
    with self.assertRaisesRegex(
        escalation.EscalationError, "escalation_request_invalid"
    ):
        self.make_request(summary="x" * 2001)
    with self.assertRaisesRegex(
        escalation.EscalationError, "escalation_request_invalid"
    ):
        self.make_request(proofs=["OPENAI_API_KEY=secret"])

def test_versioned_receipts_preserve_prior_attempt(self):
    first_path, first_hash = escalation.write_history_decision(
        self.history, self.initial_decision
    )
    second = task_routing.next_route(
        self.initial_decision, "verification_failed", self.policy
    )
    second_path, second_hash = escalation.write_history_decision(
        self.history, second
    )
    self.assertNotEqual(first_path, second_path)
    self.assertNotEqual(first_hash, second_hash)
    self.assertTrue(Path(first_path).is_file())
    self.assertTrue(Path(second_path).is_file())
```

- [ ] **Step 2: Run RED**

Expected: `ModuleNotFoundError: routing_escalation`.

- [ ] **Step 3: Implement the pure module**

```python
ELIGIBLE_FAILURES = frozenset({
    "verification_failed",
    "implementation_blocked",
    "model_capability_insufficient",
})
REQUEST_FIELDS = frozenset({
    "schemaVersion", "requestId", "agentId", "taskId", "bossId",
    "requestedBy", "actorClass", "failure", "summary", "proofs",
    "routingSha256", "createdAt", "state",
})
TERMINAL_STATES = frozenset({
    "committed", "rolled_back", "recovery_required",
})

class EscalationError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)
```

Expose `create_request(root, *, request_id, agent_id, task_id, boss_id,
requested_by, actor_class, failure, summary, proofs, routing_sha256, now=None)`
returning `tuple[str, dict]`; `load_request(root, request_id)`;
`write_request_state(root, request, state)`; `transaction_paths(root,
request_id)`; `write_transaction_state(root, request_id, phase, **fields)`;
`load_transaction_state(root, request_id)`; and
`write_history_decision(root, decision)` returning `tuple[str, str]`.

All identifiers, fields, transitions, bounds, and sensitive fragments are
validated before mutation. Directories are `0700`; files are atomic `0600`.
`write_history_decision` uses canonical decision bytes and:

```python
target = root / decision["taskId"] / (
    f"attempt-{decision['attemptCount']}-{digest[:12]}.json"
)
```

Existing identical bytes are idempotent. Symlinks, path escapes, non-private
records, conflicting targets, extra fields, and terminal-state rewrites fail
closed.

- [ ] **Step 4: Run GREEN and routing regression**

Run `test_routing_escalation.py` and `test_task_routing.py`.

- [ ] **Step 5: Commit**

```bash
git add bin/routing_escalation.py verify/test_routing_escalation.py
git commit -m "feat: add private escalation records"
```

### Task 3: Add Worker And Boss Request Commands

**Files:**
- Modify: `bin/mp:1-55,1020-1090,1430-1490`
- Create: `verify/test_routing_escalation_cli.py`

- [ ] **Step 1: Write RED command tests**

```python
def test_worker_fail_queues_only_an_opaque_request(self):
    os.environ.update({
        "AGENT_ID": self.worker,
        "OWNER_TASK_ID": "task-1",
        "BOSS_ID": self.boss,
    })
    queued = []
    with self.patch_runtime(queue=queued):
        self.mp.fail(namespace(
            failure="verification_failed",
            summary=["Verifier", "failed"],
            proof=["python3 verify/example.py: 1 failed"],
        ))
    payload = queued[0]
    self.assertEqual(payload["type"], "routing_escalate")
    self.assertEqual(payload["target_agent"], self.worker)
    self.assertEqual(set(payload["payload"]), {"request_id"})
    self.assertNotIn("Verifier", json.dumps(payload))

def test_worker_fail_rejects_reassignment(self):
    self.board["tasks"]["task-1"]["assignee"] = "node-1/main:Other"
    with self.assertRaisesRegex(
        SystemExit, "escalation_actor_unauthorized"
    ):
        self.mp.fail(self.fail_namespace())

def test_boss_or_operator_allowed_but_unrelated_worker_denied(self):
    os.environ["AGENT_ID"] = self.boss
    with self.patch_runtime():
        self.mp.escalate(self.direct_namespace())
    os.environ["AGENT_ID"] = "node-1/main:Other"
    with self.assertRaisesRegex(
        SystemExit, "escalation_actor_unauthorized"
    ):
        self.mp.escalate(self.direct_namespace())
```

- [ ] **Step 2: Run RED**

Expected: `mp` has no `fail` or `escalate` command.

- [ ] **Step 3: Implement validation and request creation**

Add parser contracts:

```python
q = sub.add_parser("fail")
q.add_argument("--failure", required=True, choices=sorted(ELIGIBLE_FAILURES))
q.add_argument("--summary", nargs="+", required=True)
q.add_argument("--proof", action="append", default=[], required=True)
q.set_defaults(fn=fail)

q = sub.add_parser("escalate")
q.add_argument("agent_id")
mode = q.add_mutually_exclusive_group(required=True)
mode.add_argument("--request-id")
mode.add_argument("--failure", choices=sorted(ELIGIBLE_FAILURES))
q.add_argument("--summary", nargs="+")
q.add_argument("--proof", action="append", default=[])
q.set_defaults(fn=escalate)
```

Define one shared subject gate:

```python
def escalation_subject(agent_id):
    aid = full_agent_id(agent_id)
    record = next(
        (row for row in load_roster() if row.get("agent_id") == aid),
        None,
    )
    if (
        not record
        or record.get("backend") != "codex"
        or record.get("lifecycle") != "owner"
        or record.get("state") != "alive"
        or record.get("retired")
        or not record.get("session_id")
        or record.get("resume_state") != "available"
    ):
        raise SystemExit("routing_escalation_subject_invalid")
    verify_owner_task_for_revive(record, aid)
    validate_record_receipt(
        record, "routing_path", "routing_sha256",
        "routing_receipt_mismatch",
    )
    return aid, record
```

`fail(ns)` requires environment-bound actor/task/Boss, validates the live
owner and assigned open task, writes the private request, posts one idempotent
`[escalation-request:<id>]` comment, submits only the request ID through
`/task/submit`, marks the request queued and worker status blocked, and prints
the queue task ID.

`escalate(ns)` accepts the owning Boss, a no-`AGENT_ID` operator, or an
existing internal request. Any other managed actor is rejected before a
request is created.

- [ ] **Step 4: Run GREEN and owner-worker regressions**

Run the new CLI test, `test_worker_handoff.py`,
`test_taskspec_spawn.py`, and `test_adaptive_owner_routing.py`.

- [ ] **Step 5: Commit**

```bash
git add bin/mp verify/test_routing_escalation_cli.py
git commit -m "feat: accept structured worker failures"
```

### Task 4: Deliver Opaque Requests Through The Queue

**Files:**
- Modify: `bin/queue-client.py:55-105`
- Create: `verify/test_queue_routing_escalation.py`

- [ ] **Step 1: Write the RED queue test**

```python
def test_queue_invokes_internal_request_without_sensitive_payload(self):
    task = {
        "type": "routing_escalate",
        "target_agent": "node-1/main:Worker-1",
        "payload": {"request_id": "a" * 32},
    }
    with mock.patch.object(module.subprocess, "run") as run:
        run.return_value = namespace(
            returncode=0, stdout="committed\n", stderr=""
        )
        ok, result = module.execute(task)
    self.assertEqual(run.call_args.args[0][-4:], [
        "escalate", "node-1/main:Worker-1",
        "--request-id", "a" * 32,
    ])
    self.assertTrue(ok)
    self.assertNotIn("summary", json.dumps(task))
```

Add denial tests for missing/extra payload fields, invalid request IDs, and a
missing target agent.

- [ ] **Step 2: Run RED**

Expected: queue action returns `unknown type`.

- [ ] **Step 3: Implement bounded delivery**

```python
if typ == "routing_escalate":
    request_id = p.get("request_id")
    if (
        set(p) != {"request_id"}
        or not isinstance(request_id, str)
        or not request_id
    ):
        return False, "invalid escalation request"
    argv = [
        os.path.join(ROOT, "bin", "mp"),
        "escalate", aid, "--request-id", request_id,
    ]
    result = subprocess.run(
        argv, capture_output=True, text=True, timeout=120
    )
    output = (result.stdout + result.stderr)[-4000:]
    return result.returncode == 0, output
```

Do not add summary, proofs, session IDs, policy bodies, or provider output to
the queue payload.

- [ ] **Step 4: Run GREEN and queue regressions**

Run the new test plus `test_durable_control_queue.py` and
`test_queue_agent_reconciliation.py`.

- [ ] **Step 5: Commit**

```bash
git add bin/queue-client.py verify/test_queue_routing_escalation.py
git commit -m "feat: deliver escalation requests through queue"
```

### Task 5: Implement Exact-Session Forward Escalation

**Files:**
- Modify: `bin/mp:1080-1285`
- Create: `verify/test_lossless_routing_escalation.py`

- [ ] **Step 1: Write RED forward tests**

```python
def test_forward_changes_only_model_and_receipt(self):
    original = self.owner_record(
        model="gpt-5.6-luna", session_id=self.sid
    )
    other = self.other_worker()
    with self.runtime(original, other) as observed:
        result = self.mp.execute_routing_escalation(
            original["agent_id"], self.request()
        )
    current = observed.roster[original["agent_id"]]
    self.assertEqual(result["phase"], "committed")
    self.assertEqual(current["agent_id"], original["agent_id"])
    self.assertEqual(current["session_id"], self.sid)
    self.assertEqual(current["owner_task_id"], "task-1")
    self.assertEqual(current["model"], "gpt-5.6-terra")
    self.assertEqual(observed.roster[other["agent_id"]], other)
    self.assertEqual(observed.killed, [original["agent_id"]])
    self.assertEqual(observed.resume_session, self.sid)

def test_continuation_is_fixed_and_submitted_once_after_verify(self):
    with self.runtime(self.owner_record()) as observed:
        self.mp.execute_routing_escalation(
            observed.owner_id, self.request()
        )
    self.assertEqual(observed.messages, [(
        observed.owner_id,
        self.mp.ROUTING_CONTINUATION_MESSAGE,
    )])
    self.assertLess(len(observed.messages[0][1]), 220)
    self.assertNotIn("terminal", observed.messages[0][1].lower())
    self.assertNotIn("proof", observed.messages[0][1].lower())

def test_duplicate_committed_request_has_no_side_effect(self):
    with self.runtime(
        self.owner_record(), terminal_state="committed"
    ) as observed:
        first = self.mp.execute_routing_escalation(
            observed.owner_id, self.request()
        )
        second = self.mp.execute_routing_escalation(
            observed.owner_id, self.request()
        )
    self.assertEqual(first, second)
    self.assertEqual(observed.killed, [])
    self.assertEqual(observed.messages, [])
```

- [ ] **Step 2: Run RED**

Expected: `execute_routing_escalation` and the continuation constant are
absent.

- [ ] **Step 3: Implement prepare, lock, resume, and verification**

```python
ROUTING_CONTINUATION_MESSAGE = (
    "Continue the same owner task from the preserved session. "
    "Re-run the failed verification and report with mp complete "
    "or one new structured failure."
)
```

Import `next_route`, shared lock/handoff functions, and escalation-record
helpers. Implement the forward skeleton:

```python
def execute_routing_escalation(agent_id, request):
    aid, original = escalation_subject(agent_id)
    prior = validated_routing_decision(original)
    policy = load_routing_policy()
    candidate = next_route(prior, request["failure"], policy)
    model, profile_id, _home = resolve_provider_runtime(
        aid, "codex", False, parse_agent_id(aid)[2],
        candidate["model"], True,
    )
    if (
        model != candidate["model"]
        or profile_id != original.get("provider_profile")
    ):
        raise SystemExit("routing_model_denied")

    prepare_escalation_transaction(
        request, original, prior, candidate,
        build_handoff(original, capture_agent_tail(original)),
    )
    acquire_lock(provider_switch_lock_path(), request["requestId"])
    try:
        original = revalidate_escalation_subject(request)
        candidate_path, candidate_sha = write_history_decision(
            routing_history_root(), candidate
        )
        candidate_record = escalation_candidate_record(
            original, candidate, candidate_path, candidate_sha
        )
        stop_selected_worker_process(original)
        spawn(
            namespace_from_record(candidate_record),
            resume_session=original["session_id"],
            receipt_record=candidate_record,
        )
        verify_forward_escalation(original, candidate_record)
        if not tmux_send_message(
            tmux_target(aid), ROUTING_CONTINUATION_MESSAGE
        ):
            raise RuntimeError("routing_continuation_failed")
        return commit_escalation(
            request, original, candidate_record
        )
    except BaseException as error:
        return rollback_escalation(request, original, error)
    finally:
        release_lock(
            provider_switch_lock_path(), request["requestId"]
        )
```

Required behavior:

- repeat board, assignee, session, receipt, profile, and policy gates after
  acquiring the lock;
- kill only `mc-<session>:<tab>` and `rec-<tab>`, without `mp kill`;
- set only the selected roster record to `switching`;
- call `spawn(namespace_from_record(candidate_record),
  resume_session=original["session_id"], receipt_record=candidate_record)`;
- compare unchanged identity fields and all unrelated roster rows;
- send the continuation only after exact-resume verification;
- commit receipt pointer/counters and idempotent result comment;
- never delete the prior receipt or start a fresh session.

- [ ] **Step 4: Run GREEN and exact-session regressions**

Run the new test plus `test_exact_session_recovery.py`,
`test_task_routing.py`, `test_adaptive_owner_routing.py`, and
`test_provider_session.py`.

- [ ] **Step 5: Commit**

```bash
git add bin/mp verify/test_lossless_routing_escalation.py
git commit -m "feat: resume escalated workers exactly"
```

### Task 6: Implement Rollback And Recovery-Required

**Files:**
- Modify: `bin/mp`
- Modify: `verify/test_lossless_routing_escalation.py`

- [ ] **Step 1: Write RED rollback tests**

```python
def test_forward_failure_restores_prior_exact_worker(self):
    original = self.owner_record(
        model="gpt-5.6-luna", session_id=self.sid
    )
    with self.runtime(
        original, fail_forward_verify=True
    ) as observed:
        result = self.mp.execute_routing_escalation(
            original["agent_id"], self.request()
        )
    current = observed.roster[original["agent_id"]]
    self.assertEqual(result["phase"], "rolled_back")
    self.assertEqual(current["model"], "gpt-5.6-luna")
    self.assertEqual(current["session_id"], self.sid)
    self.assertEqual(
        current["routing_sha256"], original["routing_sha256"]
    )
    self.assertEqual(observed.messages, [])

def test_failed_rollback_preserves_evidence_and_blocks_task(self):
    with self.runtime(
        self.owner_record(),
        fail_forward_verify=True,
        fail_rollback=True,
    ) as observed:
        result = self.mp.execute_routing_escalation(
            observed.owner_id, self.request()
        )
    self.assertEqual(result["phase"], "recovery_required")
    self.assertEqual(observed.task_state, "blocked")
    self.assertEqual(
        observed.roster[observed.owner_id]["recovery_state"],
        "blocked",
    )
    for name in (
        "roster-before.json",
        "routing-before.json",
        "routing-candidate.json",
        "handoff.json",
    ):
        self.assertTrue(observed.transaction_files[name])

def test_stale_request_mutates_nothing(self):
    for mutation in (
        "assignee", "routing_sha", "provider_profile", "session_id"
    ):
        with self.runtime(
            self.owner_record(), stale=mutation
        ) as observed:
            with self.assertRaises(SystemExit):
                self.mp.execute_routing_escalation(
                    observed.owner_id, self.request()
                )
        self.assertEqual(observed.killed, [])
        self.assertEqual(observed.comments, [])
```

- [ ] **Step 2: Run RED**

Expected: old worker is not restored or recovery evidence is missing.

- [ ] **Step 3: Implement deterministic rollback**

`rollback_escalation` writes `rolling_back`, stops a partial candidate
window if present, restores the exact prior roster/receipt, and calls:

```python
spawn(
    namespace_from_record(original),
    resume_session=original["session_id"],
    receipt_record=original,
)
```

After verification, mark `rolled_back`, add one sanitized typed comment, do
not commit candidate counters, and do not send continuation.

If rollback fails, mark `recovery_required`, set only the selected worker
dead with recovery state `blocked`, move the original task to `blocked`,
preserve all transaction evidence, and notify Boss with
`routing_escalation_recovery_required`. Never include a raw exception,
provider output, session ID, policy body, or fresh-session fallback.

- [ ] **Step 4: Run GREEN and recovery regressions**

Run the new test plus `test_exact_session_recovery.py`,
`test_review_resume_revive.py`, and
`test_queue_agent_reconciliation.py`.

- [ ] **Step 5: Commit**

```bash
git add bin/mp verify/test_lossless_routing_escalation.py
git commit -m "feat: roll back failed model escalation"
```

### Task 7: Package Tests And Document The Operator Contract

**Files:**
- Modify: `verify/run-suite.sh:35-55`
- Modify: `verify/test_isolated_verifier.py`
- Modify: `README.md:84-110`
- Modify: `docs/USER-MANUAL.md:165-215`
- Modify: `docs/ADAPTIVE-ROUTING-LIVE-CANARY.md`
- Modify: `verify/test_public_repository.py`

- [ ] **Step 1: Write RED packaging and documentation assertions**

```python
def test_lossless_escalation_is_packaged_and_public(self):
    suite = (ROOT / "verify" / "run-suite.sh").read_text()
    for name in (
        "test_provider_shared_primitives.py",
        "test_routing_escalation.py",
        "test_routing_escalation_cli.py",
        "test_queue_routing_escalation.py",
        "test_lossless_routing_escalation.py",
    ):
        self.assertIn(name, suite)

    for path in (
        ROOT / "README.md",
        ROOT / "docs" / "USER-MANUAL.md",
    ):
        text = path.read_text(encoding="utf-8")
        self.assertIn("mp fail", text)
        self.assertIn("mp escalate", text)
        self.assertIn("same Codex session", text)
        self.assertIn("verification_failed", text)
        self.assertIn("model_capability_insufficient", text)
        self.assertIn("one compact continuation message", text)
        self.assertIn(
            "routing calculation consumes zero model tokens", text
        )
```

- [ ] **Step 2: Run RED**

Expected: new suite names and public command text are absent.

- [ ] **Step 3: Add suite entries and English documentation**

Add every new test to `verify/run-suite.sh` before `core_verify.py`.
Document worker/Boss syntax, eligible failures, excluded provider/auth/
infrastructure/context/timeout/crash cases, same agent/task/session behavior,
one compact continuation turn and its normal token cost, zero-token route
calculation, rollback/recovery-required, no fresh fallback, and canary cleanup.

Keep all public content English and free of personal paths, credentials, raw
provider session IDs, and private runtime values.

- [ ] **Step 4: Run GREEN and sanitation**

Run `test_public_repository.py`, `test_isolated_verifier.py`,
`test_runtime_image_contract.py`, and `git diff --check`.

- [ ] **Step 5: Commit**

```bash
git add verify/run-suite.sh verify/test_isolated_verifier.py README.md docs/USER-MANUAL.md docs/ADAPTIVE-ROUTING-LIVE-CANARY.md verify/test_public_repository.py
git commit -m "docs: explain lossless model escalation"
```

### Task 8: Verify, Upgrade, Canary, And Publish

**Files:**
- Verification only unless a failing test first proves a defect.
- Modify the canary document only when observed safe behavior differs.

- [ ] **Step 1: Run the complete focused Linux matrix**

Run every new test plus routing, TaskSpec, worker handoff, provider profile,
provider transaction, exact recovery, runtime, and public suites in a
credential-free disposable container. Expected: zero failures and exit `0`.

- [ ] **Step 2: Build the committed candidate**

```powershell
$sha=(git rev-parse --short=7 HEAD).Trim()
$base=(docker inspect mypeople --format '{{.Config.Image}}').Trim()
$image="mypeople-node:lossless-escalation-$sha"
docker build -f docker/Dockerfile.runtime-image --build-arg BASE_IMAGE=$base -t $image .
```

Verify packaged and host SHA-256 for `bin/mp`,
`bin/routing_escalation.py`, `bin/provider_handoff.py`, and
`bin/provider_transaction.py`.

- [ ] **Step 3: Run the isolated packaged verifier**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\verify\Invoke-IsolatedVerify.ps1 -Image $image
```

Expected: exit `0`, focused contracts and J1-J52 green, disposable Compose
cleanup complete.

- [ ] **Step 4: Perform the backup-first live upgrade**

Run `windows/Upgrade-MyPeopleDockerImage.ps1` with the candidate. Require a
completed transaction record, exact eight-volume mount contract, preserved
board/stable roster, Priorities/HUD health `200`, provider unpaused, and
Boss/Nightwatch alive. Never use `docker compose down -v`.

- [ ] **Step 5: Execute one controlled Luna-to-Terra canary**

Create an authorized disposable economy task and let Boss start one Luna owner.
Record task/assignee, agent/model/routing hash/profile, a local digest of the
session identity (never the raw ID), Boss/Nightwatch roster, and health.

Inside that worker submit:

```bash
mp fail \
  --failure model_capability_insufficient \
  --summary "Controlled escalation canary requested by the rollout procedure." \
  --proof "No repository mutation was requested; validate exact session and model transition."
```

Verify same agent/task/assignee/session digest, Luna-to-Terra, counters advance
once, both receipts mode `0600`, continuation sent once, one request/result
comment, and Boss/Nightwatch/queue/HUD/Docker remain live. Replay the request
once and prove no extra side effect. Retire only the disposable worker after
review; preserve the card and transaction until rollout review completes.

- [ ] **Step 6: Run the Windows launcher smoke**

Run the installed launcher with `-NoBrowser -NonInteractive`. Expected:
exit `0`, no volume/image/provider mutation, healthy control plane.

- [ ] **Step 7: Request final code review**

Use `requesting-code-review`. Validate every finding against code and tests;
apply each valid defect through a fresh RED/GREEN cycle.

- [ ] **Step 8: Publish through PR**

Run fresh verification, inspect the intended diff, push
`feat/lossless-routing-escalation`, and open an English PR titled:

```text
Add lossless automatic model escalation
```

The PR must distinguish zero-token routing calculation from the one normal
higher-model continuation turn and include packaged/live evidence without
credentials or raw session IDs.
