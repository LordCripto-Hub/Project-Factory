# Boss Adaptive Routing Design

**Date:** 2026-07-18
**Status:** Approved

## Purpose

Add a deterministic, zero-model-call routing policy so Boss can select the
least expensive eligible Codex model for an owner task while respecting
project limits, explicit operator choices, and auditable escalation ceilings.

The task remains owned by Priorities. Routing chooses a worker configuration;
it does not move task authority into a provider conversation or agent process.

## Goals

- Classify owner tasks without spending inference tokens.
- Default routine work to the least expensive allowed model tier.
- Select a stronger tier only when explicit task signals justify it.
- Validate manual model choices against the same project policy.
- Persist a compact, deterministic routing decision and expose its reason on
  the task.
- Define retry and escalation ceilings without implementing an unbounded
  autonomous retry loop.
- Preserve the existing exact-session recovery and provider-profile contracts.

## Non-Goals

- No LLM-based task classification.
- No automatic provider or account switching.
- No Claude or mixed-provider execution in this phase.
- No HUD buttons or visual model controls.
- No automatic cross-model process replacement. This phase emits and enforces
  the bounded next-tier decision that a later lossless-switch workflow can use.
- No token-price calculator or claim of exact monetary cost when providers do
  not expose reliable usage and pricing metadata.

## Selected Approach

Use a pure Python routing engine with a versioned local policy document.

Two alternatives were rejected for this phase:

1. An LLM classifier would understand ambiguous language better, but it would
   spend tokens before useful work begins and make routing nondeterministic.
2. A hybrid rules-plus-LLM classifier would add two execution paths, more test
   surface, and fallback ambiguity before rules-only behavior has evidence.

The deterministic engine is inspectable, cheap, reproducible, and easy to
replace later if measured routing quality justifies a more expensive method.

## Components

### 1. Routing policy

Runtime configuration lives at `run/routing-policy.json`, overridable with
`MYPEOPLE_ROUTING_POLICY_PATH`. A sanitized example is committed as
`examples/routing-policy.example.json`.

The schema contains:

```json
{
  "schemaVersion": 1,
  "tiers": {
    "economy": {"model": "gpt-5.6-luna", "rank": 1},
    "standard": {"model": "gpt-5.6-terra", "rank": 2},
    "strong": {"model": "gpt-5.6-sol", "rank": 3}
  },
  "defaults": {
    "tier": "economy",
    "maxAutomaticTier": "standard",
    "maxAttempts": 2,
    "maxEscalations": 1
  },
  "projects": {
    "mypeople": {
      "allowedModels": ["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"],
      "maxAutomaticTier": "strong",
      "maxAttempts": 2,
      "maxEscalations": 1
    }
  }
}
```

The runtime file contains no credentials. Missing, malformed, or internally
inconsistent policy fails closed for owner-task auto-routing. Existing master,
Nightwatch, temporary, revive, and explicit non-owner workflows retain their
current behavior.

Project overrides select from the validated global tiers through a model
allowlist and stricter or explicitly configured ceilings. Unknown fields,
unknown tiers or models, negative budgets, duplicate ranks, and non-monotonic
tier ranks are rejected.

### 2. Deterministic classifier

Create `bin/task_routing.py` as a side-effect-free engine. Its public boundary
accepts a compiled TaskSpec, the validated policy, the effective provider
profile, and an optional requested model. It returns a decision or a typed
error.

Classification uses normalized TaskSpec fields:

- `objective`
- `acceptanceCriteria`
- `verificationCommands`
- `allowedActions`
- `forbiddenActions`
- `evidencePolicy`
- optional `routingHints` copied from the task card

Optional hints are:

```json
{
  "taskClass": "simple|implementation|critical",
  "risk": "low|medium|high",
  "maxTier": "economy|standard|strong"
}
```

Hints constrain classification but cannot bypass project policy. An explicit
`maxTier` is a ceiling, not a request to spend that tier.

Without hints, the engine computes stable reason codes from a small bilingual
English/Spanish vocabulary and structural signals:

- documentation, explanation, formatting, translation, and bounded review
  begin at `economy`;
- implementation, bug fix, refactor, API, database, Docker, or integration
  begin at `standard`;
- security, authentication, secrets, destructive migration, production
  deployment, payment, data-loss, rollback, or architecture-critical work
  requests `strong`;
- required evidence and multiple verification commands may raise risk but can
  never independently jump more than one tier;
- ambiguous input remains at the cheaper tier and records
  `insufficient_strong_signal` rather than guessing upward.

Signals produce named reason codes, not a hidden free-form score. Tier choice
is the maximum justified signal after applying task and project ceilings.
Rules are order-independent and tested in both languages.

### 3. Routing decision receipt

The engine returns a versioned record:

```json
{
  "schemaVersion": 1,
  "taskId": "task-123",
  "projectSlug": "mypeople",
  "taskClass": "implementation",
  "risk": "medium",
  "tier": "standard",
  "model": "gpt-5.6-terra",
  "providerProfile": "codex-primary",
  "selection": "automatic",
  "reasonCodes": ["implementation_signal", "project_policy_allowed"],
  "maxAttempts": 2,
  "maxEscalations": 1,
  "nextEligibleTier": "strong",
  "aiUsage": "none"
}
```

