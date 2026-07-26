# Memory Gate B Active Live Canary

**Date:** 2026-07-21

**Status:** Approved design pending written-spec review

## Purpose

Promote the provider-neutral Gate B fixture into one explicit, reversible live
MyPeople canary. The canary must test whether bounded project memory improves a
real Boss-owned task while preserving the local TaskSpec contract, project
isolation, agent sessions, and the normal no-memory path.

This cycle does not enable memory globally. It does not write memories, train a
model, deploy Cloudflare, expose a memory tool to workers, or claim statistical
improvement from one task.

## Dependency And Branch Boundary

This design depends on the isolated experiment published by pull request 10.
Implementation lives on `feat/memory-gate-b-live-canary` and must remain a
separate review unit. The experiment package stays under
`experiments/memory-gate-b/`; production code may consume its closed recall
contract but must not import the experiment package as an implicit startup
dependency.

The old `feat/secure-memory-activation` implementation is not a merge base for
this work. It is substantially behind the current runtime and is coupled to a
synthetic Cloudflare credential path. Its fail-closed and secret-isolation
lessons may be reused, but its code must not be merged wholesale.

## Chosen Approach

Three activation strategies were considered:

1. Enable memory for every Project Factory task immediately.
2. Run a shadow phase that retrieves but never influences a TaskSpec.
3. Run one active, task-level opt-in canary with strict rollback.

The third approach is selected. Gate B already proves deterministic retrieval,
provenance, top-K limits, and Docker isolation. A shadow-only repetition would
not answer whether memory changes real execution. Global activation would make
fault attribution and rollback unnecessarily broad.

## First Canary Provider

The first canary uses a local, read-only sidecar built from the locked Gate B
dataset and closed recall protocol. It requires no Cloudflare account, paid
model call, persistent bearer credential, external network, or second memory
database. The sidecar is a replaceable provider behind MyPeople's existing
MemoryGateway boundary.

The dataset contains only committed public Project Factory history bound to
source commit `80dce6f866329b79061bb1ed6b0594f9fdf2dd45`. Because every managed
process in the current MyPeople container shares the `mp` operating-system
identity, this local canary is not treated as a credential boundary suitable
for private memory. Private or hosted memory remains blocked until a separate
broker identity is evaluated.

The sidecar must:

- expose recall only;
- accept only `project-factory`;
- return at most three claims and zero graph hops;
- enforce response-character and timeout bounds server-side;
- run with a read-only root filesystem and dataset;
- have no external network route, production volume, Docker socket, or
  provider credential;
- emit metadata only;
- stop independently without stopping MyPeople.

## Task Opt-In Contract

The task schema adds one operator-controlled Boolean:

```json
{
  "memoryCanary": true
}
```

The field defaults to `false` for existing and new tasks. It is accepted only
when all of these conditions are true:

- the task has `projectSlug: "project-factory"`;
- `contextQuestion` is non-empty and at most 500 characters;
- the runtime canary control is enabled;
- the project is present in the runtime allowlist;
- the ProjectProfile enables the reviewed local MemoryGateway endpoint;
- the task is not already owned by an active worker.

A regular task, a task from another project, or a task with an empty question
must not call memory even if the sidecar is running.

## Runtime Control

The durable runtime volume owns one private, atomically written control record:

```json
{
  "schemaVersion": 1,
  "enabled": false,
  "allowedProjects": ["project-factory"],
  "revision": 1,
  "updatedAt": 0
}
```

The TaskSpec compiler reads and validates this record on every owner-task
compilation. Therefore disabling the canary requires no Docker, Boss,
Nightwatch, queue, or provider-session restart.

The operator interfaces are:

```text
mp memory-canary status
mp memory-canary enable --project project-factory
mp memory-canary disable
```

Only metadata is printed. Updates are mode `0600`, atomic, revisioned, and
idempotent. An invalid or missing control record fails closed as disabled.

## Active Compilation Flow

For a canary task, MyPeople performs the following sequence before creating a
worker process:

1. Reject an existing live owner for the task.
2. Validate the task, ProjectProfile, runtime control, and project allowlist.
3. Compile a local-only baseline TaskSpec in memory without calling recall.
4. Ask MemoryGateway the task's explicit `contextQuestion`.
5. Validate project identity, provenance, schema, top-K, response size, and
   status of every returned claim.
6. Compile the candidate TaskSpec with local fields taking precedence.
7. Persist the candidate TaskSpec atomically with mode `0600`.
8. Persist a metadata-only baseline/candidate receipt.
9. Start exactly one owner worker and pass the candidate TaskSpec path.

The baseline is never executed. It exists only to measure the exact context
delta without paying for a duplicate worker execution.

## Failure And Retry Semantics

Memory-enabled compilation remains fail-closed. Timeout, unavailable sidecar,
invalid response, cross-project claim, missing provenance, excessive claim
count, or budget overflow prevents worker creation. The task remains intact
and receives a concise typed status.

The operator may select `Retry without memory`. This action:

- keeps the same card, task ID, project, comments, evidence, and repository;
- records that the canary was bypassed for this attempt;
- recompiles from the authoritative card without memory;
- does not reuse partial claims or a partial TaskSpec;
- starts the worker only after the local-only TaskSpec succeeds.

There are no automatic retries that could add hidden latency or provider cost.

## Receipt And Metrics Contract

Each canary attempt creates one append-oriented metadata receipt. The receipt
contains no claim text, question text, credential, provider transcript, email,
username, or private reasoning.

Required fields are:

```json
{
  "schemaVersion": 1,
  "attemptId": "opaque-id",
  "taskId": "task-id",
  "projectSlug": "project-factory",
  "controlRevision": 1,
  "profileRevision": 1,
  "memoryStatus": "ok",
  "returnedClaimCount": 3,
  "embeddedClaimCount": 3,
  "retrievalLatencyMs": 0,
  "baselineCharacters": 0,
  "candidateCharacters": 0,
  "memoryDeltaCharacters": 0,
  "memoryDeltaTokensEstimated": 0,
  "memoryProviderUsage": "not_measured",
  "backend": "codex",
  "model": "model-id",
  "providerProfile": "profile-id",
  "sessionAlias": "codex:abcd1234",
  "providerInputTokens": "not_measured",
  "providerOutputTokens": "not_measured",
  "toolCalls": "not_measured",
  "retries": 0,
  "startedAt": 0,
  "completedAt": 0,
  "durationMs": 0,
  "outcome": "pending",
  "utilityAssessment": "not_reviewed",
  "evidenceCount": 0,
  "humanInterventions": 0
}
```

`memoryDeltaTokensEstimated` is a deterministic context-size estimate and is
never reported as billed usage. Provider tokens are recorded only when the
provider transcript exposes an attributable usage event for the captured
session and attempt interval. Otherwise the value remains `not_measured`.

The local UI may show a shortened provider session alias derived from the
validated session ID. Public evidence replaces that alias with a one-way,
run-scoped pseudonym. Account email and login identity are out of scope.

## Outcome Evaluation

One task can prove integration safety and measure its own cost; it cannot prove
general quality improvement. The canary is complete only after Boss or the
operator assigns one structured assessment:

- `useful`: retrieved evidence materially helped the task;
- `neutral`: evidence was correct but did not affect execution;
- `harmful`: evidence distracted, contradicted, or caused rework;
- `not_demonstrated`: the attempt cannot support a conclusion.

The assessment records a short rationale and links existing task evidence. It
does not write a new durable memory. Gate C owns learning candidates,
validation, consolidation, and prevention.

Future promotion requires multiple comparable canaries and a separately
approved evaluation rule. No success percentage is inferred from this single
attempt.

## Priorities Experience

An opted-in task displays a compact memory strip using the existing visual
system. It shows:

- `MEMORY CANARY`;
- status: `not requested`, `retrieving`, `ready`, `failed`, or `rolled back`;
- embedded claims as a count from zero to three;
- retrieval latency;
- estimated memory-token delta and actual provider tokens when measured;
- model and shortened session alias;
- a link to the private receipt/evidence view.

