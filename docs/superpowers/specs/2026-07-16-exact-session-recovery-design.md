# Exact Agent Session Recovery Design

## Status

Approved by the operator on 2026-07-16.

## Context

MyPeople currently persists task ownership, project context, provider bindings,
models, and role metadata, but `mp revive` starts a new provider conversation.
The roster has a `session_id` field, yet Codex sessions are not captured and the
Claude lifecycle hook only writes the ID to the per-pane status file. A missing
Boss window is automatically revived even when `mp kill` was deliberate.

This design adds exact same-session recovery without making provider
conversations the source of project memory. Priorities, TaskSpec, ProjectProfile,
workspace Git state, evidence, and public handoffs remain authoritative.

The runtime versions verified for this design are:

- Codex CLI 0.144.3, which supports
  `codex resume [OPTIONS] <SESSION_ID>` and `--model`;
- Claude Code 2.1.209, which supports
  `claude --resume <SESSION_ID>` and `--model`.

## Goals

- Capture and persist the provider session ID for every managed agent.
- Resume the exact conversation after a deliberate stop or accidental window
  loss when backend and provider identity are unchanged.
- Allow a model change inside the same backend and profile while preserving the
  exact conversation.
- Make deliberate stop intent durable so supervisors cannot undo an operator
  decision.
- Add bounded, observable reconciliation for accidental failure.
- Preserve the existing explicit provider-profile switch transaction.
- Fail closed when exact resume evidence is missing or contradictory.
- Keep all runtime credentials, prompts, transcripts, and private account data
  out of Git, Priorities comments, and recovery logs.

## Non-goals

- No Priorities or HUD lifecycle buttons in this phase.
- No automatic model-tier selection or cost-based routing.
- No simultaneous provider-account management UI.
- No SQLite board migration.
- No recorder lifecycle redesign.
- No recovery of hidden reasoning across different providers.
- No silent fresh-session fallback after an exact resume failure.
- No change to Docker networking, Tailscale, Windows dictation, or the
  one-click launcher.

## Alternatives Considered

### Install global provider hooks for both backends

The upstream project installs lifecycle hooks into global Claude and Codex
configuration. Hooks provide direct session IDs, but changing global user
configuration is invasive and conflicts with MyPeople's profile-scoped runtime
homes.

### Use handoffs for every recovery

This is simple and provider-neutral, but it discards recoverable provider
conversation state and does not meet the exact-resume requirement.

### Selected: backend-aware hybrid capture

Claude keeps using its existing lifecycle hook because the hook payload already
contains `session_id`. Codex session metadata is discovered inside the effective
profile-scoped `CODEX_HOME`. Codex startup discovery is serialized only until a
new session is identified; agent work remains fully parallel.

This approach avoids global Codex mutation, preserves profile isolation, and
uses the native resume commands verified in the installed CLIs.

## Core Invariants

1. The task belongs to Priorities, not to a provider process.
2. Exact resume is allowed only when session backend, provider profile, and
   session storage match the requested runtime identity.
3. A model may change during exact resume when backend and profile remain the
   same.
4. A backend or provider-profile change requires an explicit sanitized handoff
   and a fresh provider session.
5. `reconcile` never creates a fresh session after an exact resume failure.
6. Deliberate stop intent is written before tmux is stopped.
7. Missing or invalid session evidence produces a typed blocked state.
8. Recovery attempts are bounded and visible in roster/status state.
9. No recovery record contains transcript content, credentials, tokens, or
   hidden reasoning.

## Architecture

### 1. Session runtime module

Add a focused `bin/agent_session.py` module responsible for:

- normalizing and validating provider session IDs;
- taking a pre-launch session snapshot;
- discovering a new Codex session after launch;
- receiving a Claude session ID from status state;
- locating and validating a transcript for an existing session;
- comparing recorded and effective provider identity;
- building backend-specific exact-resume arguments;
- managing startup-capture locks and recovery metadata.

The module does not start tmux, mutate tasks, or choose models.

### 2. Codex session capture

Codex stores session metadata under:

```text
$CODEX_HOME/sessions/**/rollout-*.jsonl
```

The first JSONL record is a `session_meta` event whose payload contains the
session UUID and real working directory.

Before creating a Codex tmux window, `mp spawn`:

1. resolves the effective provider profile and `CODEX_HOME`;
2. acquires a private startup lock scoped to that Codex profile;
3. records the existing session files and launch timestamp;
4. starts the tmux window;
5. waits for the composer and sends the role's bootstrap message exactly once;
6. polls for a new `session_meta` record created after the snapshot;
7. requires its real `cwd` to equal the agent's resolved cwd;
8. persists the UUID in status and roster;
9. releases the lock.

Codex 0.144.3 may defer creating the transcript until it receives the first
user prompt. The bootstrap message is therefore computed before launch and sent
while startup discovery still owns the profile capture lock. Boss, Nightwatch,
owner workers, and fresh provider handoffs use their existing doctrine,
TaskSpec, or sanitized handoff prompt. Temporary or otherwise unclassified
workers receive one bounded generic readiness prompt so they also establish a
recoverable session. The message must not be sent a second time after roster
persistence.

