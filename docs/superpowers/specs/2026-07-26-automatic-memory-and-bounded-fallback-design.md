# Automatic Memory and Bounded Fallback Design

**Date:** 2026-07-26  
**Status:** Approved design, implementation pending  
**Scope:** `project-factory` only

## Goal

Promote the existing read-only hybrid Memory Gate B path from per-card manual
opt-in to automatic, bounded recall for Project Factory owner tasks. Recall must
improve historical continuity without adding another memory, blocking normal
execution, or injecting the complete board into a model prompt.

## Decisions

- Every Project Factory owner task gets a deterministic memory query compiled
  from its title/objective and acceptance criteria. Query compilation uses no
  model and consumes no provider tokens.
- Recall remains read-only, project-scoped, provenance-bearing, and capped at
  three injected claims.
- MyPeople uses the existing hybrid store and event sources. It does not adopt
  upstream `memory-dump.py`, create a board corpus, or add a second index.
- Memory is an execution aid, not a task prerequisite. Exhausted recovery
  returns a typed status and the worker continues with its normal TaskSpec.
- The feature is reversible without restarting Docker or losing task state.

## Automatic Query Contract

The compiler derives one normalized query from existing card fields in this
order:

1. objective/title;
2. acceptance criteria;
3. explicit context question, when supplied.

An explicit context question supplements the deterministic query; it does not
open a separate recall path. Empty, duplicate, and oversized fragments are
removed before recall. The compiled query is bounded and never includes
comments, credentials, provider transcripts, hidden reasoning, or proof binary
contents.

Only cards whose `projectSlug` is exactly `project-factory` are eligible.
Synthetic verifier cards and comparison baseline arms remain excluded unless
their existing test-only contract explicitly enables memory.

## Four-Level Recall

One coordinator owns the following ordered recovery ladder:

1. **Fast recall:** existing SQLite FTS5/top-k retrieval.
2. **Deep recall:** existing history/relationship traversal when fast evidence
   is insufficient.
3. **Bounded exhaustive fallback:** search the same store and events using
   expanded text, aliases, regex, temporal range, file, commit, task, agent, and
   event type filters. Refinements are successive and bounded; the model never
   receives the explored set.
4. **Local emergency access:** when the sidecar or normal transport is
   unavailable, a read-only local adapter queries the same locked dataset/store
   directly. It may create a temporary textual diagnostic view only in a
   private runtime directory, with strict limits and guaranteed removal. The
   view is never indexed or treated as a source of truth.

Each level stops as soon as evidence is sufficient. Every returned fragment
must identify its source event and original source URI. Conflicting evidence is
returned as conflict metadata rather than silently resolved.

## Fail-Open Boundary

If all levels fail, time out, exceed budget, or return inconsistent evidence,
the TaskSpec contains no memory claims and execution continues. The public
status is one of:

- `memory_applied`;
- `insufficient_evidence`;
- `memory_unavailable`;
- `memory_budget_exceeded`;
- `memory_invalid_response`.

The failure reason is visible in Priorities/HUD and the bounded event receipt.
No raw query, claim body, secret, complete session ID, or provider transcript is
written to public telemetry.

Memory failure never changes provider routing, model selection, task ownership,
approval requirements, or exact-session recovery.

## Budgets

Initial hard ceilings per task:

- injected claims: 3;
- estimated injected memory context: 300 tokens;
- total recall deadline across all levels: 2 seconds;
- exhaustive fallback activation: only after fast and deep insufficiency;
- exhaustive examined fragments: 100;
- exhaustive selected fragments: 3;
- local emergency temporary bytes: 256 KiB;
- one automatic recall attempt per TaskSpec compilation.

The existing measured examples ranged from approximately 14–18 estimated
tokens for minimal evidence and 236 estimated tokens for a complete
provenance-bearing TaskSpec delta. Provider tokens remain `not_measured` unless
the provider reports attributable counters.

## Runtime Controls and Rollback

Add one project-scoped control record with modes:

- `off`: no automatic recall;
- `automatic`: apply this design;
- `manual_canary`: preserve the current explicit-card behavior for diagnosis.

Changing `automatic` to `off` takes effect for the next TaskSpec compilation,
requires no Docker restart, and does not modify existing cards or compiled
historical TaskSpecs. Active workers retain their immutable TaskSpec.

If the local emergency adapter is disabled independently, levels 1–3 continue
normally. Disabling the complete memory control stops sidecar use and removes
ephemeral credentials using the existing cleanup transaction.

## Observability

For every attempted recall, record only bounded metadata:

- task/project and profile revision;
- selected level and escalation reasons;
- levels attempted;
- elapsed milliseconds;
- examined, returned, and injected fragment counts;
- response characters and estimated injected tokens;
- provider tokens when actually measurable;
- terminal memory status and provenance completeness.

The HUD shows current mode, sidecar/local-adapter health, last status, recall
latency, injected claims, estimated memory tokens, and measured provider tokens
or `not measured`.

## Safety and Data Ownership

- The hybrid memory remains the only operational memory.
- The board, Git history, task events, comments, commits, and proofs remain the
  original sources of truth.
- No automatic memory writes or learning promotion are included in this phase.
- No Cloudflare dependency, external API key, or public memory port is added.
- The current shared Linux identity limits this activation to the existing
  public Project Factory dataset until per-project private isolation is proven.
- Local emergency access uses read-only mounts and cannot mutate the dataset.

## Verification and Acceptance

Implementation uses TDD in an isolated worktree and a disposable Docker clone.
Acceptance requires:

1. deterministic query generation for cards with and without an explicit
   context question;
2. zero provider calls during query generation;
3. correct fast/deep/exhaustive/emergency ordering and early stop;
4. no exhaustive or emergency cost when an earlier level succeeds;
5. at most three fully sourced claims and at most 300 estimated tokens;
6. typed fail-open execution for unavailable, timeout, invalid, insufficient,
   and over-budget outcomes;
7. project isolation and baseline-arm exclusions;
8. telemetry contains no query text, claim body, credentials, or transcripts;
9. `automatic -> off` rollback without Docker restart or task mutation;
10. complete isolated verifier, browser journey, Gate B regression, provider
    session, routing, persistence, and J1–J52 contracts remain green.

Deployment occurs only after the candidate passes the disposable Docker gate
and a human approves the live transaction. The first live validation uses one
existing Project Factory card, compares its receipt to the prior baseline, and
then leaves automatic mode enabled only if no harmful result or operational
regression appears.

## Explicit Non-Goals

- automatic learning or memory writes;
- a full-board prompt or persistent corpus;
- Cloudflare or another hosted memory dependency;
- an LLM-generated retrieval question;
- automatic model/provider changes based on memory;
- private multi-project memory before identity isolation exists.
