# Memory Gate B Current-SHA Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate, lock, qualify, and safely exercise a new Project Factory history dataset bound exactly to live SHA `039a62988625369f3f86c055cd476b0080395daa` without altering the prior benchmark evidence.

**Architecture:** The deterministic Git-only dataset builder is promoted from the benchmark sandbox into the MyPeople experiment so the repository owns its reproduction path. A SHA-named corpus, SHA-specific lock, generated six-case fixture, and double-run offline receipt form the immutable qualification boundary. Only after those checks pass may the existing opt-in comparison launcher bind the live Docker workspace and run three isolated Luna pairs.

**Tech Stack:** Python 3 standard library, Git, JSON/JSONL, `unittest`, PowerShell, Docker Compose, existing MyPeople comparison runtime.

**Approved design:** `docs/superpowers/specs/2026-07-22-memory-gate-b-current-sha-refresh-design.md`

---

## Fixed boundaries

- New source SHA: `039a62988625369f3f86c055cd476b0080395daa`.
- New dataset directory: `experiments/memory-gate-b/datasets/project-factory-history-039a62988625`.
- New lock: `experiments/memory-gate-b/docker/history-hybrid-039a62988625.dataset-lock.json`.
- Generator v2 accepts the observed 52-commit boundary, still emits 100 unique
  grounded questions, and never invents history.
- Old dataset, old lock, and old reports remain byte-identical.
- Public repository content is English and sanitized.
- Raw question text and gold answers remain in the private dataset/runtime path; the committed comparison fixture contains identifiers only.
- Memory stays read-only, opt-in, bounded to top three results, and disabled for normal tasks.
- No live cards or workers are created until exact-SHA preflight succeeds.

### Task 1: Make dataset reproduction repository-owned

**Files:**

- Create: `experiments/memory-gate-b/src/memory_bench/history_dataset.py`
- Create: `experiments/memory-gate-b/scripts/build_project_factory_history_dataset.py`
- Create: `experiments/memory-gate-b/tests/test_history_dataset.py`

- [ ] **Step 1: Copy the proven tests, then add a source-boundary failure test**

Port the existing deterministic builder tests from the benchmark sandbox and add:

```python
def test_refuses_source_sha_that_is_not_a_commit(self):
    with self.assertRaisesRegex(ValueError, "source SHA must resolve to a commit"):
        build_history_dataset(self.repo, "refs/heads/missing", "example/project-factory")
```

- [ ] **Step 2: Run the focused test and verify red**

```powershell
python -m unittest experiments.memory-gate-b.tests.test_history_dataset -v
```

Expected: FAIL because `memory_bench.history_dataset` is not present in the MyPeople experiment.

- [ ] **Step 3: Port the reviewed deterministic implementation and CLI**

Preserve these public interfaces exactly:

```python
def build_history_dataset(repo: Path, source_sha: str, repo_slug: str) -> HistoryDataset: ...
def validate_history_dataset(dataset: HistoryDataset) -> dict[str, object]: ...
def write_history_dataset(dataset: HistoryDataset, output: Path) -> dict[str, object]: ...
```

The builder must read committed Git objects only, resolve the requested SHA once, reject fewer than 50 non-merge commits, create exactly 100 grounded questions, and write canonical UTF-8 JSON/JSONL. It may reuse evidence deterministically between families and selects correction cases only from the closed verbs `fix`, `restore`, `harden`, `guard`, `repair`, `rollback`, and `correct`.

- [ ] **Step 4: Verify deterministic reproduction**

```powershell
python -m unittest experiments.memory-gate-b.tests.test_history_dataset -v
```

Expected: all dataset tests pass, including equality for two builds of the same SHA.

- [ ] **Step 5: Commit**

```powershell
git add experiments/memory-gate-b/src/memory_bench/history_dataset.py experiments/memory-gate-b/scripts/build_project_factory_history_dataset.py experiments/memory-gate-b/tests/test_history_dataset.py
git commit -m "feat: own deterministic history dataset generation"
```

