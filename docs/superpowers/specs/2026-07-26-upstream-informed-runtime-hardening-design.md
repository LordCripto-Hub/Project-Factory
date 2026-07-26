# Upstream-Informed Runtime Hardening Design

Date: 2026-07-26  
Status: Draft for review  
Branch: `feat/upstream-hardening`  
Baseline: `origin/main` at `febf5ac2bf3c9129733847e6c6517a71232a3c7c`

## Purpose

Harden five runtime contracts after Memory Gate B without changing the selected
memory architecture, provider-profile model, exact session recovery, adaptive
routing, project/task contracts, or controlled Git publisher.

The changes are informed by patterns identified in `delattre1/mypeople`, but
they will be implemented against this repository's current architecture. The
referenced upstream commits are design references, not code-import targets.

## Scope

This stage contains five ordered changes:

1. Validate the identity and readiness of an existing tmux agent window.
2. Reject local evidence paths submitted as URLs and expose media load errors.
3. Add typed provider-health classification without restarting Docker.
4. Remove silent backend fallback, including implicit fallback to Claude.
5. Prove task persistence across an isolated server or Docker restart.

Each change must begin with a failing focused test, remain independently
reviewable, and preserve all existing public behavior not explicitly changed
here.

## Non-goals

- Do not deploy to the live MyPeople container in this stage.
- Do not merge or publish implementation without explicit approval.
- Do not change the Gate B activation state, comparison receipts, dataset, or
  promotion decision.
- Do not implement the permanent provider-health HUD in this stage. This stage
  creates its authoritative backend contract and a minimal Priorities
  diagnostic surface; a later HUD stage will project the same data.
- Do not implement the bounded exhaustive memory fallback tracked separately.
- Do not adopt upstream `memory-dump.py`, create a board corpus, or introduce a
  parallel memory store or index.
- Do not poll providers continuously or consume model tokens for health checks.

## Design Principles

### One authoritative typed contract per concern

The implementation will introduce or consolidate five small contracts:

- `agent_identity`
- `evidence_validation`
- `provider_health`
- `backend_resolution`
- `persistence_e2e`

CLI commands, Boss, roster projections, Priorities, and later the HUD must
consume these contracts rather than independently infer state.

### Fail closed with visible diagnostics

Ambiguous agent identity, invalid local evidence URLs, unresolved backends, and
unclassifiable launch state must block the affected action. The error must
include a stable machine-readable code and a concise operator-facing message.

### Receipts over hidden state

Important classifications and validation results must be stored atomically in
private runtime receipts. Receipts may contain sanitized diagnostic categories,
timestamps, and references, but never access tokens, authentication material,
or unbounded provider output.

## 1. Existing tmux Agent Identity

### Current problem

`window_exists()` currently calls only `tmux has-session`. A tmux target can
exist while containing a shell, a crashed provider process, the wrong backend,
the wrong profile/model, or an agent that never reached its interactive
composer. Treating existence as identity can route work into the wrong process.

### Contract

The new validator receives an expected identity derived from the roster,
provider binding, launch receipt, and requested operation. It returns:

```json
{
  "ok": true,
  "state": "ready",
  "target": "mc-main:Boss",
  "observedAt": 0,
  "checks": {
    "window": "pass",
    "process": "pass",
    "backend": "pass",
    "profile": "pass",
    "model": "pass",
    "arguments": "pass",
    "readiness": "pass"
  }
}
```

Failure uses a stable state such as:

- `window_missing`
- `process_missing`
- `process_mismatch`
- `backend_mismatch`
- `profile_mismatch`
- `model_mismatch`
- `arguments_mismatch`
- `not_ready`
- `identity_unknown`

### Evidence sources

Validation will combine, in order:

1. tmux target existence;
2. pane PID and descendant process inspection;
3. observed executable and sanitized arguments;
4. roster and provider-session identity;
5. required launch parameters such as working directory and owner task;
6. readiness evidence from the backend-specific composer or a current launch
   receipt.