Initial controls are:

- `Run with memory`;
- `Retry without memory`;
- `Disable canary`.

The controls use explicit confirmation for disabling or bypassing memory. They
do not expose raw claims, credentials, or complete session IDs in board JSON or
public comments. Existing tasks and non-canary cards retain their current
layout and behavior.

## Security Boundary

- Only Boss or an authenticated local operator may request canary compilation.
- Workers receive compiled claims in TaskSpec but no memory tool registration.
- Project slug is checked in the card, profile, gateway request, gateway
  response, and every claim.
- The local dataset and sidecar are read-only and contain public data only.
- The sidecar cannot write project state or execute tools.
- Local TaskSpec fields are never removed to fit memory.
- A strict timeout applies once; there is no automatic retry.
- Receipt writes are private, atomic, append-oriented, and bounded.
- Public export removes machine paths, session aliases, timestamps that identify
  a workstation, and all credential-shaped material.
- The canary never mounts the Docker socket or production state into the
  memory sidecar.

The shared `mp` operating-system identity means this canary is a cooperative
runtime boundary, not protection against a malicious worker with arbitrary
shell access. That limitation is explicit and is why private memory and hosted
credentials remain out of scope.

## Rollback

Rollback is successful when all of the following are demonstrated:

1. `mp memory-canary disable` atomically disables new recall.
2. A pending canary task can be recompiled without memory.
3. The same task, repository, comments, evidence, and session binding remain.
4. No partial enriched TaskSpec is reused.
5. The sidecar can stop without stopping MyPeople.
6. Boss, Nightwatch, queue, HUD, terminals, and provider sessions remain alive.
7. A sanitized rollback receipt records the typed reason.

Rollback does not kill Docker or an agent unless that specific process is
independently unhealthy. A memory failure alone is not a reason to restart the
control plane.

## Verification Strategy

Implementation follows test-driven development in this order:

1. Task-schema tests for `memoryCanary`, legacy defaults, authorization, and
   project allowlisting.
2. Control-record tests for atomic enable, disable, status, corruption, and
   no-restart behavior.
3. Compiler tests for baseline/candidate deltas, local-field priority, top-K,
   provenance, typed failures, and bypass retry.
4. Receipt tests for bounded metadata, honest token attribution, session
   aliases, redaction, and append behavior.
5. Sidecar contracts for read-only filesystem, no external network, no Docker
   socket, public locked dataset, and clean teardown.
6. Priorities API and browser tests for the strip, controls, legacy layout, and
   state transitions.
7. Disposable Docker E2E covering one positive canary, one cross-project
   negative, one timeout, and one rollback.
8. Full isolated Project Factory verification.
9. One synthetic live canary on a new test card after backups and preflight.
10. Before/after health checks proving unchanged restart counts and no residual
    test resources.

The live canary is not run while user-owned work is active. It creates and
cleans only its explicitly marked test card and preserves its sanitized receipt
as evidence.

## Success Criteria

The phase succeeds when:

1. Exactly one opted-in Project Factory task receives no more than three
   relevant, grounded claims.
2. The local TaskSpec contract remains byte-for-byte equivalent except for
   canary metadata, memory status, and memory claims.
3. A non-canary and a cross-project task make zero recall calls.
4. The worker completes the canary with reviewable evidence.
5. Baseline/candidate context delta, latency, session alias, model, and honest
   token fields are recorded.
6. Failure and rollback preserve the task and control-plane health.
7. MyPeople remains healthy with unchanged restart count.
8. The feature can be disabled without restarting Docker or provider sessions.
9. Public evidence is English, sanitized, and clearly labeled as one canary,
   not proof of general performance improvement.

## Explicit Non-Goals

- No automatic question generation from an entire task history.
- No memory writes, proposals, consolidation, or learned guardrails.
- No Cloudflare deployment or hosted MCP credential.
- No private ObsidianBrain or Engram data import.
- No multiple memory providers queried for one TaskSpec.
- No global activation.
- No automatic model selection changes caused by memory.
- No claim that a single task proves lower total token cost or better quality.

