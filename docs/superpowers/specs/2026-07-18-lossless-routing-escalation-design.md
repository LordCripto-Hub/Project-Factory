# Lossless Routing Escalation Design

**Date:** 2026-07-18

**Status:** Approved

## Purpose

MyPeople already selects an initial Codex model with deterministic local rules
and can calculate exactly one eligible next routing tier. This phase turns that
calculation into a bounded process transaction: an eligible, explicitly typed
worker failure can stop only that worker and resume the same Codex provider
session, agent identity, task, workspace, and receipts with the next permitted
model.

The task remains the source of truth. A model process is replaceable execution
capacity, not the owner of durable task state.

## Goals

- Let a managed owner worker report one structured eligible failure.
- Let its Boss or a local operator request the same transaction explicitly.
- Advance exactly one permitted routing tier.
- Stop and restart only the selected worker process.
- Resume the exact same Codex session under the higher model.
- Deliver exactly one compact fixed continuation message after exact resume so
  the higher model continues the same task instead of waiting at an idle prompt.
- Preserve the same task ID, assignee, ProjectProfile, TaskSpec, role contract,
  workspace, provider profile, agent ID, Boss, and evidence.
- Record a bounded private handoff, immutable routing history, transaction
  state, and concise idempotent Priorities comments.
- Roll back to the previous model and exact session when forward resume fails.
- Fail closed without a silent fresh provider session.

## Non-Goals

- Inferring failure from terminal text, elapsed time, process crash, or silence.
- Escalating authentication, quota, provider, infrastructure, missing-context,
  or policy failures.
- Changing backend, provider profile, account, or organization.
- Cross-provider or cross-account handoff.
- Parallel ownership by two workers.
- HUD controls or automatic budget-price calculation.
- Replacing Boss, Nightwatch, queue, HUD, Docker, or unrelated workers.
- Claiming token savings or exact cost when provider telemetry is absent.

## Chosen Approach

The selected worker keeps the same agent ID and exact Codex session. MyPeople
restarts the Codex process with the next allowed model inside the current
provider profile.

This is preferred over a fresh session because it preserves provider-visible
conversation continuity and avoids reinjecting a large handoff. A bounded
private handoff is still captured as recovery evidence. A fresh session is not
a fallback in this phase.

Launching a stronger parallel reviewer is rejected because it duplicates cost,
creates competing ownership, and does not prove lossless replacement.

## Eligible Failure Contract

Only these existing routing failure types can request escalation:

- `verification_failed`
- `implementation_blocked`
- `model_capability_insufficient`

The following classes never trigger model escalation:

- provider exhaustion or quota;
- provider authentication or authorization;
- provider process startup or session-capture failure;
- infrastructure, Docker, tmux, queue, filesystem, or network failure;
- task, ProjectProfile, TaskSpec, role, receipt, or context mismatch;
- policy denial or missing policy;
- timeout, silence, crash, or an inferred lack of progress.

Ineligible input fails before any process, roster, receipt, task status, or
comment mutation.

## User-Facing Commands

### Worker report

A managed owner worker may report only against its own environment-bound task:

```bash
mp fail \
  --failure verification_failed \
  --summary "The required verifier still fails after the bounded implementation attempt." \
  --proof "python3 verify/example.py: 1 failed"
```

The command requires:

- `AGENT_ID`, `OWNER_TASK_ID`, and `BOSS_ID`;
- an active owner roster record matching those values;
- an open task assigned to that exact agent;
- a non-empty summary of at most 2,000 characters;
- one to five evidence strings, each at most 1,000 characters;
- an eligible failure type;
- a valid current routing receipt and available exact Codex session.

The worker command writes a private request first, then submits only its opaque
request ID to the queue. It never kills its own tmux process inline. The
external queue client performs the transaction and makes duplicate delivery
idempotent.

### Boss or operator escalation

The owning Boss may initiate the same operation:

```bash
mp escalate node-1/main:Worker-1 \
  --failure model_capability_insufficient \
  --summary "The worker produced a bounded blocker with no viable implementation path." \
  --proof "Boss review confirmed the capability blocker."
```

When `AGENT_ID` is present, it must equal the target record's `boss_id`.
An unrelated managed worker is rejected. A local operator shell without
`AGENT_ID` may invoke the command directly. Boss/operator input is persisted
through the same private request schema before execution.

An internal `--request-id` form is reserved for queue delivery and accepts no
free-form command-line summary or evidence.

## Private Request Record

Requests live under:

```text
run/routing-escalations/requests/<request-id>.json
```

The directory is mode `0700` and each record is mode `0600`. The closed
schema contains:

- schema version and opaque request ID;
- target agent ID, task ID, and Boss ID;
- requesting actor class: `worker`, `boss`, or `operator`;
- eligible failure type;
- bounded summary and evidence strings;
- current routing receipt SHA-256;
- creation time and request state.

