# MyPeople Minimal Architecture

## Decision

MyPeople remains an execution and coordination plane. It does not duplicate a knowledge vault, an operational memory database, or the invisible history of a provider session.

The rule is simple: one capability, one owner.

| Capability | Owner |
|---|---|
| Project source and configuration | Git |
| Operational task and agent state | MyPeople |
| Durable, auditable knowledge | An optional project knowledge source |
| Fast cross-session recall | An optional retrieval service |
| Immediate reasoning and conversation history | The provider session, ephemeral |
| Context delivered to a worker | One bounded, compiled `TaskSpec` |

## Recommended context flow

1. A card identifies the project slug and objective.
2. MyPeople loads one versioned `ProjectProfile` for that project.
3. A compiler produces a short `TaskSpec` containing the repository, objective, acceptance criteria, relevant files, verification commands, permissions, and limits.
4. The worker receives only that `TaskSpec` and the files required for the task.
5. `mp complete` attaches a summary and verification, moves the card to review, and notifies the Boss.
6. Boss or CEO verifies and integrates. A worker cannot close its own task.

An external knowledge system may be one input to the compiler, but it is not a mandatory runtime dependency. A retrieval service may answer a specific question when requested by the `TaskSpec`. Tasks do not query multiple memory systems and complete provider history by default.

## Minimal patterns worth adopting

### 1. Persistence before additional intelligence

- External volumes for runtime state, provider sessions, and recordings.
- Verified backup and restore.
- Reproducible container startup.
- A public, sanitized repository for the installable product.

### 2. Small `ProjectProfile`

Recommended fields:

- slug and repository
- working directory
- allowed branches
- verification commands
- authorized context files
- time, retry, and cost limits
- actions requiring approval
- secret references, never secret values

Do not duplicate the same context as separate briefs, packs, registries, and profiles. Compile one effective profile.

### 3. One `TaskSpec`

Each work item needs:

- objective and acceptance criteria
- project slug
- relevant paths and context
- test commands
- allowed and forbidden actions
- required evidence
- budget and stop condition

Recipes and templates are presets for this same contract, not parallel task systems.

### 4. Handoff and evidence

Already implemented:

- `mp complete` requires a summary and at least one proof.
- It moves the card to review with `verified=false`.
- It notifies the Boss.
- Boss or CEO retains closure authority.

The server also rejects completion without required evidence and authorized review.

### 5. Concurrency only when required

Add an atomic lease, TTL, and heartbeat when several workers can touch the same project. Keep one integration owner responsible for promoting changes.

## Patterns not adopted

- A complete knowledge vault inside MyPeople.
- Another canonical vector database.
- A parallel planning or dashboard runtime.
- Silent capture of every conversation.
- Automatic recall every few messages.
- Duplicate task schemas, locks, or event logs.
- Prompt self-modification without human review.

Hybrid search, deduplication, and graph indexes may be tested later as rebuildable indexes. They must never become a second source of truth without evidence that they reduce total cost or risk.

## Current failure decisions

- Transient queue: acceptable for ephemeral messages when the board, `TaskSpec`, and critical events are durable and idempotent.
- Provider conversation resume: use explicit handoffs first; session resume may be added later without depending on invisible history.
- PID 1 and zombies: introduce an init process only after volumes and backup/restore are proven.
- Ports: bind to localhost by default and expose writable terminals only through an explicit decision.
- Verifier: run the destructive/full journey in isolation from active board work.
- Workers: use isolated checkouts and promote changes only after review.

## Token discipline

MyPeople never retrieves memory by habit. Every lookup answers a concrete question and has a bound. The worker's only automatic context input is the compiled `TaskSpec`.