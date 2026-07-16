# Upstream MyPeople Implementation Review

## Scope

This document records a read-only reverse-engineering review of
[delattre1/mypeople](https://github.com/delattre1/mypeople) and compares it
with Project Factory. The upstream baseline was commit
[862803c](https://github.com/delattre1/mypeople/tree/862803c8fed62dbb11c285f89587b0ceffdbc95b),
tag distance `v0.4.0-2`, reviewed on 2026-07-16.

No upstream code was copied. The upstream repository did not declare a license
at the reviewed revision, so this review extracts architectural patterns only.

## Executive decision

Project Factory should not replace its runtime with upstream MyPeople and
should not import the full upstream role framework. Project Factory is already
stronger in project-scoped context, durable control commands, evidence,
provider profiles, transactional switching, Git publication controls, Docker
persistence, loopback networking, and Windows operation.

The smallest useful adoption is:

1. mount a small versioned role contract outside project worktrees;
2. record doctrine and TaskSpec digests;
3. derive and validate worker cwd from TaskSpec;
4. resume exact provider sessions and distinguish deliberate stops from crashes;
5. reconcile workers with bounded retries and zombie handling;
6. make terminal recording opt-in; and
7. expose a product version on every UI page.

SQLite remains an experiment, not an immediate migration.

## Architecture comparison

| Domain | Upstream | Project Factory | Decision |
| --- | --- | --- | --- |
| Startup | Installable Python package, first-run flow, public image | Pinned Docker deployment, Windows shortcut, provider and memory rehydration, Ready-degraded mode | Keep local; improve distribution later |
| Supervision | Fleet reconciliation, deliberate-stop state, zombie reaping | Clean PID ownership and shutdown, Boss and Nightwatch supervision | Add bounded fleet reconciliation |
| Sessions | Provider session IDs and exact resume | Transactional provider profile switching with sanitized handoff, but fresh process revival | Add exact resume without losing local switching |
| Roles | Versioned registry, profiles, skills, policies, hooksets, digests | Generated Boss/Nightwatch doctrine plus a minimal worker contract | Adopt only a small backend-neutral bundle |
| Task context | Board, role, environment, transcript | ProjectProfile, TaskSpec, context limits, claims with provenance, verification and permission boundaries | Keep local |
| Board | SQLite WAL/FULL with reversible JSON migration | Atomic JSON, backups, shrink quarantine and Git export | Benchmark before changing |
| Queue | In-memory transient commands | Durable journal with uncertain delivery and explicit retry | Keep local |
| Git | Board backup only | Persistent workspace, worker push denial, SHA-bound approval and host-brokered draft PR | Keep local |
| Network | Ports exposed on all interfaces by default | Loopback-only local default, optional remote profile | Keep local |
| Verification | Broad Python and browser coverage | Broader isolated, Windows, Docker, provider and browser contracts | Keep local |

## How upstream agents are instructed

The reviewed upstream revision has no repository-root `AGENTS.md` or
`CLAUDE.md`. Its runtime doctrine is assembled from:

- [role registry](https://github.com/delattre1/mypeople/blob/862803c8fed62dbb11c285f89587b0ceffdbc95b/mypeople/runtime/roles/registry.json);
- versioned Boss and engineer profiles;
- personalities and skills under `mypeople/runtime/roles`;
- policies, toolsets and lifecycle hooksets; and
- [mprole.py](https://github.com/delattre1/mypeople/blob/862803c8fed62dbb11c285f89587b0ceffdbc95b/mypeople/runtime/bin/mprole.py).

`mprole.py` validates references, resolves the role bundle, calculates digests,
materializes one view per agent, creates an attestation, and adapts the same
role to Claude, Codex, or Grok. This is the strongest reusable upstream pattern:
instructions are an explicit, reproducible artifact rather than an incidental
file in the target repository.

The role bundle is not a substitute for ProjectProfile or TaskSpec. Identity,
authority and lifecycle belong in the role bundle. Repository, cwd, acceptance
criteria, verification, permissions and bounded memory belong in TaskSpec.

## Local instruction gaps found

### P0: doctrine drift

`boss-CLAUDE.md` and `plans/boss-claude.md` are both treated as authorities but
are not identical. One canonical source plus generated backend views is needed.

### P0: worker cwd can diverge from TaskSpec

TaskSpec carries `workingDirectory`, but a worker can still start in a fallback
runtime directory when Boss omits `--cwd`. The runtime must derive cwd from the
compiled TaskSpec and reject a conflicting explicit cwd.

### P0: runtime doctrine can dirty the product worktree

The current Codex worker bootstrap may create or append `AGENTS.md` inside the
assigned checkout. That can dirty the worktree, block the publisher, or leak
runtime doctrine into product commits. MyPeople doctrine must be mounted from
runtime state without modifying a repository-owned `AGENTS.md`.

### P0: Claude and Codex worker doctrine are not equivalent

The generated worker contract is Codex-oriented. Claude workers are told to
read `CLAUDE.md`, but the same contract is not materialized for them. One
backend-neutral source must render equivalent Claude and Codex instructions.

### P1: no context receipt

Roster and HUD do not show doctrine version, doctrine digest, TaskSpec digest,
ProjectProfile revision, or whether required context files were loaded. These
receipts should be metadata, not repeated prompt prose.

### P1: prompt declarations are not enforcement

TaskSpec includes verification commands and forbidden actions, but most fields
remain instruction-level declarations. Security-critical boundaries should be
enforced by runtime or broker code where practical, as Git publication already
is.

## Upstream patterns worth adopting

### Exact session resume

Upstream persists provider session IDs, validates transcript availability, and
uses provider-native resume commands. Project Factory currently revives a new
process with preserved configuration and a public handoff, not the exact
conversation. Exact resume should be attempted first, with an explicit and
visible fallback only when the operator or policy allows it.

### Deliberate stop versus crash

Upstream records operator intent so a supervisor does not immediately revive a
deliberately killed Boss. Project Factory should add a per-agent tombstone or
desired-state field. The global provider pause marker solves a different
problem and should remain separate.

### Bounded reconciliation and zombie recovery

Upstream reconciles roster state with tmux state, waits for startup readiness,
and limits retries for agents that never establish a session. Project Factory
should add those checks to its existing supervisor rather than install another
daemon.

### Recorder opt-in

Upstream made terminal recording opt-in after read-only clients could leave
panes in a bad state. Project Factory currently starts a recorder for every
spawn. Recording should be explicit and observable.

### Version visibility

Upstream renders the running version on each UI page. Project Factory should
derive one version from the packaged source and expose it in health and UI
surfaces.

### Reversible SQLite experiment

Upstream uses SQLite WAL, `synchronous=FULL`, immediate transactions, indexes,
and a reversible JSON-to-SQLite migration with deep comparison. Project
Factory should first benchmark a copied, non-sensitive board and prove rollback.
Its current atomic JSON store is adequate until evidence shows a real limit.

## Patterns rejected

- Do not expose Priorities, HUD or writable ttyd on every network interface by
  default.
- Do not treat a browser visit and self-issued cookie as sufficient remote
  authentication.
- Do not copy policies that are hashed but not enforced.
- Do not silently report a fresh spawn as successful session recovery.
- Do not mutate host Claude, Codex or tmux configuration during first run.
- Do not add another model provider until a real need and isolated test exist.
- Do not copy the upstream fresh-Boss UI flow at this revision: its queue path
  omits the role required by the spawn contract.

## Prioritized implementation backlog

### P0-A: backend-neutral doctrine bundle

Acceptance:

- one canonical Boss, Nightwatch and worker contract;
- version and digest stored per agent;
- equivalent Claude and Codex rendering;
- runtime files live outside project worktrees;
- repository-owned `AGENTS.md` and `CLAUDE.md` remain untouched; and
- HUD exposes compact doctrine and TaskSpec receipts.

### P0-B: TaskSpec cwd enforcement

Acceptance:

- owner spawn derives cwd from the compiled TaskSpec;
- a conflicting `--cwd` fails before tmux creation;
- the resolved path must remain inside the declared project workspace; and
- an end-to-end test proves the worker starts in the correct repository.

### P0-C: lossless model switching

Acceptance:

- persist provider session ID and transcript reference;
- exact resume is attempted before fresh spawn;
- deliberate stop is distinct from crash;
- fallback creates a visible handoff and never claims exact recovery; and
- an end-to-end test switches model while preserving the same task and evidence.

### P1-A: bounded fleet reconciliation

Acceptance:

- reconcile roster, desired state and tmux state;
- cap retries and surface terminal failure;
- prevent duplicate Boss or Nightwatch ownership;
- clean orphan startup processes safely; and
- preserve provider pause and switch locks.

### P1-B: recorder and version hygiene

Acceptance:

- recorder is opt-in with visible state and cleanup;
- one packaged version appears in health, Priorities and HUD; and
- both features have isolated regression tests.

### P2: board-store experiment

Acceptance:

- copied non-sensitive fixture only;
- JSON and SQLite results deep-compare;
- load and churn measurements are recorded;
- migration rollback is proven; and
- adoption requires evidence of lower risk or operational cost.

## Token-cost effect

These are design targets, not measured provider usage:

| Change | Expected token effect |
| --- | --- |
| TaskSpec cwd enforcement | None; runtime validation only |
| Doctrine digest and receipts | Negligible metadata |
| Small shared worker contract | Cap at roughly 700 input tokens per fresh spawn |
| Exact session resume | Neutral to reducing; avoids repeated reconstruction and handoff prompts |
| Desired state and reconciliation | None; supervisor logic only |
| Recorder, version stamp and SQLite | None |

The bundle must stay small. ProjectProfile, TaskSpec, board state and provider
session history remain the existing sources of truth; the role bundle must not
duplicate them.

## Recommended sequence

1. Fix cwd enforcement and stop writing doctrine into project worktrees.
2. Unify role doctrine and add backend parity plus digests.
3. Add exact resume and deliberate-stop state.
4. Add bounded reconciliation.
5. Add recorder opt-in and version visibility.
6. Run the SQLite experiment only after the lifecycle invariants are stable.