It contains no provider output, session identifier, credential, token, API key,
environment dump, or raw terminal transcript. Queue payloads and process
arguments contain only the request ID and target agent ID.

## Transaction Coordination

The transaction reuses the existing private provider-switch lock. This matters
even though the provider profile does not change:

- Boss supervisor observes the lock and pauses provider launches and
  reconciliation.
- Provider-profile switching cannot race with a model escalation.
- A killed selected worker cannot be revived by `mp reconcile` midway through
  the transaction.
- Running Boss, Nightwatch, HUD, queue, Docker, and unrelated workers continue.

The lock contains an owner transaction ID and is removed only by that owner.
Duplicate or concurrent requests fail closed or return the already recorded
result.

## Transaction Record

Each request owns:

```text
run/routing-escalations/transactions/<request-id>/
  state.json
  roster-before.json
  routing-before.json
  routing-candidate.json
  handoff.json
```

The transaction directory is mode `0700`; records are atomic mode `0600`.
State phases are:

- `prepared`
- `stopped`
- `resuming`
- `verifying`
- `committed`
- `rolling_back`
- `rolled_back`
- `recovery_required`

The handoff reuses the existing sanitizer for a maximum 4,000-character
terminal tail and adds only the bounded failure summary and evidence. Secret
assignments, credential paths, JWT-like values, private keys, and userinfo are
redacted.

## Forward Transaction

The command performs these gates in order:

1. Validate the request schema and request ownership.
2. Load the target roster record and require a live, non-retired Codex owner
   worker with an available exact session.
3. Load the board and require the task to exist, remain open, and remain
   assigned to the target.
4. Validate TaskSpec, role, routing receipt paths and SHA-256 bindings.
5. Load the private routing policy and calculate `next_route`.
6. Resolve the candidate model through the current provider profile before
   stopping anything.
7. Capture the private roster snapshot, prior routing receipt, and sanitized
   handoff.
8. Write an immutable candidate receipt and prepared state.
9. Acquire the provider-switch lock and revalidate all gates to close the
   check/use race.
10. Mark only the selected roster record as `switching`.
11. Kill only its tmux window and recording session.
12. Resume its exact provider session with the candidate model and candidate
    receipt.
13. Verify the same agent ID, session ID, task ID, Boss, backend, provider
    profile, cwd, TaskSpec hash, role hash, and new routing hash/model.
14. Verify unrelated roster records are unchanged and their windows remain
    live.
15. Submit exactly one fixed continuation message to the resumed worker:
    `Continue the same owner task from the preserved session. Re-run the
    failed verification and report with mp complete or one new structured
    failure.`
16. Mark the transaction and request committed, then release the lock.
17. Add one idempotent Priorities result comment.

The candidate receipt uses the existing closed decision schema and
`selection=automatic_escalation`. Its `attemptCount` and
`escalationCount` advance once. It is stored in immutable routing history;
the roster points to the committed receipt. The previous receipt is never
deleted.

## Exact Resume Rules

The forward process must call the existing exact-resume path with:

- the prior validated Codex session ID;
- the same provider profile and provider home;
- the same working directory;
- the candidate model;
- the same TaskSpec and role receipts;
- the candidate routing receipt.

It must not use fresh spawn, session discovery, a blank session ID, or a fresh
handoff provider transaction. The provider transcript remains authoritative
for exact session identity.

No handoff, terminal tail, summary, or evidence is injected into the provider
conversation. After exact resume verification, MyPeople submits the one fixed
continuation message above. Delivery is attempted exactly once and is part of
the forward transaction gate; a local delivery failure enters rollback rather
than silently leaving the stronger worker idle.

Classification, route calculation, receipt handling, and process transaction
make no model request. The fixed continuation message starts one normal turn
on the selected higher model and therefore consumes that model's ordinary
tokens. Provider context accounting remains provider-defined and is recorded
as `not_measured` unless telemetry exists.

## Priorities Visibility

The request produces at most one bounded request comment:

```text
[escalation-request:<12 hex>] failure=verification_failed agent=node-1/main:Worker-1 status=queued
```

A committed transaction produces one result comment:

```text
[routing:<12 hex>] escalation=committed failure=verification_failed from=gpt-5.6-luna to=gpt-5.6-terra sameTask=true exactResume=true continuation=sent routingAiUsage=none
```

A rollback or recovery-required outcome uses the transaction marker and typed
phase without raw exception text. Comments are idempotent by marker. Evidence
remains attached to the original task.

## Rollback

If forward resume or verification fails after the selected process is stopped:

1. Enter `rolling_back` while retaining the same lock.
2. Kill any partial candidate window.
3. Restore the prior roster record and routing receipt binding.
4. Resume the prior exact session with the prior model.
5. Verify the restored agent identity, session, task, model, receipt, and
   window.
6. Mark `rolled_back`, record a typed sanitized comment, and release the
   lock.

A successful rollback does not spend the routing escalation budget because
the candidate receipt never becomes committed. The processed request cannot be
automatically retried; a new explicit structured request is required.

If rollback also fails:

- mark the selected worker dead with recovery state `blocked`;
- preserve the prior roster snapshot, both receipts, handoff, and transaction;
- move the original task to `blocked` without deleting or reassigning it;
- notify Boss with a typed `routing_escalation_recovery_required` message;
- release the owned lock only after durable recovery evidence exists.

There is no silent fresh-session fallback.

## Idempotency And Concurrency

- Request IDs are opaque and validated.
- A committed, rolled-back, or recovery-required request returns its recorded
  result without repeating side effects.
- A queued duplicate cannot create a second receipt, comment, or process stop.
- The provider-switch lock serializes provider/profile/model mutations.
- All gates are repeated after lock acquisition.
- The transaction rejects a changed assignee, task state, receipt hash,
  session identity, provider binding, or routing policy.
- The task remains assigned to one worker throughout the transaction.

## Queue Integration

The queue client accepts a new internal `routing_escalate` action. Its payload
contains only:

- target agent ID;
- opaque request ID.

It invokes the internal request form with a bounded timeout and returns a
sanitized typed result. Queue journal semantics make an uncertain delivery
visible; replay remains safe because the transaction is request-idempotent.

## Verification Strategy

### Pure and focused tests

- worker request schema, bounds, private permissions, and secret rejection;
- actor authorization for worker, Boss, unrelated agent, and operator;
- eligible and ineligible failure types;
- budget, tier, allowlist, provider-profile, and receipt gates;
- immutable prior and candidate receipt history;
- duplicate request idempotency and lock contention;
- queue payload contains no summary, evidence, credential, or session ID;
- exact resume receives the same session ID and candidate model;
- the fixed continuation message is submitted exactly once and no handoff
  payload is injected;
- only the selected tmux window and recording session are stopped;
- same task, assignee, cwd, TaskSpec, role, Boss, backend, and profile;
- unrelated roster records and windows remain unchanged;
- successful rollback restores prior model, receipt, and exact session;
- failed rollback produces `recovery_required` and a recoverable blocked task;
- no fresh spawn or silent fallback.

### Isolated E2E

A synthetic Codex fixture starts an economy owner worker, records a session,
submits a typed capability failure, processes the queue request, and proves:

- Luna changes to Terra;
- agent ID, provider session ID, task ID, assignee, Boss, provider profile,
  workspace, TaskSpec hash, and role hash are identical;
- attempt and escalation counters advance once;
- the fixed continuation message is submitted exactly once after verification;
- Boss, Nightwatch, queue, HUD, Docker fixture, and unrelated worker remain
  available;
- prior and committed receipts plus transaction evidence exist privately;
- duplicate delivery has no extra side effect.

### Live canary

After packaged verification and a backup-first image upgrade:

1. Create one disposable simple task authorized for economy routing.
2. Let Boss start one disposable Luna owner worker.
3. Submit a controlled `model_capability_insufficient` report with harmless
   evidence.
4. Verify the same worker and exact session resume on Terra.
5. Verify Boss, Nightwatch, Priorities, HUD, queue, board, and unrelated state.
6. Preserve sanitized evidence, then retire the disposable worker.

The live canary does not intentionally test rollback. Rollback is covered in
the isolated fixture to avoid creating an unnecessary live outage.

## Public Documentation

README and the user manual will explain:

- the three eligible failures;
- worker and Boss commands;
- exact same-session behavior;
- zero-token routing/escalation calculation;
- provider/profile/account non-goals;
- rollback and recovery-required behavior;
- the live canary and safe cleanup procedure.

All repository content remains English and contains no personal data,
credentials, provider session IDs, or private runtime paths.

## Acceptance Criteria

- One explicit eligible failure advances exactly one allowed model tier.
- The selected worker is the only stopped process.
- Exact Codex session ID and durable task identity remain unchanged.
- No fresh provider session is created.
- Exactly one compact continuation message starts the next higher-model turn.
- Provider, profile, account, backend, workspace, TaskSpec, role, and Boss
  remain unchanged.
- Prior and candidate routing receipts and the private handoff remain auditable.
- Duplicate queue delivery is side-effect free.
- Ineligible failures and invalid state mutate nothing.
- Forward failure either restores the prior exact worker or records
  recovery-required without claiming success.
- Focused, isolated, packaged, launcher, and live-canary gates pass before
  publication.
