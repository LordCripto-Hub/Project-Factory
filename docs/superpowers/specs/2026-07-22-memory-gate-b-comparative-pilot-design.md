# Memory Gate B Low-Token Comparative Pilot

**Date:** 2026-07-22

**Status:** Approved design pending written-spec review

## Purpose

Measure whether bounded Project Factory memory improves real MyPeople worker
execution relative to the existing no-memory path. Both arms use the same task,
model tier, verification contract, and scoring rules while minimizing provider
use and preserving complete rollback.

This phase produces directional evidence from a small paired sample. It does
not claim statistical significance, enable memory globally, write memories,
deploy Cloudflare, or promote Gate B into the default runtime.

## Dependency And Branch Boundary

This design depends on pull request 10 (the provider-neutral isolated Gate B
experiment) and pull request 11 (the explicit active live-canary path).
Implementation lives on feat/memory-gate-b-comparison and targets
feat/memory-gate-b-live-canary as a third review unit.

## Approaches Considered

1. A ten-to-twenty-pair live comparison offers better statistical power but
   consumes too many provider tokens for the first comparison.
2. An offline-only comparison is cheap and deterministic but cannot show
   whether Boss and workers use the recovered evidence.
3. The selected hybrid pilot runs six deterministic offline cases, then three
   real paired tasks. It catches harness and scoring defects without provider
   cost before spending tokens on the smallest useful execution sample.

## Experiment Shape

The experiment has two ordered stages:

1. **Offline qualification:** six cases exercise TaskSpec compilation, recall
   relevance, no-recall controls, scoring, receipts, and deterministic replay.
2. **Paired worker pilot:** three qualified tasks each run twice, once without
   memory and once with Memory Gate B.

The paired stage uses six worker executions. All workers use gpt-5.6-luna, the
least expensive approved Codex tier for normal implementation work. No
model-based judge is used.

## Task Families

The six offline cases contain two cases from each family:

1. **Exact constraint:** identify a verified repository constraint and its
   supporting evidence.
2. **Temporal continuation:** determine what replaced an older procedure and
   which current verification applies.
3. **Contradiction prevention:** avoid a superseded or unsafe approach while
   selecting the current valid path.

The committed aliases are cmp-exact-01, cmp-exact-02, cmp-temporal-01,
cmp-temporal-02, cmp-contradiction-01, and cmp-contradiction-02. The three
aliases ending in 01 advance to the paired pilot. This selection is part of the
fixture and cannot change after offline results are produced.

Exactly one case from each family advances to the paired pilot. Selection is
fixed before any worker result is observed. Cases use only public Project
Factory history from the locked dataset, require read-only inspection and
focused verification, have closed gold evidence, avoid external effects, and
fit within one worker turn and one proof.

Raw task questions and gold answers remain private runtime fixtures. Public
artifacts contain only aliases, family labels, metrics, and verdicts.

## Pairing And Order Control

Each selected task has two arms:

- baseline: compile and execute the normal TaskSpec without memory;
- memory: compile and execute the same authoritative task with Gate B.

Task text, project, acceptance criteria, evidence policy, repository SHA,
verification commands, model, and worker role are identical. Only the bounded
memory context may differ.

Arm order is committed in advance:

| Case alias | First arm | Second arm |
|---|---|---|
| cmp-exact-01 | baseline | memory |
| cmp-temporal-01 | memory | baseline |
| cmp-contradiction-01 | baseline | memory |

Every arm uses a fresh worker and provider conversation. No transcript,
TaskSpec, proof, or answer from one arm is visible to the other.

Each arm uses a distinct synthetic card ID generated from the run ID, case
alias, and arm. Both cards are compiled from the same immutable task fixture;
the first card is removed and its worker retired before the second is created.

## Runtime Isolation

The offline stage runs in a disposable Docker fixture with no provider, no
external network, read-only source and dataset, and no production volume,
Docker socket, credential, or write tool.

The paired stage uses the reviewed live MyPeople path because it must measure
real Boss-to-worker execution. It runs sequentially only when the board has no
user-owned active work. Preflight records source and image identity, restart
count, runtime health, board count, owners, Boss/Nightwatch state, and absence
of prior canary resources.

Only test=true and memoryComparison=true cards may be created. At most one arm
is active. Each arm receives a fresh process and conversation.

## Memory Contract

The memory arm reuses the active-canary contract:

- project is exactly project-factory;
- recall is read-only, top-K is at most three, and graph hops are zero;
- local TaskSpec fields retain priority;
- every claim has validated provenance;
- one strict timeout and no automatic retry;
- workers receive compiled claims but no memory tool or credential.

The baseline arm makes zero recall calls and contains no memory claims or
cross-arm metadata.

## Deterministic Scoring

No LLM judge is used. Every case defines a private gold contract containing
accepted fact or decision identifiers, required provenance, forbidden
superseded identifiers, required verification commands, expected command exit
status, and a maximum unsupported-assertion count.

Each arm scores from 0 to 100:

- 40 points: decision correctness;
- 25 points: provenance;
- 20 points: required verification;
- 10 points: contradiction avoidance;
- 5 points: execution discipline and absence of unrelated changes.

