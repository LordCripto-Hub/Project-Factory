# Memory Gate B Comparative Pilot Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task by task with review checkpoints.

**Goal:** Compare MyPeople task execution with and without the existing read-only hybrid memory path, using a low-token deterministic pilot that is isolated, reversible, and incapable of enabling memory globally.

**Architecture:** A committed six-case fixture and deterministic scorer drive offline qualification. A private run-state module and authenticated test-only API coordinate three paired live comparisons. Each arm gets a fresh worker, provider conversation, and synthetic card; only the memory arm receives the bounded TaskSpec memory block. Public receipts contain aggregate metrics and evidence identifiers, never raw private prompts, credentials, or provider conversations.

**Tech Stack:** Python 3 standard library, existing MyPeople HTTP server and CLI, PowerShell, Docker Compose, JSON/JSONL, `unittest`.

**Approved design:** `docs/superpowers/specs/2026-07-22-memory-gate-b-comparative-pilot-design.md`

---

## Global constraints

- Work only on `feat/memory-gate-b-comparison`, based on `feat/memory-gate-b-live-canary`.
- Do not enable memory globally, write memories, use Cloudflare, or alter normal cards.
- Do not reuse workers, conversations, or cards between arms.
- Use `gpt-5.6-luna` for every live arm.
- Keep provider token metrics `not_measured` unless the provider returns actual usage.
- Estimate memory tokens only with the documented deterministic estimator.
- Stop and clean up on any safety/isolation failure.
- Public repository content remains English-only and sanitized.
- Make each implementation task test-first and commit after its focused verification passes.

## Fixed experiment matrix

| Alias | Dataset question | Class | Live | Order |
|---|---|---|---|---|
| `cmp-exact-01` | `hist-exact-005` | exact constraint | yes | baseline → memory |
| `cmp-exact-02` | `hist-exact-006` | exact constraint | no | — |
| `cmp-temporal-01` | `hist-temporal-006` | temporal continuation | yes | memory → baseline |
| `cmp-temporal-02` | `hist-temporal-004` | temporal continuation | no | — |
| `cmp-contradiction-01` | `hist-contradiction-004` | contradiction prevention | yes | baseline → memory |
| `cmp-contradiction-02` | `hist-contradiction-002` | contradiction prevention | no | — |

The fixture stores identifiers, evaluation requirements, allowed evidence IDs, rejected evidence IDs, verification commands, order, and public-safe metadata. It must not duplicate raw question or gold-answer text already present in the locked dataset.

---

### Task 1: Lock the six comparison cases

**Files:**

- Create: `experiments/memory-gate-b/comparison/__init__.py`
- Create: `experiments/memory-gate-b/comparison/cases.json`
- Create: `experiments/memory-gate-b/comparison/contracts.py`
- Create: `verify/test_memory_comparison_fixtures.py`

**Step 1: Write the failing fixture contract test**

Test that:

- exactly six aliases exist;
- the dataset question IDs match the approved matrix;
- every case has one of the three approved classes;
- exactly three cases have `live: true`;
- live order matches the table;
- each case resolves against `datasets/project-factory-history-80dce6f86632`;
- no raw prompt, answer, credential, or absolute host path is copied into `cases.json`.

Run:

~~~powershell
python verify\test_memory_comparison_fixtures.py
~~~

Expected: FAIL because the fixture and loader do not exist.

**Step 2: Add the minimal fixture and loader**

Implement typed validation helpers in `contracts.py`:

- `load_cases(path, dataset_root)`
- `validate_case(case, dataset_questions)`
- `live_cases(cases)`

Reject duplicate aliases/question IDs, unknown classes/arms/orders, missing evidence requirements, and dataset mismatch.

**Step 3: Run focused tests**

~~~powershell
python verify\test_memory_comparison_fixtures.py
~~~

Expected: PASS.

**Step 4: Commit**

~~~powershell
git add experiments/memory-gate-b/comparison verify/test_memory_comparison_fixtures.py
git commit -m "test: lock Gate B comparison cases"
~~~

---

### Task 2: Implement closed worker-result validation and deterministic scoring

**Files:**

- Create: `experiments/memory-gate-b/comparison/scoring.py`
- Create: `verify/test_memory_comparison_scoring.py`

**Step 1: Write failing unit tests**

Cover a result envelope containing only:

- `decision_id`
- `selected_evidence_ids`
- `rejected_evidence_ids`
- `commands` with stable ID and integer exit code
- `conclusion` limited to 500 characters

Test the 100-point rubric:

- correctness: 40
- provenance: 25
- verification: 20
- contradiction avoidance: 10
- discipline: 5

Also test:

- score `>= 80` is successful only without safety/isolation violations;
- wrong-project evidence, forbidden action, or isolation breach forces score 0 and `harmful: true`;
- missing fields fail closed;
- extra narrative/provider transcript fields are rejected;
- scoring the same envelope twice yields byte-identical canonical JSON.

Run and confirm failure:

~~~powershell
python verify\test_memory_comparison_scoring.py
~~~

**Step 2: Implement the scorer**

Add pure functions:

- `validate_result_envelope(case, result)`
- `score_result(case, result)`
- `canonical_score_receipt(score)`

No LLM judge, network call, mutable global, or current-time input is permitted in scoring.

**Step 3: Verify and commit**

~~~powershell
python verify\test_memory_comparison_scoring.py
git add experiments/memory-gate-b/comparison/scoring.py verify/test_memory_comparison_scoring.py
git commit -m "feat: add deterministic Gate B comparison scorer"
~~~

---

### Task 3: Build the six-case offline qualification runner

**Files:**

- Create: `experiments/memory-gate-b/comparison/offline.py`
- Create: `experiments/memory-gate-b/scripts/run_memory_comparison_offline.py`
- Create: `verify/test_memory_comparison_offline.py`

**Step 1: Write failing tests**

Use the locked dataset and existing `taskspec_gate.py` retrieval path. Assert:

- all six cases run;
- each run is reproducible;
- retrieved evidence IDs satisfy the fixture contract;
- escalation count stays at or below the existing bound;
- retrieval latency and estimated injected tokens are recorded;
- output contains no raw source bodies, prompts, absolute private paths, or secrets.

Run:

~~~powershell
python verify\test_memory_comparison_offline.py
~~~

**Step 2: Implement the runner**

Produce a canonical JSON receipt with:

- dataset SHA/name;
- fixture version;
- per-case alias, class, retrieval mode, selected/rejected evidence IDs;
- latency milliseconds;
- estimated memory-context tokens;
- aggregate pass/fail and medians.

The CLI accepts explicit dataset, fixture, and output paths. It must refuse the preliminary dataset directory.

**Step 3: Verify deterministic reproduction**

~~~powershell
python verify\test_memory_comparison_offline.py
python experiments\memory-gate-b\scripts\run_memory_comparison_offline.py --dataset experiments\memory-gate-b\datasets\project-factory-history-80dce6f86632 --cases experiments\memory-gate-b\comparison\cases.json --output C:\tmp\memory-comparison-offline-a.json
python experiments\memory-gate-b\scripts\run_memory_comparison_offline.py --dataset experiments\memory-gate-b\datasets\project-factory-history-80dce6f86632 --cases experiments\memory-gate-b\comparison\cases.json --output C:\tmp\memory-comparison-offline-b.json
Get-FileHash C:\tmp\memory-comparison-offline-a.json,C:\tmp\memory-comparison-offline-b.json -Algorithm SHA256
~~~

Expected: tests pass and hashes match.

**Step 4: Commit**

~~~powershell
git add experiments/memory-gate-b/comparison experiments/memory-gate-b/scripts/run_memory_comparison_offline.py verify/test_memory_comparison_offline.py
git commit -m "feat: qualify Gate B comparison cases offline"
~~~

---

### Task 4: Add an isolated comparison-card marker

**Files:**

- Modify: `bin/todo-server.py`
- Modify: `verify/test_task_project_fields.py`
- Create: `verify/test_memory_comparison_cards.py`

**Step 1: Write failing API contract tests**

Test that a comparison card can be created only when all are true:

- authenticated internal request;
- explicit experiment ID, case alias, arm, and cleanup deadline;
- project identity matches the configured Project Factory test project;
- server-side comparison feature flag is enabled.

Test that normal card requests cannot set or inherit comparison fields and remain byte-compatible with existing behavior.

**Step 2: Implement the smallest server change**

Add a namespaced metadata object, for example `experiment.memory_comparison`, without changing normal TaskSpec construction. Reject unknown fields, expired deadlines, invalid arm names, and reuse of an experiment/card identity.

**Step 3: Verify regressions and commit**

~~~powershell
python verify\test_memory_comparison_cards.py
python verify\test_task_project_fields.py
git add bin/todo-server.py verify/test_task_project_fields.py verify/test_memory_comparison_cards.py
git commit -m "feat: isolate Gate B comparison cards"
~~~

---

### Task 5: Implement private run state, event ledger, and aggregation

**Files:**

- Create: `bin/memory_comparison.py`
- Create: `verify/test_memory_comparison_runtime.py`

**Step 1: Write failing state-machine tests**

Cover transitions:

~~~text
planned -> offline_qualified -> arm_started -> arm_recorded
-> arm_cleaned -> pair_completed -> completed
~~~

Any violation transitions to `aborted`, requires cleanup, and blocks further starts. Assert:

- append-only JSONL events;
- atomic current-state snapshots;
- one active arm maximum;
- no worker/card/conversation reuse;
- configured arm order enforced;
- cleanup evidence required before the paired arm starts;
- only aggregate/public-safe fields can be exported.

**Step 2: Implement pure state helpers**

Add:

- `start_run`
- `record_offline_qualification`
- `start_arm`
- `record_arm_result`
- `record_cleanup`
- `complete_pair`
- `complete_run`
- `abort_run`
- `build_public_summary`

Store private runtime data under the existing ignored runtime root. Never store credentials or raw provider conversation content.

**Step 3: Verify and commit**

~~~powershell
python verify\test_memory_comparison_runtime.py
git add bin/memory_comparison.py verify/test_memory_comparison_runtime.py
git commit -m "feat: add Gate B comparison run state"
~~~

---

### Task 6: Expose authenticated internal API and CLI commands

**Files:**

- Modify: `bin/todo-server.py`
- Modify: `bin/mp`
- Create: `verify/test_memory_comparison_api.py`

**Step 1: Write failing API/CLI tests**

Test authenticated, localhost/internal-only commands for:

- initialize/status/abort comparison run;
- start an approved arm;
- submit the closed result envelope;
- confirm cleanup;
- export public-safe summary.

Assert denial for missing/invalid auth, normal cards, unknown aliases, reordered arms, reused resources, and any request attempting global activation or memory writes.

**Step 2: Implement narrow routes and CLI wrappers**

Route all mutations through `memory_comparison.py`. The CLI prints compact JSON and non-zero exit codes on refusal. Do not expose raw prompts, retrieved source bodies, or provider session material.

**Step 3: Verify and commit**

~~~powershell
python verify\test_memory_comparison_api.py
python verify\test_codex_message_submit.py
git add bin/todo-server.py bin/mp verify/test_memory_comparison_api.py
git commit -m "feat: add controlled Gate B comparison API"
~~~

---

### Task 7: Add the Windows paired-run state machine

**Files:**

- Create: `windows/Start-MyPeopleMemoryComparison.ps1`
- Create: `verify/test_windows_memory_comparison.py`

**Step 1: Write failing source-contract tests**

Require the script to:

- default to dry-run;
- require explicit `-Execute` and a matching run ID;
- verify Docker health, feature flag, dataset SHA, fixture hash, and offline qualification;
- use `gpt-5.6-luna` for all six arms;
- create a fresh worker and conversation for each arm;
- enforce the approved counterbalanced order;
- wait for the closed result envelope;
- retire worker, delete synthetic card, remove temp artifacts, then verify absence;
- abort and clean up on timeout, score refusal, restart, wrong project, or provider error;
- never push, merge, publish, enable global memory, or write memory.

**Step 2: Implement orchestration**

The script drives existing `mp spawn`, assignment, message, kill/retire, and comparison API commands. It may pause for a worker result but must not fabricate one. Record actual wall time and retrieval latency; mark provider tokens `not_measured` unless actual usage exists.

**Step 3: Verify and commit**

~~~powershell
python verify\test_windows_memory_comparison.py
git add windows/Start-MyPeopleMemoryComparison.ps1 verify/test_windows_memory_comparison.py
git commit -m "feat: orchestrate paired Gate B comparison on Windows"
~~~

---

### Task 8: Prove isolation and rollback in disposable Docker

**Files:**

- Create: `verify/test_memory_comparison_e2e.py`
- Modify: `verify/run-suite.sh`

**Step 1: Write the disposable E2E test**

Use an isolated container/runtime directory and synthetic provider adapter. Verify:

- six arms execute in the exact schedule;
- baseline TaskSpec has no memory block;
- memory TaskSpec has only the bounded approved block;
- workers, cards, conversations, and temp files are unique per arm;
- first arm is absent before second arm starts;
- harmful result aborts immediately;
- successful completion leaves no synthetic resources;
- normal Priorities/HUD endpoints remain healthy;
- container restart count does not change.

**Step 2: Implement only the seams needed for deterministic E2E**

Keep the synthetic adapter confined to verification code and feature-flagged test paths.

**Step 3: Run focused and full verification**

~~~powershell
python verify\test_memory_comparison_e2e.py
bash verify/run-suite.sh
~~~

Expected: comparison E2E and J1–J52/current suite pass.

**Step 4: Commit**

~~~powershell
git add verify/test_memory_comparison_e2e.py verify/run-suite.sh
git commit -m "test: prove Gate B comparison isolation"
~~~