No single source is sufficient on its own. Process-command inspection must
compare normalized structured arguments, not substring-match one shell line.

### Integration

- New spawns validate readiness before accepting the first task.
- Reuse, revive, switch, and recovery validate the existing target before
  messaging it.
- Exact session recovery remains authoritative for provider conversation
  identity; the new validator confirms that the live process matches that
  identity.
- A failed validation does not kill or overwrite the existing target
  automatically. It blocks and explains the mismatch.

## 2. Evidence Validation and Visible Failures

### Current problem

The evidence API can classify any supplied URL as a link. This permits
`file://` references and local Windows, UNC, or POSIX paths that another browser
or container cannot open. Image and video elements also lack an explicit
visible failure state.

### URL contract

Link evidence accepts only explicitly supported remote schemes, initially
`http` and `https`. It rejects:

- `file://...`
- Windows drive paths such as `C:\...` or `C:/...`
- UNC paths such as `\\host\share\...`
- absolute POSIX paths such as `/home/...`
- malformed or scheme-relative local references

The API returns:

```json
{
  "ok": false,
  "error": "local_evidence_path_rejected",
  "action": "use_proof_file"
}
```

The CLI and Priorities translate this into a concise instruction to upload with
`--proof-file <path>`. Validation is server-side and therefore cannot be
bypassed by another client.

### Media rendering contract

Image and video cards attach `error` listeners. On failure they retain the
evidence metadata and replace the blank media area with a visible message:

> Evidence preview could not be loaded. Open or download the original artifact.

The original safe URL remains available when appropriate. Existing upload
storage, MIME data, byte counts, SHA-256 hashes, authorship, and timestamps are
preserved.

## 3. Provider Health

### Purpose

Expose whether an assigned provider can serve an agent without restarting
Docker and without confusing authentication, quota, network, and process
failures.

### States

Every health receipt has exactly one state:

- `authenticated`
- `expired`
- `quota_exhausted`
- `unreachable`
- `unknown`
- `process_dead`

It also carries:

```json
{
  "provider": "codex",
  "profile": "default",
  "agentId": "node-1/main:Boss",
  "state": "authenticated",
  "reasonCode": "session_active",
  "observedAt": 0,
  "stale": false,
  "source": "spawn"
}
```

### Classification rules

Classification uses deterministic evidence and explicit precedence:

1. A missing expected live process is `process_dead`.
2. A confirmed provider authentication rejection is `expired`.
3. A confirmed usage or quota rejection is `quota_exhausted`.
4. A transport/DNS/timeout/service failure is `unreachable`.
5. A successful authenticated provider interaction is `authenticated`.
6. Insufficient or conflicting evidence is `unknown`.

A temporary network failure must never mutate credentials to `expired`.
Unknown errors must retain a sanitized diagnostic reference, not be guessed
into a stronger category.

### Refresh policy

There is no periodic provider polling. Health refresh occurs on:

- spawn, revive, switch, or provider-session start;
- an observed provider failure;
- an explicit `mp providers-status --refresh` request.

Ordinary status reads return the latest receipt and mark it `stale` after a
configured age. Manual refresh must be rate-limited and must not invoke a paid
model turn merely to test health.

### Surfaces

This stage exposes the same projection through:

- `mp providers-status`;
- roster/agent state used by Boss;
- visible diagnostics in Priorities when provider state blocks work.

The later HUD stage will display these receipts as compact health indicators
and offer manual refresh. It must not implement a second health detector.

## 4. Explicit Backend Resolution

### Current problem

Backend defaults can silently select a provider even when the task, assigned
profile, and routing policy do not contain an intentional decision. This makes
failures look like provider problems and can unintentionally launch Claude.

### Resolution precedence

Every spawn resolves its backend using this order:

1. explicit task or command override;
2. assigned agent/provider profile;
3. approved routing-policy decision.

If none produces one supported backend, resolution returns
`backend_unresolved` and blocks the spawn. If sources conflict without an
explicit higher-precedence choice, it returns `backend_ambiguous`.

