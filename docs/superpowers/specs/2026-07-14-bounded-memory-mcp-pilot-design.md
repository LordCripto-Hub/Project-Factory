# Bounded External Memory MCP Pilot Design

## Status

Approved in principle on 2026-07-14 after the architecture review of
`rahilp/second-brain-cloudflare`. This document converts that decision into a
decomposed implementation contract. Each phase must remain independently
testable and reversible.

## Problem

MyPeople currently documents `ProjectProfile` and `TaskSpec` as its context
boundary, but neither contract exists in the runtime. Priority cards also have
no durable project identifier. Connecting a remote memory server directly to
every agent would therefore create an unbounded second source of truth and
would allow context, contradictions, and cost to leak across projects.

The reviewed Second Brain Cloudflare release has a strong retrieval engine and
MCP surface, but it currently uses one global memory pool, one owner identity,
optional tags rather than enforced project partitions, and instructions that
encourage habitual recall and silent capture. Those defaults are incompatible
with MyPeople.

## Goals

- Give every memory-enabled priority card an explicit project slug and one
  optional, concrete context question.
- Implement a small, versioned `ProjectProfile` and one compiled `TaskSpec`.
- Put all external memory access behind one MyPeople-owned `MemoryGateway`.
- Use MCP as the remote transport while keeping the gateway read-only during
  the first live pilot.
- Enforce project identity, result bounds, timeouts, provenance, and context
  size before memory reaches an agent.
- Harden a separate Cloudflare fork with real project partitions, scoped
  authorization, provenance, export/import, and vector rebuild.
- Keep Git and the MyPeople board authoritative for source and operational
  task state.
- Measure retrieval quality, latency, and Workers AI consumption before
  enabling persistent writes.
- Keep all tracked product content in English and free of secrets or private
  operator details.

## Non-goals

- MyPeople will not ingest ObsidianBrain, Engram, GBrain, provider chat history,
  or complete conversations.
- Agents will not call several memory systems for the same task.
- The initial pilot will not enable automatic capture, automatic pattern
  creation, nightly compression, Notion sync, or browser capture.
- Engineers will not receive unrestricted MCP credentials.
- The first MyPeople phase will not deploy Cloudflare resources or move real
  project data.
- The Cloudflare fork will remain a separate external component; its source
  will not be vendored into Project Factory.
- Provider account switching and memory authorization remain separate
  contracts. A Codex or Claude profile must never imply memory access.

## Decomposition

This initiative contains three independently releasable subprojects.

### Phase A — MyPeople bounded context foundation

Implement project identity, project profiles, TaskSpec compilation, and a
read-only MCP gateway in Project Factory. Verification uses a local fake MCP
server and synthetic memories. No Cloudflare account is required.

### Phase B — project-isolated Cloudflare MCP fork

Harden a separate fork of Second Brain Cloudflare. Every D1 row, graph edge,
Vectorize operation, contradiction query, and MCP tool call must carry an
enforced project slug. Add scoped credentials, provenance, restore/import, and
vector rebuild. Use synthetic data only.

### Phase C — private Cloudflare sandbox integration

Deploy the hardened fork to a private Cloudflare sandbox, connect only the
MyPeople gateway, execute the adversarial multi-project evaluation, and record
latency and neuron usage. Real project data and write promotion require a new
human gate after the sandbox report.

## Approaches considered

### 1. Give every Codex agent the upstream MCP directly

This is the easiest installation path, but it delegates context policy to
prompts, exposes the global memory pool to every worker, and makes recall cost
and project leakage difficult to control. It is rejected.

### 2. Let the Python compiler call the upstream REST API

This is technically small and avoids an MCP client dependency. It does not
meet the requirement that the external service be consumed through MCP, and it
would create a second integration surface beside MCP. It is rejected.

### 3. Use one official-SDK MCP gateway controlled by MyPeople

A small Node CLI uses the official Model Context Protocol SDK and accepts one
bounded JSON request from the Python TaskSpec compiler. The compiler remains
the policy owner; engineers receive only compiled results. This introduces one
focused runtime dependency but avoids implementing the MCP transport manually
and preserves a single remote contract. This is the chosen approach.

## Phase A architecture

### 1. Priority-card project contract

The task schema adds:

```json
{
  "projectSlug": "mypeople",
  "contextQuestion": "Which verified constraints affect provider switching?"
}
```

`projectSlug` uses lowercase ASCII letters, digits, and single hyphens, with a
maximum length of 64 characters. Existing cards remain valid with an empty
project slug, but a card without a slug cannot request external memory or
compile a memory-enabled TaskSpec.

`contextQuestion` is optional and limited to 500 characters. Empty means no
memory lookup. The runtime must not derive hidden broad queries from the task
title.

The Priorities detail view exposes both fields. The server validates them and
the board migration adds empty values without inventing a project assignment.

### 2. ProjectProfile