### Task 2: Generate and independently lock the current-SHA corpus

**Files:**

- Create: `experiments/memory-gate-b/datasets/project-factory-history-039a62988625/aliases.json`
- Create: `experiments/memory-gate-b/datasets/project-factory-history-039a62988625/events.jsonl`
- Create: `experiments/memory-gate-b/datasets/project-factory-history-039a62988625/manifest.json`
- Create: `experiments/memory-gate-b/datasets/project-factory-history-039a62988625/questions.jsonl`
- Create: `experiments/memory-gate-b/datasets/project-factory-history-039a62988625/validation.json`
- Create: `experiments/memory-gate-b/docker/history-hybrid-039a62988625.dataset-lock.json`
- Create: `verify/test_memory_dataset_refresh.py`

- [ ] **Step 1: Record hashes of all historical evidence and write the failing refresh test**

The test must assert:

```python
NEW_SHA = "039a62988625369f3f86c055cd476b0080395daa"
NEW_NAME = "project-factory-history-039a62988625"
OLD_NAME = "project-factory-history-80dce6f86632"

self.assertEqual(new_manifest["source_sha"], NEW_SHA)
self.assertEqual(new_lock["dataset_dir"], NEW_NAME)
self.assertEqual(set(new_lock["files"]), EXPECTED_DATASET_FILES)
self.assertEqual(old_hashes_after, old_hashes_before)
```

Store the historical expected SHA-256 values directly in the test from the committed old lock and reports; do not compute both sides from the same post-change state.

- [ ] **Step 2: Run the test and verify red**

```powershell
python verify\test_memory_dataset_refresh.py
```

Expected: FAIL because the new dataset and lock do not exist.

- [ ] **Step 3: Build the dataset from the exact checked commit**

```powershell
$mounts = docker inspect mypeople | ConvertFrom-Json | Select-Object -ExpandProperty Mounts
$repoPath = @($mounts | Where-Object { $_.Destination -eq '/home/mp/workspaces/project-factory' } | Select-Object -ExpandProperty Source)
if ($repoPath.Count -ne 1) { throw 'project_factory_host_mount_not_found' }
$env:PYTHONPATH='experiments\memory-gate-b\src'
python experiments\memory-gate-b\scripts\build_project_factory_history_dataset.py --repo $repoPath[0] --source-sha 039a62988625369f3f86c055cd476b0080395daa --repo-slug LordCripto-Hub/Project-Factory --output experiments\memory-gate-b\datasets\project-factory-history-039a62988625
```

The mount lookup must resolve exactly one host source for `/home/mp/workspaces/project-factory`; the builder must still receive the exact SHA above.

- [ ] **Step 4: Create the SHA-specific lock from canonical file hashes**

Write schema version, dataset directory, repo slug, full source SHA, and SHA-256 for exactly the five dataset files. Do not modify `history-hybrid.dataset-lock.json`.

- [ ] **Step 5: Verify and commit**

```powershell
python verify\test_memory_dataset_refresh.py
git diff --check
git add experiments/memory-gate-b/datasets/project-factory-history-039a62988625 experiments/memory-gate-b/docker/history-hybrid-039a62988625.dataset-lock.json verify/test_memory_dataset_refresh.py
git commit -m "data: lock Project Factory history at 039a629"
```

### Task 3: Generate a six-case fixture from the new locked corpus

**Files:**

- Create: `experiments/memory-gate-b/scripts/select_memory_comparison_cases.py`
- Modify: `experiments/memory-gate-b/comparison/cases.json`
- Modify: `verify/test_memory_comparison_fixtures.py`
- Modify: `verify/test_memory_comparison_scoring.py`

- [ ] **Step 1: Add failing current-SHA fixture tests**

Require `cases.json` to identify the new dataset and contain exactly:

```python
expected_classes = {
    "exact_constraint": 2,
    "temporal_continuation": 2,
    "contradiction_prevention": 2,
}
expected_live_orders = [
    ("exact_constraint", ["baseline", "memory"]),
    ("temporal_continuation", ["memory", "baseline"]),
    ("contradiction_prevention", ["baseline", "memory"]),
]
```

Also assert that every allowed/rejected evidence ID exists in the new corpus, that allowed and rejected sets are disjoint, and that no `query`, `answer`, `prompt`, or absolute path key appears in the fixture.

- [ ] **Step 2: Verify red**

```powershell
python verify\test_memory_comparison_fixtures.py
python verify\test_memory_comparison_scoring.py
```

Expected: fixture test fails on the old dataset identity.

- [ ] **Step 3: Implement deterministic case selection**

The selector accepts `--dataset`, `--lock`, and `--output`; sorts eligible questions by stable `question_id`; chooses two passing cases from each required family; marks the first of each family live; and emits only IDs, class, arm order, decision ID, evidence IDs, and verification-command IDs.

- [ ] **Step 4: Generate and verify the fixture**

```powershell
$env:PYTHONPATH='experiments\memory-gate-b\src'
python experiments\memory-gate-b\scripts\select_memory_comparison_cases.py --dataset experiments\memory-gate-b\datasets\project-factory-history-039a62988625 --lock experiments\memory-gate-b\docker\history-hybrid-039a62988625.dataset-lock.json --output experiments\memory-gate-b\comparison\cases.json
python verify\test_memory_comparison_fixtures.py
python verify\test_memory_comparison_scoring.py
```

Expected: both suites pass and the fixture contains no raw question text.

- [ ] **Step 5: Commit**

```powershell
git add experiments/memory-gate-b/scripts/select_memory_comparison_cases.py experiments/memory-gate-b/comparison/cases.json verify/test_memory_comparison_fixtures.py verify/test_memory_comparison_scoring.py
git commit -m "test: bind comparison cases to current Project Factory history"
```

### Task 4: Rebind all offline and isolated consumers without deleting history

**Files:**

- Modify: `experiments/memory-gate-b/scripts/run_memory_comparison_offline.py`
- Modify: `verify/test_memory_comparison_offline.py`
- Modify: `experiments/memory-gate-b/windows/Invoke-IsolatedTaskSpecMemory.ps1`
- Modify: `experiments/memory-gate-b/tests/test_taskspec_windows_launcher.py`
- Modify: `experiments/memory-gate-b/tests/test_taskspec_docker_contract.py`
- Modify: `verify/test_memory_gate_b_experiment.py`

- [ ] **Step 1: Change tests first to require explicit SHA-specific locks**

Tests must reject pairing the new dataset with the old lock, pairing the old dataset with the new lock, and invoking an implicit generic lock for the new corpus.

- [ ] **Step 2: Verify red**

```powershell
python verify\test_memory_comparison_offline.py
python experiments\memory-gate-b\tests\test_taskspec_windows_launcher.py
python experiments\memory-gate-b\tests\test_taskspec_docker_contract.py
python verify\test_memory_gate_b_experiment.py
```

- [ ] **Step 3: Make dataset and lock binding explicit**

Set current defaults to `project-factory-history-039a62988625` and `history-hybrid-039a62988625.dataset-lock.json`. Keep the old directory and lock readable only through explicit historical paths. Every loader continues to verify manifest SHA and every file checksum.

- [ ] **Step 4: Verify green and commit**

```powershell
python verify\test_memory_comparison_offline.py
python experiments\memory-gate-b\tests\test_taskspec_windows_launcher.py
python experiments\memory-gate-b\tests\test_taskspec_docker_contract.py
python verify\test_memory_gate_b_experiment.py
git add experiments/memory-gate-b/scripts/run_memory_comparison_offline.py experiments/memory-gate-b/windows/Invoke-IsolatedTaskSpecMemory.ps1 experiments/memory-gate-b/tests verify/test_memory_comparison_offline.py verify/test_memory_gate_b_experiment.py
git commit -m "feat: bind memory qualification to SHA-specific corpus"
```