Claude remains a supported explicit backend. It is not removed; only implicit
or silent selection is removed. The same rule applies to Codex and future
providers.

### Receipt

The launch receipt records the chosen backend and its source:

```json
{
  "backend": "codex",
  "resolutionSource": "routing_policy",
  "policyRevision": "..."
}
```

Remote spawn payloads carry the resolved decision or enough typed inputs for
the remote host to repeat and verify the resolution. They must not reintroduce
a local default.

## 5. Persistence Restart E2E

### Scenario

An isolated test instance creates one task containing:

- project slug and bounded context question;
- state and evidence policy;
- assigned owner and owner history;
- multiple comments;
- one uploaded evidence artifact with hash and metadata;
- verification and unread fields where applicable.

The test captures a canonical representation, restarts the isolated todo server
or disposable Docker container, reloads the board, and compares the canonical
representation.

### Assertions

- Every specified field survives.
- The uploaded artifact remains readable and hash-identical.
- No comment, proof, or ownership event is duplicated.
- Ordering remains deterministic.
- Restart does not fabricate a second task.
- The test uses temporary volumes or directories and never reads or writes the
  live board.

The final integrated verification repeats this scenario in disposable Docker
with the same volume topology intended for production.

## Gate B Compatibility

The implementation must preserve:

- Gate B control and attempt receipts;
- baseline/memory pairing rules;
- task memory-canary fields and UI;
- provider-usage and session metadata;
- the current `not_promoted` decision;
- hybrid-memory top-k, provenance, and escalation behavior.

Focused regression tests must prove that stricter backend and identity
validation do not rewrite completed Gate B evidence or activate memory.

## Test Strategy

TDD proceeds in five checkpoints:

1. Red/green unit and integration tests for `agent_identity`.
2. Red/green server and browser-DOM tests for evidence validation.
3. Red/green classification and CLI projection tests for provider health.
4. Red/green resolution tests covering explicit, profile, policy, missing, and
   conflicting backend inputs.
5. Red/green isolated restart E2E, followed by disposable-Docker integration.

After each checkpoint, run its focused tests and the closest existing
regression groups. Before requesting deployment approval, run the complete
isolated verifier, including J1-J52 and Gate B regressions.

## Security and Privacy

- Never persist credentials, access tokens, full authentication responses, or
  provider command output in health or identity receipts.
- Sanitize command arguments before storing diagnostics.
- Keep receipts private and atomically written with restrictive permissions.
- Continue binding the local default deployment to `127.0.0.1`.
- Evidence validation must occur before filesystem or URL dereference.

## Upstream Memory Pattern Decision

The upstream full-board corpus approach is documented only as a useful
diagnostic and manual-recovery pattern: it is flexible and easy to inspect, but
can increase context size, reduce retrieval precision, duplicate the source of
truth, and consume unnecessary tokens.

MyPeople retains the selected bounded hybrid-memory architecture: one event
store, FTS5 fast retrieval, deep relational escalation, top-k injection, and
complete provenance. The separately tracked exhaustive fallback may later add
bounded flexible exploration over that same store; it will not create a second
memory.

## Rollout

1. Implement only in the isolated worktree.
2. Present each bug reproduction, initial failing test, implementation, and
   green focused tests.
3. Run the final disposable-Docker verifier.
4. Report Gate B interactions and residual risk.
5. Await explicit approval before live deployment, merge, or publication.

Rollback is a code/image rollback only. Runtime receipts added by this stage
must be backward-compatible and ignorable by the previous image.

## Acceptance Criteria

- Existing tmux targets are accepted only when identity and readiness match.
- Local evidence paths are rejected with `use_proof_file` guidance.
- Broken image/video previews show a visible failure state.
- Provider health distinguishes all six required states without Docker restart.
- Network failures never masquerade as expired credentials.
- No backend, including Claude, is silently selected.
- The restart E2E proves task and artifact survival without duplication.
- Gate B and the existing provider/session architecture remain green.
- Full disposable-Docker verification passes.
- No live deployment, merge, or push occurs without approval.