Runtime profiles live under a configurable, non-Git state path. The default is
`run/project-profiles/<slug>.json`. A tracked example documents the schema but
does not contain local paths or credentials.

```json
{
  "schemaVersion": 1,
  "revision": 1,
  "slug": "mypeople",
  "repository": "https://github.com/example/project.git",
  "workingDirectory": "/workspace/project",
  "allowedBranches": ["main"],
  "contextFiles": ["README.md", "AGENTS.md"],
  "verificationCommands": ["python3 -m unittest discover -s verify"],
  "allowedActions": ["read", "edit", "test"],
  "forbiddenActions": ["deploy", "push", "delete"],
  "limits": {
    "contextChars": 6000,
    "memoryTopK": 3,
    "memoryHops": 0,
    "memoryTimeoutSeconds": 8
  },
  "memory": {
    "enabled": false,
    "serverUrl": "https://memory.example.invalid/mcp",
    "credentialRef": "env://MYPEOPLE_MEMORY_TOKEN"
  }
}
```

Validation rejects unknown schema versions, unsafe slugs, relative working
directories, shell metacharacters in verification commands, plaintext token
fields, non-HTTPS remote URLs outside explicit test mode, `memoryTopK` above 3,
and `memoryHops` above 0 during the read-only pilot.

`credentialRef` is a reference only. The profile loader never serializes the
resolved value into a TaskSpec, board, log, or error.

### 3. MemoryGateway

The gateway is a narrow command, not a daemon and not a second memory store.
The Python compiler invokes it with JSON over stdin:

```json
{
  "serverUrl": "https://memory.example.invalid/mcp",
  "projectSlug": "mypeople",
  "question": "Which verified constraints affect provider switching?",
  "topK": 3,
  "hops": 0,
  "timeoutSeconds": 8,
  "credentialEnv": "MYPEOPLE_MEMORY_TOKEN"
}
```

The Node gateway uses `@modelcontextprotocol/sdk` with Streamable HTTP and
calls only the remote `recall` tool in Phase A. It never accepts arbitrary MCP
tool names. Authentication is sent in the Authorization header and never in a
URL. The gateway closes the transport after each bounded request.

Successful output is normalized before returning to Python:

```json
{
  "claims": [
    {
      "id": "memory-id",
      "projectSlug": "mypeople",
      "content": "Point-in-time claim; verify before asserting.",
      "sourceUri": "task://card-id",
      "sourceType": "verified-task",
      "createdAt": 0,
      "updatedAt": 0,
      "status": "canonical"
    }
  ],
  "truncated": false
}
```

The gateway rejects a result whose `projectSlug` differs from the request,
whose provenance is absent, or whose content exceeds the caller's remaining
budget. Errors are typed as unavailable, unauthorized, timeout,
project-mismatch, invalid-response, or budget-exceeded. Errors never include
response bodies, tokens, or complete retrieved content.

### 4. TaskSpec compiler

The compiler loads the card and matching ProjectProfile, validates both, and
produces `run/taskspecs/<task-id>.json` using an atomic mode-0600 write.

```json
{
  "schemaVersion": 1,
  "taskId": "card-id",
  "projectSlug": "mypeople",
  "profileRevision": 1,
  "objective": "Repair provider switching",
  "acceptanceCriteria": "Focused and full verification pass",
  "repository": "https://github.com/example/project.git",
  "workingDirectory": "/workspace/project",
  "contextFiles": ["README.md", "AGENTS.md"],
  "verificationCommands": ["python3 -m unittest discover -s verify"],
  "allowedActions": ["read", "edit", "test"],
  "forbiddenActions": ["deploy", "push", "delete"],
  "evidencePolicy": "required",
  "memoryQuestion": "Which verified constraints affect provider switching?",
  "memoryClaims": [],
  "memoryStatus": "disabled",
  "compiledAt": 0
}
```

Memory is optional input. If memory is disabled or no question is present, the
TaskSpec compiles without a remote call. If the remote service is unavailable,
the default behavior is fail-closed for a card that explicitly requested
memory: no worker is started, and the Boss receives a concise retryable error.
The Boss may explicitly clear the context question and retry without memory;
the runtime never silently drops requested context.

The total serialized TaskSpec must not exceed `contextChars`. Local contract
fields take priority over memory. Memory claims are truncated or rejected
before any local acceptance criteria, permissions, verification commands, or
evidence requirements are removed.

### 5. Worker delivery

When `mp spawn --owner-task <id>` is used, MyPeople compiles the TaskSpec before
creating the provider process. The worker receives:

- `OWNER_TASK_ID` as today;
- `MYPEOPLE_TASKSPEC_PATH` pointing to the mode-0600 file;
- a short initial message instructing it to read that file before work.

The complete TaskSpec is not copied into global `AGENTS.md`, provider profile
metadata, or terminal history. Existing spawn behavior without `--owner-task`
is unchanged.