### Task 5: Qualify the new corpus twice and publish a sanitized offline receipt

**Files:**

- Create: `experiments/memory-gate-b/reports/comparison-offline-039a62988625.json`
- Modify: `experiments/memory-gate-b/README.md`
- Modify: `verify/test_memory_comparison_public_artifacts.py`

- [ ] **Step 1: Add failing sanitation and reproducibility assertions**

Require the new receipt to report six passes, zero harmful cases, top-k three, the new source SHA, actual retrieval latency, estimated context tokens, and provider tokens as `not_measured`. Require the old receipt hash to remain unchanged.

- [ ] **Step 2: Run two independent qualifications**

```powershell
python experiments\memory-gate-b\scripts\run_memory_comparison_offline.py --dataset experiments\memory-gate-b\datasets\project-factory-history-039a62988625 --lock experiments\memory-gate-b\docker\history-hybrid-039a62988625.dataset-lock.json --cases experiments\memory-gate-b\comparison\cases.json --output C:\tmp\memory-039a-offline-a.json
python experiments\memory-gate-b\scripts\run_memory_comparison_offline.py --dataset experiments\memory-gate-b\datasets\project-factory-history-039a62988625 --lock experiments\memory-gate-b\docker\history-hybrid-039a62988625.dataset-lock.json --cases experiments\memory-gate-b\comparison\cases.json --output C:\tmp\memory-039a-offline-b.json
```

Compare `fixture_sha256`, `logical_digest`, pass/fail, evidence IDs, and escalation decisions. Retrieval latency may differ.

- [ ] **Step 3: Publish only the qualified canonical receipt and English documentation**

Copy the first verified receipt to `comparison-offline-039a62988625.json`. Document commands, hashes, metric semantics, historical preservation, and that offline success does not prove live benefit.

- [ ] **Step 4: Verify and commit**

```powershell
python verify\test_memory_comparison_offline.py
python verify\test_memory_comparison_public_artifacts.py
python verify\test_public_repository.py
git diff --check
git add experiments/memory-gate-b/reports/comparison-offline-039a62988625.json experiments/memory-gate-b/README.md verify/test_memory_comparison_public_artifacts.py
git commit -m "docs: qualify current-SHA memory corpus offline"
```

### Task 6: Rebind live preflight and prove refusal/cleanup in disposable Docker

**Files:**

- Modify: `windows/Start-MyPeopleMemoryComparison.ps1`
- Modify: `verify/test_windows_memory_comparison.py`
- Modify: `verify/test_memory_comparison_e2e.py`
- Modify: `verify/run-suite.sh`

- [ ] **Step 1: Write failing exact-SHA preflight tests**

Require the launcher to bind the new dataset, lock, receipt, fixture hash, logical digest, and SHA. Simulate and assert refusal on wrong workspace SHA, dirty workspace, unavailable provider, disabled comparison flag, existing comparison resources, or changed restart count.

- [ ] **Step 2: Verify red**

```powershell
python verify\test_windows_memory_comparison.py
python verify\test_memory_comparison_e2e.py
```

- [ ] **Step 3: Implement minimal rebinding and clean-workspace check**

Preflight runs `git rev-parse HEAD` and `git status --porcelain` inside `/home/mp/workspaces/project-factory`; it proceeds only for the exact approved SHA and empty status. It checks Priorities/HUD health, provider availability without exporting credentials, zero comparison resources, and memory sidecar readiness.

- [ ] **Step 4: Run disposable Docker and full isolated verification**

```powershell
python verify\test_windows_memory_comparison.py
python verify\test_memory_comparison_e2e.py
bash verify/run-suite.sh
```