If the composer never becomes ready or the bootstrap message cannot be
submitted, startup records a typed unavailable state and does not claim exact
recovery readiness. This ordering changes no Claude hook behavior and adds no
probe message when a real role prompt already exists.

The lock is held only during provider startup and session identification. It
does not serialize prompts, tools, or subsequent work. The default discovery
deadline is 90 seconds and is configurable for deterministic tests. The
larger default absorbs slow provider startup without spending additional
tokens; it only extends the failure wait when no transcript appears.

Profile-scoped serialization prevents two concurrent MyPeople spawns sharing
one `CODEX_HOME` from claiming the same session. A malformed record, duplicate
candidate, timeout, or cwd mismatch leaves the window usable but records
`resume_state: unavailable`; it must never guess an ID.

### 3. Claude session capture

The existing Claude lifecycle hook already receives `session_id`. Its atomic
status write will also update the matching durable roster entry under the roster
lock. `SessionStart` is the normal capture event; `UserPromptSubmit` may provide
the first ID on Claude versions that delay it.

Spawn readiness accepts a visible composer even if Claude has not emitted an ID
yet, but the agent remains `resume_state: unavailable` until the hook supplies
one. Exact revival is rejected while that state remains unavailable.

### 4. Durable roster contract

Managed roster records gain the following non-secret fields:

```json
{
  "session_id": "provider-session-uuid",
  "session_backend": "codex",
  "session_profile": "codex-primary",
  "session_cwd": "/workspace/project",
  "session_recorded_at": 0,
  "resume_state": "available",
  "stop_intent": "",
  "recovery_attempts": 0,
  "next_recovery_at": 0,
  "recovery_state": "healthy",
  "last_recovery_error": ""
}
```

Allowed `resume_state` values are `pending`, `available`, and `unavailable`.
Allowed `recovery_state` values are `healthy`, `stopped`, `recovering`,
`cooldown`, and `blocked`.

`last_recovery_error` contains only a bounded typed code such as
`session_missing`, `session_identity_mismatch`, or `resume_process_failed`.
Provider stderr, transcript content, and credential paths are not copied.

### 5. Exact resume launch contract

For Codex, the effective launch is equivalent to:

```text
codex resume
  --sandbox danger-full-access
  --ask-for-approval never
  -C <recorded-cwd>
  [--model <desired-model>]
  [existing trust and worker-contract overrides]
  <session-id>
```

For Claude, the existing autonomous, plugin, role, and model arguments are
preserved and extended with:

```text
claude ... [--model <desired-model>] --resume <session-id>
```

Before launch, exact revival requires:

- a valid recorded session ID;
- an existing provider transcript/session record;
- matching recorded and requested backend;
- matching recorded and effective provider profile;
- matching real cwd;
- an open owner task when the agent owns a task;
- matching TaskSpec and role-contract receipts when present.

Failure of any prerequisite stops before tmux creation.

### 6. Deliberate stop

`mp kill` becomes a durable deliberate-stop transaction:

1. validate the agent record;
2. persist `retired: true`, `state: stopping`,
   `stop_intent: deliberate`, reason, and timestamp;
3. stop recorder and tmux window;
4. persist `state: dead`, `recovery_state: stopped`;
5. unregister the live agent.

Writing intent before killing tmux closes the race with the supervisor.

An explicit `mp revive` may clear the deliberate tombstone only after all exact
resume prerequisites pass. If launch fails, the previous stopped state is
restored and the failure is recorded without starting a fresh conversation.

### 7. Accidental recovery and reconcile

Add `mp reconcile` and have `boss-supervisor.sh` call it every 15 seconds after
the provider-pause and provider-switch guards.

For each non-retired managed record:

- an existing window is healthy and resets recovery counters;
- a missing window with an available exact session enters recovery;
- attempts are separated by a 30-second cooldown;
- automatic recovery stops after three failed attempts;
- the final state is `blocked` with a typed error;
- a deliberate tombstone is always skipped.

`reconcile` calls the same strict exact-resume path as explicit `mp revive`.
There is no fresh fallback.

For an initial process that never records any provider session and disappears
while still `starting`, `reconcile` may perform up to three explicit
`bootstrap_retry` spawns. This is not reported as exact recovery. Each retry is
recorded, keeps the same TaskSpec and role receipts, and is allowed only because
no resumable provider session was ever established. After the cap, the agent is
blocked.

### 8. Boss and Nightwatch supervision

Boss and Nightwatch follow the same lifecycle contract as workers.

- If no Boss record exists, the supervisor may bootstrap the configured Boss.
- If a Boss record has deliberate stop intent, it remains stopped.
- If an active Boss record loses its window, `mp reconcile` performs strict
  exact recovery.
- The supervisor never interprets a failed exact resume as permission for a
  fresh Boss.
- Nightwatch follows the same rule and preserves its recorded backend, model,
  provider profile, and session.