The canonical serialized record is written atomically to
`run/routing-decisions/<task-id>.json`. The roster stores its path and SHA-256
receipt alongside the selected tier/model. Session identifiers and credentials
are never included.

The decision timestamp, if needed for UI display, is stored outside the
canonical hash input so identical inputs produce identical decision hashes.

### 4. Spawn integration

For `mp spawn --owner-task <id>`:

1. Compile and validate the existing TaskSpec.
2. Resolve the provider profile without selecting the final worker model.
3. Load and validate routing policy.
4. Classify the task or validate the explicitly requested `--model`.
5. Persist the routing receipt atomically.
6. Record the receipt path/hash, tier, budget ceilings, and model in the roster.
7. Add one concise idempotent Priorities comment containing class, risk, tier,
   model, and reason codes.
8. Launch the worker with the selected model through the existing provider and
   exact-session machinery.

If `--model` is supplied, `selection` is `manual`. The model must be in the
project allowlist and its tier must not exceed the task/project ceiling. Manual
selection never bypasses policy. Boss receives a typed denial instead of a
silently substituted model.

For owner tasks with no `--model`, the current unconditional
`DEFAULT_ENG_MODEL` fallback is replaced by the routing result. Other spawn
paths keep their existing defaults to avoid changing unrelated lifecycle
behavior.

### 5. Escalation boundaries

The receipt records `maxAttempts`, `maxEscalations`, and `nextEligibleTier`.
This phase provides a pure `next_route(decision, failure)` operation that:

- accepts only typed failures such as `verification_failed`,
  `implementation_blocked`, or `model_capability_insufficient`;
- refuses escalation for provider exhaustion, authentication failure,
  infrastructure failure, missing context, or policy denial;
- advances at most one tier;
- refuses when the task ceiling, project ceiling, allowed-model list, attempt
  budget, or escalation budget would be exceeded;
- emits a new auditable decision without killing or restarting any process.

The future lossless-switch command will consume this output. Boss cannot spend
the escalation budget merely because a worker is slow or a provider is out of
quota.

## Error Handling

Typed public errors include:

- `routing_policy_missing`
- `routing_policy_invalid`
- `routing_project_missing`
- `routing_model_denied`
- `routing_tier_denied`
- `routing_task_invalid`
- `routing_budget_exhausted`
- `routing_failure_not_escalatable`

Errors contain no raw policy body, provider output, credentials, or stack trace
in Priorities comments. A failed route does not create a worker, partial
receipt, or roster mutation.

## Token And Cost Behavior

Classification performs no provider call and therefore consumes zero model
tokens. It reads bounded local JSON and TaskSpec data only.

Choosing a smaller model may reduce downstream cost, but exact savings remain
`not_measured` unless provider telemetry exposes actual usage. The policy
records ceilings and decisions; it does not invent price estimates.

## Compatibility

- Existing provider profiles remain the authentication and per-agent account
  boundary.
- Existing exact-session revive reuses the recorded model and routing receipt;
  it does not reclassify or spend another escalation.
- Provider-switch handoffs remain fresh-session operations when provider
  identity changes.
- Tasks without an owner, temporary agents, Boss, and Nightwatch are outside
  adaptive routing in this phase.
- Missing policy affects only new automatically routed owner workers and does
  not stop the MyPeople control plane.

## Verification

Focused tests must prove:

- economy is the default for simple and ambiguous tasks;
- English and Spanish implementation signals select `standard`;
- critical signals select `strong` only when policy permits it;
- task and project ceilings always win;
- explicit models are allowed or denied without substitution;
- provider-profile models absent from the routing allowlist are denied;
- identical inputs produce identical canonical receipts and hashes;
- receipts are atomic and contain no secret/session fields;
- one task receives one idempotent routing comment;
- failed routing creates no tmux worker or roster mutation;
- exact-session revive preserves the original decision and model;
- escalation advances one tier only for eligible typed failures and respects
  all budgets;
- existing spawn, provider-profile, TaskSpec, handoff, exact-session, and
  packaged verifier suites remain green.

## Rollout

1. Add the pure policy validator/classifier and RED/GREEN unit tests.
2. Add decision persistence and receipt tests.
3. Integrate owner-task spawn and idempotent task comments.
4. Add bounded next-route calculation without process mutation.
5. Run focused suites and the packaged isolated verifier.
6. Build a pinned image, perform the backup-first Docker transaction, and run a
   disposable live routing canary.
7. Publish through a reviewed GitHub PR only after all gates pass.

## Acceptance Criteria

- New owner workers without `--model` receive the cheapest policy-compliant
  model justified by deterministic task signals.
- Classification consumes zero provider tokens and records `aiUsage: none`.
- Manual model requests cannot bypass allowlists or tier ceilings.
- Every launched owner worker has a validated routing receipt bound by hash to
  its roster record.
- Routing failures are fail-closed and leave no partial worker state.
- Escalation calculation is bounded, typed, one-tier-at-a-time, and does not
  mutate processes in this phase.
- Existing exact-session recovery and shared MyPeople services remain intact.