Expected: the exact counterbalanced schedule passes under the synthetic adapter, harmful output aborts immediately, all temporary resources are absent, and J1-J52/current suite is green.

- [ ] **Step 5: Commit**

```powershell
git add windows/Start-MyPeopleMemoryComparison.ps1 verify/test_windows_memory_comparison.py verify/test_memory_comparison_e2e.py verify/run-suite.sh
git commit -m "test: qualify current-SHA live comparison boundary"
```

### Task 7: Run the bounded live pairs and record the promotion decision

**Files:**

- Create on successful completion: `experiments/memory-gate-b/reports/comparison-live-039a62988625.json`
- Modify: `experiments/memory-gate-b/README.md`
- Modify: `verify/test_memory_comparison_public_artifacts.py`

- [ ] **Step 1: Capture preflight evidence without creating resources**

```powershell
powershell -ExecutionPolicy Bypass -File windows\Start-MyPeopleMemoryComparison.ps1 -Action Preflight
```

Expected: `offline_qualified`, exact source SHA, unchanged restart count, fixture hash, and logical digest. Any other result stops the task.

- [ ] **Step 2: Execute exactly three counterbalanced Luna pairs**

```powershell
$run='memory-039a-20260722'
powershell -ExecutionPolicy Bypass -File windows\Start-MyPeopleMemoryComparison.ps1 -Action Paired -RunId $run -ConfirmedRunId $run -Execute -ConfirmLiveRun
```

Every arm receives a fresh card, worker, provider conversation, and result directory. Baseline gets no memory block; memory gets only the approved top-three block. Never selectively rerun a failed pair.

- [ ] **Step 3: Enforce promotion gates**

Require three completed pairs, zero harmful results, memory success count and median score not below baseline, at least one measurable improvement, median retrieval latency below 2000 ms, median estimated memory context at most 300 tokens, complete cleanup, and unchanged restart count. Otherwise record `not_promoted`.

- [ ] **Step 4: Sanitize, verify, and commit the report**

```powershell
python verify\test_memory_comparison_public_artifacts.py
python verify\test_memory_comparison_e2e.py
python verify\test_public_repository.py
git diff --check
git status --short
```

The report contains aggregate/per-alias metrics and evidence IDs only: no prompts, credentials, provider transcripts, private paths, full session IDs, or private reasoning.

```powershell
git add experiments/memory-gate-b/reports/comparison-live-039a62988625.json experiments/memory-gate-b/README.md verify/test_memory_comparison_public_artifacts.py
git commit -m "docs: record current-SHA paired memory comparison"
```

### Task 8: Final branch verification and PR update

**Files:**

- Modify: `docs/superpowers/plans/2026-07-22-memory-gate-b-current-sha-refresh.md` only to check completed boxes

- [ ] **Step 1: Run the complete evidence suite**

```powershell
python -m unittest experiments.memory-gate-b.tests.test_history_dataset -v
python verify\test_memory_dataset_refresh.py
python verify\test_memory_comparison_fixtures.py
python verify\test_memory_comparison_scoring.py
python verify\test_memory_comparison_offline.py
python verify\test_memory_comparison_public_artifacts.py
python verify\test_windows_memory_comparison.py
python verify\test_memory_comparison_e2e.py
python verify\test_public_repository.py
bash verify/run-suite.sh
git diff --check
git status --short
```

- [ ] **Step 2: Verify safety invariants manually**

Confirm old hashes are unchanged, memory is off by default, no comparison resource remains, no memory write occurred, public content is English, and actual/estimated/not-measured metrics are distinct.

- [ ] **Step 3: Commit plan tracking and push the existing branch**

```powershell
git add docs/superpowers/plans/2026-07-22-memory-gate-b-current-sha-refresh.md
git commit -m "docs: complete current-SHA memory refresh plan"
git push origin feat/memory-gate-b-comparison
```

Update draft PR `#12`. Passing authorizes only the design of a larger statistical experiment; it does not enable memory globally.