### 9. Model and provider switching

`mp switch` distinguishes identity-preserving and identity-changing changes.

- Same backend and provider profile, different model: exact resume with the new
  model.
- Different backend or provider profile: exact resume is impossible. The
  existing provider-session transaction captures a sanitized handoff and uses a
  separately named explicit fresh-handoff operation.

The fresh-handoff operation is accepted only while the provider-switch lock is
owned by the active transaction and only for a handoff path under that private
transaction directory. It preserves task, cwd, TaskSpec, role, evidence
references, and model selection. It never claims that the provider conversation
was resumed.

### 10. Failure behavior

Typed failures include:

- `session_capture_timeout`;
- `session_capture_ambiguous`;
- `session_metadata_invalid`;
- `session_missing`;
- `session_identity_mismatch`;
- `session_cwd_mismatch`;
- `owner_task_closed`;
- `resume_process_failed`;
- `recovery_attempts_exhausted`;
- `fresh_handoff_not_authorized`.

Failures update roster/status atomically. They do not delete the previous
session, change the task owner, close a task, or expose backend stderr in public
state.

## Security and Privacy

- Session IDs are opaque operational identifiers, not credentials.
- Transcript contents never enter roster, board comments, logs, or Git.
- Runtime paths may be stored in private roster state but not public evidence.
- Provider credentials remain in existing host/profile stores.
- Startup locks and recovery files use private directories and atomic writes.
- Fresh handoff authorization is bound to the existing provider-switch lock.
- No generic shell or provider credential is exposed to Priorities or HUD.

## Verification Strategy

### Unit and contract tests

- Codex snapshot discovery accepts exactly one new matching `session_meta`.
- Fresh Codex startup submits one role bootstrap prompt before discovery and
  never duplicates it after roster persistence.
- Temporary Codex workers establish a transcript with one bounded readiness
  prompt before their session identity is captured.
- Codex discovery rejects stale, malformed, ambiguous, and wrong-cwd records.
- Profile-scoped startup locking prevents double claims.
- Claude hook copies session ID into status and roster.
- Resume argument builders preserve role, cwd, model, and provider overrides.
- Exact resume rejects missing transcript and identity mismatch.
- Deliberate stop is persisted before tmux termination.
- Explicit revive restores the previous tombstone after launch failure.
- Same-profile model switching uses exact resume.
- Cross-profile/provider switching requires an authorized fresh handoff.

### Reconcile tests

- Deliberately stopped agents are skipped.
- Missing active windows attempt exact resume.
- Cooldown prevents rapid retries.
- Three failed attempts produce a stable blocked state.
- Exact resume failure never calls fresh spawn.
- A never-started zombie receives at most three labeled bootstrap retries.
- Boss and Nightwatch do not bootstrap over existing deliberate tombstones.

### Isolated integration tests

- A fake Codex provider writes a real `session_meta`, exits, and is relaunched
  with the same UUID.
- A fake Claude hook publishes a session ID and exact revive uses it.
- TaskSpec, role receipts, cwd, model, and owner task remain unchanged across
  exact revive.
- Provider-profile switching uses the handoff path and records a fresh session
  without claiming exact resume.
- The focused lifecycle, provider-session, TaskSpec, worker-handoff, and
  supervisor suites remain green.

### Live canary

After image build and isolated verification:

1. create one disposable managed Codex worker;
2. give it a non-secret unique continuity marker;
3. confirm its session UUID is persisted;
4. deliberately stop it;
5. explicitly revive it with the same profile;
6. verify the UUID is unchanged and the marker remains available;
7. retire the canary and remove only its disposable task/runtime artifacts.

The live Boss, Nightwatch, board, queue, workspace, and provider credentials are
not used as destructive test subjects.

## Rollout and Rollback

The feature ships behind the persisted roster fields and strict CLI behavior;
no database migration is required. Old records without `session_id` remain
readable but are not exact-resumable. They may continue running until naturally
replaced or may be explicitly fresh-started by the operator with a handoff.

Before replacing the live image:

- back up runtime volumes and roster;
- run the isolated full verifier;
- verify the one-click launcher against the candidate image;
- keep the previous image tag for rollback.

Rollback restores the previous image and roster backup. Existing provider
session files are never deleted by either rollout or rollback.

## Acceptance Criteria

1. New Claude and Codex agents persist their provider session IDs.
2. A deliberate stop remains stopped until explicit revive.
3. Explicit revive uses the same provider session ID.
4. An accidental missing window is recovered through strict exact resume.
5. Recovery stops after three failed attempts with a visible blocked state.
6. No exact-resume failure silently creates a fresh provider session.
7. A same-profile model change preserves the exact provider conversation.
8. A backend/profile change uses an explicit sanitized handoff and reports a
   fresh session honestly.
9. Task ownership, TaskSpec, role receipts, cwd, evidence, and Git workspace
   survive both recovery paths.
10. Focused tests, isolated full verification, live disposable canary, launcher
    smoke, public-content audit, and secret scan pass before publication.