---

### Task 9: Execute and record offline qualification

**Files:**

- Modify: `experiments/memory-gate-b/README.md`
- Create after successful run: `experiments/memory-gate-b/reports/comparison-offline-2026-07-22.json`
- Create: `verify/test_memory_comparison_public_artifacts.py`

**Step 1: Add a public-artifact sanitation test**

Scan the README and report for:

- private Windows usernames/paths;
- credentials/tokens;
- raw provider conversations;
- duplicated raw question/gold-answer text;
- claims of actual provider token use when not measured.

**Step 2: Run offline qualification twice**

Generate two temporary receipts, compare SHA-256, then copy the verified canonical receipt to the report path. Record six-of-six status, escalation use, latency median, estimated injected-token median, dataset identity, and fixture hash.

**Step 3: Update documentation**

Document the purpose, commands, metric semantics, stop conditions, and explicit statement that offline qualification does not prove production benefit.

**Step 4: Verify and commit**

~~~powershell
python verify\test_memory_comparison_public_artifacts.py
python verify\test_memory_comparison_offline.py
git add experiments/memory-gate-b/README.md experiments/memory-gate-b/reports/comparison-offline-2026-07-22.json verify/test_memory_comparison_public_artifacts.py
git commit -m "docs: record Gate B offline comparison qualification"
~~~

---

### Task 10: Run three live pairs, clean up, and publish the dependent PR

**Files:**

- Create after successful run: `experiments/memory-gate-b/reports/comparison-live-2026-07-22.json`
- Modify: `experiments/memory-gate-b/README.md`
- Modify if needed: `verify/test_memory_comparison_public_artifacts.py`

**Step 1: Preflight live MyPeople**

Capture:

- container ID/restart count;
- health of Priorities and HUD;
- zero active comparison resources;
- correct Project Factory repo/SHA binding;
- provider availability without copying credentials;
- offline receipt hash.

If any preflight fails, do not start the run.

**Step 2: Execute the approved schedule**

~~~powershell
powershell -ExecutionPolicy Bypass -File windows\Start-MyPeopleMemoryComparison.ps1 -Execute -RunId <generated-run-id>
~~~

For every arm, inspect the closed result and cleanup receipt before allowing the next arm. Stop on harmful output or isolation failure.

**Step 3: Evaluate directional gates**

Require all of:

- six offline cases reproduced;
- three live pairs completed;
- zero harmful results;
- memory success count is not below baseline;
- median memory score is not below baseline;
- at least one pair improves score or avoids measurable rework;
- median retrieval latency `< 2000 ms`;
- median added memory context `<= 300` estimated tokens;
- full cleanup and unchanged restart count.

If a gate fails, report `not_promoted`; do not tune the scorer or rerun selectively.

**Step 4: Sanitize and verify the public report**

The report contains aggregate/per-alias scores, outcome classifications, actual/estimated/not-measured labels, hashes, and cleanup evidence IDs. It contains no raw prompts, conclusions beyond the 500-character closed field, private paths, secrets, or session credentials.

Run:

~~~powershell
python verify\test_memory_comparison_public_artifacts.py
python verify\test_memory_comparison_e2e.py
python verify\test_public_repository.py
git diff --check
~~~

**Step 5: Commit and push**

~~~powershell
git add experiments/memory-gate-b/README.md experiments/memory-gate-b/reports/comparison-live-2026-07-22.json verify/test_memory_comparison_public_artifacts.py
git commit -m "docs: record paired Gate B comparison"
git push -u origin feat/memory-gate-b-comparison
~~~

Open a draft PR with base `feat/memory-gate-b-live-canary`. State clearly that passing this pilot authorizes only designing a larger statistical comparison; it does not enable memory by default.

---

## Final verification checklist

Run from the comparison worktree:

~~~powershell
python verify\test_memory_comparison_fixtures.py
python verify\test_memory_comparison_scoring.py
python verify\test_memory_comparison_offline.py
python verify\test_memory_comparison_cards.py
python verify\test_memory_comparison_runtime.py
python verify\test_memory_comparison_api.py
python verify\test_windows_memory_comparison.py
python verify\test_memory_comparison_e2e.py
python verify\test_memory_comparison_public_artifacts.py
python verify\test_public_repository.py
bash verify/run-suite.sh
git diff --check
git status --short
~~~

Verify manually that:

- normal cards are unchanged;
- no comparison worker/card/conversation/temp file remains;
- memory is still off by default;
- no memory was written;
- public artifacts use English and contain no private data;
- actual, estimated, and not-measured metrics are never conflated;
- the dependent PR targets `feat/memory-gate-b-live-canary`.