### 6. Observability

MyPeople records only bounded metadata:

- task ID and project slug;
- profile revision;
- memory status and typed error code;
- requested and returned claim counts;
- elapsed milliseconds;
- response characters;
- provider-reported AI consumption when available, otherwise `not_measured`.

No retrieved content or credential value is written to general runtime logs.
Task evidence may include a human-selected excerpt after verification.

## Phase B Cloudflare hardening contract

The fork must add mandatory project isolation to D1 and Vectorize. Required
entry fields are:

```text
project_slug, source_type, source_uri, task_id, repository, repo_commit,
created_by_agent, verified_by, verified_at, updated_at, content_hash,
valid_from, valid_until
```

All MCP memory tools require `projectSlug`. D1 queries include it in the WHERE
clause, contradiction and duplicate detection never cross it, graph edges
cannot cross it without a separate human-approved cross-project operation, and
Vectorize uses it as the namespace.

OAuth grants or service credentials carry an agent/service principal, allowed
projects, and `memory:read`, `memory:propose`, `memory:write`, or
`memory:admin` scopes. The MyPeople Phase C compiler receives read-only access
to the synthetic pilot projects. Query-string token authentication is removed.

The fork adds:

- versioned D1 migrations;
- a tested export/import round trip;
- deterministic Vectorize rebuild from D1;
- orphan-vector cleanup;
- rate and AI-budget limits;
- audit events containing principals and metadata but not memory content;
- explicit feature flags for insight synthesis, pattern derivation,
  compression, and integrations, all disabled in the pilot;
- a security policy and commit-pinned CI actions.

## Phase C evaluation and gates

The private sandbox uses at least 30 synthetic memories across three projects
with intentionally repeated names, technologies, and conflicting decisions.

Required gates:

- zero cross-project results and zero cross-project conflicts;
- provenance on 100 percent of returned claims;
- precision@3 of at least 0.80 on the approved query set;
- complete export/import/vector-rebuild recovery;
- direct recall p95 below 2 seconds;
- no unrestricted credential delivered to an engineer;
- no write from MyPeople during the read-only pilot;
- MCP call count, response characters, elapsed time, and Workers AI neurons
  reported per compiled TaskSpec;
- Cloudflare spend remains zero unless a separate paid-plan gate is approved.

Failure of any isolation, provenance, or restore gate blocks real data. Latency
or quality failures return the design to review. Cost failures require tighter
bounds or disabling AI enrichment; they do not silently authorize payment.

## Error handling and rollback

- Invalid cards or profiles fail before network access.
- Gateway timeout terminates the child process and returns a typed error.
- Unauthorized responses never trigger token fallback through a query string.
- Project mismatch discards the full response and emits a security event.
- Partial TaskSpec files are never visible because writes are atomic.
- A failed compile creates no worker and does not mutate the card state.
- Phase B migrations run against a fresh sandbox database before any existing
  deployment.
- Phase C rollback disconnects the gateway credential and removes only the
  synthetic Cloudflare sandbox; Project Factory and the live MyPeople board
  remain operational.

## Verification strategy

Phase A follows strict TDD:

- task migration and validation tests;
- ProjectProfile schema and secret-rejection tests;
- TaskSpec size, priority, atomic-write, and no-memory tests;
- fake MCP server tests for bounded recall, timeout, unauthorized response,
  malformed response, missing provenance, and project mismatch;
- spawn tests proving compile-before-process behavior and no worker on failure;
- browser contracts for editing project slug and context question;
- public-repository and secret scans;
- the complete existing MyPeople verifier.

Phase B reuses the upstream 599-test suite and adds isolation, scope,
provenance, restore, orphan cleanup, and feature-flag tests before modifying
production code. The exact reviewed upstream commit remains recorded.

Phase C uses synthetic state-diff tests and a written results artifact. No
result is accepted only from screenshots or model claims; every gate must have
a repeatable command or exported measurement.

## Acceptance criteria

1. A priority card can carry a validated project slug and optional context
   question without breaking legacy cards.
2. One versioned ProjectProfile compiles one bounded TaskSpec.
3. A worker with an owner task cannot start until its TaskSpec compiles.
4. The official-SDK gateway can call only `recall`, requires project identity,
   and rejects missing provenance or cross-project results.
5. No credential or retrieved content appears in Git, the board, general logs,
   provider profiles, or global agent instructions.
6. Memory-disabled tasks and cards without a context question make no network
   call.
7. The Cloudflare fork isolates D1, Vectorize, graph, duplicate detection, and
   contradiction handling by project.
8. Export/import/vector rebuild is verified before live data.
9. The synthetic Cloudflare pilot passes every isolation, provenance, quality,
   recovery, latency, and cost gate.
10. Real data, persistent writes, automatic capture, and paid Cloudflare usage
    remain blocked until a separate human approval.

