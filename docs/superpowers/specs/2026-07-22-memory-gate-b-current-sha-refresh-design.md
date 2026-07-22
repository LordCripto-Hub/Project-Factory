# Memory Gate B Current-SHA Refresh Design

## Goal

Refresh the controlled MyPeople memory comparison against the exact Project
Factory revision currently mounted in the live MyPeople workspace:
`039a62988625369f3f86c055cd476b0080395daa`.

The refresh must produce new immutable evidence. It must not overwrite or
reinterpret the existing dataset bound to
`80dce6f866329b79061bb1ed6b0594f9fdf2dd45`.

## Selected Approach

Use the live workspace SHA as the source boundary. Export only committed public
Git history from that revision, generate a new dataset directory whose name
contains its short SHA, and create a new dataset lock. Keep the previous corpus,
lock, offline receipt, and comparison results as historical evidence.

Using `origin/main` was rejected because it can differ from the runtime being
measured. Updating the live workspace before generation was rejected because it
would introduce an unrelated mutation and move the target again.

## Data And Case Refresh

1. Verify that the live workspace is clean and resolves exactly to the approved
   SHA.
2. Reuse the existing deterministic history-dataset generator from the prior
   benchmark sandbox or repository tooling. Do not hand-author history events.
3. Write the new corpus to
   `datasets/project-factory-history-039a62988625/`.
4. Generate a separate content lock for the new corpus.
5. Select six gold cases from the new corpus: two exact constraints, two
   temporal continuations, and two contradiction-prevention cases.
6. Preserve the approved live subset and counterbalanced arm order: one case
   per class, six total arms.
7. Every case must resolve only to evidence present in the new locked corpus.

Question text and gold evidence remain private runtime inputs. Public fixtures
contain aliases, question IDs, decision IDs, approved evidence IDs, rejected
evidence IDs, and verification-command IDs only.

## Qualification

Run the offline comparison twice. Both executions must match on fixture hash,
logical digest, pass/fail result, selected and rejected evidence IDs, and
escalation decisions. Whole-file hashes may differ only because retrieval
latency is an actual observation.

Qualification requires:

- six of six cases pass;
- zero harmful or wrong-project evidence;
- bounded top-three retrieval;
- explicit actual, estimated, and `not_measured` metric labels;
- public sanitation tests pass;
- the old dataset and report remain byte-identical.

## Runtime And Docker Flow

The Windows comparison launcher and preflight will be updated to bind the new
dataset name, source SHA, fixture hash, logical digest, and real case questions.
The live runtime is upgraded only through the existing backup-first image
transaction. The comparison feature flag remains opt-in and memory remains off
by default outside the bounded pilot.

Before the live pairs start, preflight requires:

- exact workspace SHA match;
- healthy Priorities and HUD;
- provider availability;
- the comparison API enabled only for the pilot;
- memory sidecar and credential lifecycle ready;
- zero existing comparison cards, workers, conversations, or temp artifacts;
- an unchanged container restart count baseline.

## Live Comparison

Execute three paired cases with `gpt-5.6-luna` for all six arms. Every arm gets
a fresh card, worker, provider conversation, and temporary result directory.
The baseline arm receives no memory block. The memory arm receives only the
bounded approved block. Cleanup is verified before the next arm starts.

Stop immediately on harmful output, provider failure, timeout, score refusal,
wrong-project evidence, resource reuse, cleanup failure, or container restart.
Do not selectively rerun failed pairs or tune the scorer after observing live
results.

## Outputs And Promotion Boundary

Public outputs are a sanitized current-SHA offline receipt and, only after a
successful live run, a sanitized paired-live report. They exclude credentials,
provider transcripts, raw prompts, private reasoning, local user paths, and
complete session identifiers.

Passing the three pairs authorizes designing a larger statistical experiment.
It does not enable memory globally and does not by itself prove a durable
production improvement.

## Verification

- dataset integrity and old-evidence preservation tests;
- fixture, scoring, offline, runtime, API, Windows, E2E, and sanitation tests;
- host-level disposable Docker lifecycle;
- complete isolated MyPeople suite including J1-J52;
- live preflight, paired execution, cleanup, and unchanged restart count;
- `git diff --check` and clean public-repository sanitation.