Success requires at least 80 points and no safety or isolation violation. A
safety or wrong-project violation forces score zero and verdict harmful. The
scorer stores matched identifiers and numeric results, never private reasoning.

## Worker Result Contract

Each worker attaches one bounded machine-readable proof containing:

- the selected decision identifier;
- zero or more supporting evidence identifiers;
- zero or more rejected superseded identifiers;
- the required verification command identifiers and exit codes;
- a concise conclusion of at most 500 characters.

The scorer rejects unknown keys, excessive lengths, duplicate identifiers, and
identifiers outside the case vocabulary. Command results are cross-checked
against the independently captured execution receipt. The worker cannot set its
own score or verdict.

## Metrics

Every arm records:

- case alias, family, arm, and committed order;
- model, backend, and pseudonymized run-scoped session alias;
- TaskSpec characters and estimated TaskSpec tokens;
- memory claim count and retrieval latency;
- provider input/output/total tokens when attributable;
- token state: actual, estimated, or not_measured;
- wall-clock duration, tool calls when exposed, attempts, failed commands,
  retries, evidence count, and human interventions;
- score, success verdict, unsupported assertions, and dirty-state result.

Estimated TaskSpec tokens are never billed-token claims. If both arms do not
expose attributable provider counters, that pair cannot support a token-savings
claim.

## Comparison And Promotion Rule

Each pair reports score, success, duration, failures, retries, interventions,
context, and comparable-token deltas. Aggregates use medians and counts.
Percentages from three pairs are descriptive only.

The directional comparison passes only when:

1. all six offline cases pass and reproduce byte-identical sanitized receipts;
2. all three pairs complete both arms with evidence;
3. no memory arm is harmful and no isolation violation occurs;
4. memory succeeds on at least as many tasks as baseline;
5. median memory score is not lower than median baseline score;
6. at least one pair improves score or rework because of memory;
7. median retrieval latency is below 2,000 milliseconds;
8. median added context is no more than 300 estimated tokens;
9. rollback removes every synthetic card, worker, sidecar, network, secret
   volume, and token without restarting MyPeople;
10. actual, estimated, and not_measured token states remain honest.

Passing authorizes a larger statistical comparison design, not default memory.
A quality tie with no rework improvement is neutral. Any safety violation,
wrong-project evidence, or memory score regression of at least 20 points is
harmful and stops promotion.

## Failure Handling

Offline failure blocks all worker execution. In the paired stage:

- compilation failure preserves the card and records a typed reason;
- a provider failure may be retried once only if no answer was produced;
- a memory failure never silently becomes a baseline run;
- a failed arm never changes the task definition;
- unavailable token counters remain not_measured;
- unexpected user work pauses after the current arm and disables the canary;
- three failures in one subsystem stop the experiment for architecture review.

## Operator Flow

One explicit Windows launcher supports:

    Start-MyPeopleMemoryComparison.ps1 -Action Preflight
    Start-MyPeopleMemoryComparison.ps1 -Action Offline
    Start-MyPeopleMemoryComparison.ps1 -Action Paired
    Start-MyPeopleMemoryComparison.ps1 -Action Status
    Start-MyPeopleMemoryComparison.ps1 -Action Cleanup
    Start-MyPeopleMemoryComparison.ps1 -Action Report

Paired requires an offline receipt bound to the same source, dataset, fixture,
and scorer SHAs plus an explicit ConfirmLiveRun switch. No default startup
path invokes it. Cleanup is idempotent and removes only resources and cards
bearing the comparison run ID.

## Artifacts And Privacy

Private runtime artifacts contain fixtures, gold contracts, outputs, TaskSpecs,
internal receipts, and exact session attribution.

Public output consists of comparison-receipt.json and comparison-report.md
under experiments/memory-gate-b/artifacts, with exact software identities,
aliases, numeric metrics, verdicts, and rollback evidence.

Public output excludes questions, claims, gold answers, complete session IDs,
account identity, local paths, credentials, transcripts, and private reasoning.

## Verification Strategy

Implementation follows test-driven development:

1. fixture and gold-contract validation;
2. deterministic selection and arm-order tests;
3. scorer tests, including forced-zero safety violations;
4. offline baseline/memory isolation and byte-reproduction tests;
5. receipt, token-honesty, and sanitation tests;
6. state-machine tests for every launcher action;
7. disposable Docker E2E with fake workers and partial failures;
8. Linux and Windows focused contracts;
9. six-case offline qualification;
10. three-pair live run;
11. final cleanup and unchanged-runtime health verification.

## Success Criteria

The phase is complete when the offline stage reproduces, all live pairs have
closed scores and verdicts, the promotion rule is evaluated automatically,
token states are explicit, board and runtime return to preflight state, the
sanitized English evidence is committed, and a draft PR targets the live-canary
branch.

## Explicit Non-Goals

- No statistical significance claim from three pairs.
- No memory writes, learning consolidation, or preventive guardrails.
- No Cloudflare deployment or hosted MCP credential.
- No private ObsidianBrain or Engram content.
- No model-based evaluator.
- No code-generation, publication, or deployment task in the task set.
- No multiple-provider or multiple-model comparison.
- No global memory activation, automatic merge, or promotion.
