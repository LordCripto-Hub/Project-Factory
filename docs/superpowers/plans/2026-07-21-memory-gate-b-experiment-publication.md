# Provider-Neutral Memory Gate B Experiment Publication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish the verified read-only TaskSpec memory Gate B as a self-contained, provider-neutral Project Factory experiment without changing or activating the production MyPeople runtime.

**Architecture:** Copy only the verified retrieval, fixture, TaskSpec adapter, disposable Docker boundary, final dataset, tests, and sanitized evidence below `experiments/memory-gate-b/`. Add a root verification bridge that executes focused experiment contracts inside the existing isolated verifier, while keeping the expensive Docker reproduction explicit and preserving the default installer, Compose deployment, launcher, and runtime code unchanged.

**Tech Stack:** Python 3 standard library and `unittest`, SQLite FTS5, Node.js MCP SDK already present in the reviewed MyPeople image, Docker Compose v2, PowerShell 5.1+, Git, SHA-256.

---

## File Map

- `experiments/memory-gate-b/README.md` — public purpose, boundary, commands, results, and promotion rules.
- `experiments/memory-gate-b/src/memory_bench/` — minimal provider-neutral retrieval and TaskSpec gate modules.
- `experiments/memory-gate-b/scripts/` — recall bridge and deterministic gate runner.
- `experiments/memory-gate-b/datasets/project-factory-history-80dce6f86632/` — final source-bound dataset only.
- `experiments/memory-gate-b/docker/` — locked dataset identity, recall-only HTTPS fixture, entrypoint, and disposable Compose file.
- `experiments/memory-gate-b/windows/Invoke-IsolatedTaskSpecMemory.ps1` — bounded Windows reproduction and live-invariant check.
- `experiments/memory-gate-b/tests/` — focused unit and static security contracts.
- `experiments/memory-gate-b/artifacts/` — deterministic result/report and sanitized execution receipt.
- `verify/test_memory_gate_b_experiment.py` — root packaging, isolation, sanitation, dataset, and nested-test bridge.
- `verify/run-suite.sh` — registers the fast focused bridge in the standard isolated verifier.
- `README.md` — links the optional experiment without implying production activation.

### Task 1: Establish the public experiment packaging contract

**Files:**
- Create: `verify/test_memory_gate_b_experiment.py`

- [ ] **Step 1: Write the failing root contract**

Create `verify/test_memory_gate_b_experiment.py` with this contract:

```python
#!/usr/bin/env python3
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "experiments" / "memory-gate-b"
DATASET = EXPERIMENT / "datasets" / "project-factory-history-80dce6f86632"
LOCK = EXPERIMENT / "docker" / "history-hybrid.dataset-lock.json"


class MemoryGateBExperimentContract(unittest.TestCase):
    def test_required_package_surfaces_exist(self):
        required = (
            EXPERIMENT / "README.md",
            EXPERIMENT / "src" / "memory_bench" / "taskspec_gate.py",
            EXPERIMENT / "src" / "memory_bench" / "taskspec_memory.py",
            EXPERIMENT / "scripts" / "run_taskspec_memory_gate.py",
            EXPERIMENT / "docker" / "compose.taskspec-memory.yml",
            EXPERIMENT / "windows" / "Invoke-IsolatedTaskSpecMemory.ps1",
            EXPERIMENT / "artifacts" / "taskspec-memory-result.json",
        )
        for path in required:
            self.assertTrue(path.is_file(), path)

    def test_dataset_is_final_locked_and_complete(self):
        lock = json.loads(LOCK.read_text(encoding="utf-8"))
        self.assertEqual(lock["dataset_dir"], DATASET.name)
        self.assertEqual(
            lock["source_sha"],
            "80dce6f866329b79061bb1ed6b0594f9fdf2dd45",
        )
        self.assertNotIn("preliminary", json.dumps(lock).lower())
        for name, expected in lock["files"].items():
            path = DATASET / name
            self.assertTrue(path.is_file(), path)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected)

    def test_experiment_is_not_activated_by_production_entrypoints(self):
        production = [ROOT / "install.sh", *sorted((ROOT / "bin").glob("*"))]
        production += sorted((ROOT / "docker").rglob("*"))
        production += sorted((ROOT / "windows").rglob("*"))
        for path in production:
            if path.is_file():
                self.assertNotIn(
                    "experiments/memory-gate-b",
                    path.read_text(encoding="utf-8", errors="ignore"),
                    path,
                )

    def test_public_experiment_has_no_private_material(self):
        forbidden = (
            re.compile(r"(?i)tskey-auth-"),
            re.compile(r"(?i)sk-[a-z0-9]{20,}"),
            re.compile(r"(?i)[a-z0-9._%+-]+@gmail\\.com"),
            re.compile(r"(?i)c:\\\\users\\\\[^\\\\]+"),
            re.compile(r"(?i)/users/[^/]+"),
            re.compile(r"(?i)authorization\\s*:\\s*bearer\\s+[^\"'\\s]+"),
        )
        for path in EXPERIMENT.rglob("*"):
            if path.is_file():
                text = path.read_text(encoding="utf-8", errors="ignore")
                for pattern in forbidden:
                    self.assertIsNone(pattern.search(text), f"{path}: {pattern.pattern}")

    def test_focused_experiment_suite_passes(self):
        env = {**os.environ, "PYTHONPATH": str(EXPERIMENT / "src")}
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                str(EXPERIMENT / "tests"),
                "-v",
            ],
            cwd=EXPERIMENT,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run the contract to prove RED**

Run:

```powershell
python verify\test_memory_gate_b_experiment.py
```

Expected: FAIL because `experiments/memory-gate-b/` does not exist.

### Task 2: Copy the minimal verified engine, final dataset, and focused tests

**Files:**
- Create: `experiments/memory-gate-b/src/memory_bench/__init__.py`
- Create: `experiments/memory-gate-b/src/memory_bench/models.py`
- Create: `experiments/memory-gate-b/src/memory_bench/retrieval.py`
- Create: `experiments/memory-gate-b/src/memory_bench/scoring.py`
- Create: `experiments/memory-gate-b/src/memory_bench/history_fixture.py`
- Create: `experiments/memory-gate-b/src/memory_bench/history_runner.py`
- Create: `experiments/memory-gate-b/src/memory_bench/taskspec_memory.py`
- Create: `experiments/memory-gate-b/src/memory_bench/taskspec_gate.py`
- Create: `experiments/memory-gate-b/scripts/query_taskspec_memory.py`
- Create: `experiments/memory-gate-b/scripts/run_taskspec_memory_gate.py`
- Create: `experiments/memory-gate-b/datasets/project-factory-history-80dce6f86632/*`
- Create: `experiments/memory-gate-b/docker/history-hybrid.dataset-lock.json`
- Create: `experiments/memory-gate-b/tests/__init__.py`
- Create: `experiments/memory-gate-b/tests/test_taskspec_memory.py`
- Create: `experiments/memory-gate-b/tests/test_taskspec_gate.py`

- [ ] **Step 1: Require an explicit verified source checkout**

Run:

```powershell
$GateBSource = $env:MYPEOPLE_GATE_B_SOURCE
if (-not $GateBSource -or -not (Test-Path "$GateBSource\src\memory_bench\taskspec_gate.py")) {
    throw 'MYPEOPLE_GATE_B_SOURCE must identify the verified Gate B checkout'
}
git -C $GateBSource rev-parse HEAD
```

Expected: the source checkout resolves to commit `b92f244` or its fast-forwarded local `master`.

- [ ] **Step 2: Copy only the minimal dependency closure**

Run the following with `$GateBSource` set:

```powershell
$Target = 'experiments\memory-gate-b'
New-Item -ItemType Directory -Force "$Target\src\memory_bench", "$Target\scripts", "$Target\datasets", "$Target\docker", "$Target\tests" | Out-Null
$Modules = @('__init__.py','models.py','retrieval.py','scoring.py','history_fixture.py','history_runner.py','taskspec_memory.py','taskspec_gate.py')
foreach ($Name in $Modules) {
    Copy-Item -LiteralPath "$GateBSource\src\memory_bench\$Name" -Destination "$Target\src\memory_bench\$Name"
}
Copy-Item -LiteralPath "$GateBSource\scripts\query_taskspec_memory.py" -Destination "$Target\scripts\query_taskspec_memory.py"
Copy-Item -LiteralPath "$GateBSource\scripts\run_taskspec_memory_gate.py" -Destination "$Target\scripts\run_taskspec_memory_gate.py"
Copy-Item -Recurse -LiteralPath "$GateBSource\datasets\project-factory-history-80dce6f86632" -Destination "$Target\datasets\project-factory-history-80dce6f86632"
Copy-Item -LiteralPath "$GateBSource\docker\history-hybrid.dataset-lock.json" -Destination "$Target\docker\history-hybrid.dataset-lock.json"
Copy-Item -LiteralPath "$GateBSource\tests\__init__.py" -Destination "$Target\tests\__init__.py"
Copy-Item -LiteralPath "$GateBSource\tests\test_taskspec_memory.py" -Destination "$Target\tests\test_taskspec_memory.py"
Copy-Item -LiteralPath "$GateBSource\tests\test_taskspec_gate.py" -Destination "$Target\tests\test_taskspec_gate.py"
```

- [ ] **Step 3: Run the focused Python tests**

Run:

```powershell
$env:PYTHONPATH = 'experiments\memory-gate-b\src'
python -m unittest discover -s experiments\memory-gate-b\tests -p 'test_taskspec_*.py' -v
Remove-Item Env:PYTHONPATH
```

Expected: the memory and TaskSpec gate tests pass; the root packaging contract still fails only for the Docker, Windows, README, and artifact surfaces not copied yet.

- [ ] **Step 4: Commit the engine and dataset slice**

```powershell
git add verify/test_memory_gate_b_experiment.py experiments/memory-gate-b/src experiments/memory-gate-b/scripts experiments/memory-gate-b/datasets experiments/memory-gate-b/docker/history-hybrid.dataset-lock.json experiments/memory-gate-b/tests
git commit -m "test: package provider-neutral memory Gate B core"
```

### Task 3: Add the disposable recall-only Docker boundary

**Files:**
- Create: `experiments/memory-gate-b/docker/compose.taskspec-memory.yml`
- Create: `experiments/memory-gate-b/docker/taskspec-memory-entrypoint.sh`
- Create: `experiments/memory-gate-b/docker/taskspec-memory-server.mjs`
- Create: `experiments/memory-gate-b/tests/test_taskspec_docker_contract.py`

- [ ] **Step 1: Copy the verified Docker fixture and its failing/green contract together**

```powershell
$Target = 'experiments\memory-gate-b'
Copy-Item -LiteralPath "$GateBSource\docker\compose.taskspec-memory.yml" -Destination "$Target\docker\compose.taskspec-memory.yml"
Copy-Item -LiteralPath "$GateBSource\docker\taskspec-memory-entrypoint.sh" -Destination "$Target\docker\taskspec-memory-entrypoint.sh"
Copy-Item -LiteralPath "$GateBSource\docker\taskspec-memory-server.mjs" -Destination "$Target\docker\taskspec-memory-server.mjs"
Copy-Item -LiteralPath "$GateBSource\tests\test_taskspec_docker_contract.py" -Destination "$Target\tests\test_taskspec_docker_contract.py"
```

- [ ] **Step 2: Run the Docker static contract**

```powershell
$env:PYTHONPATH = 'experiments\memory-gate-b\src'
python experiments\memory-gate-b\tests\test_taskspec_docker_contract.py -v
Remove-Item Env:PYTHONPATH
```

Expected: 4 tests pass and prove HTTPS, Bearer authentication, recall-only tools, no network, read-only mounts, blank provider secrets, ephemeral TLS, and no production volumes.

- [ ] **Step 3: Validate Compose with explicit inert inputs**

```powershell
$env:MYPEOPLE_TASKSPEC_IMAGE = 'mypeople-node:upgrade-20260719T150005Z'
$env:MYPEOPLE_TASKSPEC_DATASET_NAME = 'project-factory-history-80dce6f86632'
$env:EXPECTED_SOURCE_SHA = '80dce6f866329b79061bb1ed6b0594f9fdf2dd45'
$env:MP_TASKSPEC_SOURCE = (Resolve-Path 'experiments\memory-gate-b').Path
$env:MP_TASKSPEC_DATASET = (Resolve-Path 'experiments\memory-gate-b\datasets\project-factory-history-80dce6f86632').Path
$env:MP_TASKSPEC_EVIDENCE = (New-Item -ItemType Directory -Force "$env:TEMP\mypeople-gate-b-compose-check").FullName
docker compose -f experiments\memory-gate-b\docker\compose.taskspec-memory.yml config --quiet
```

Expected: exit 0 without starting a container.

- [ ] **Step 4: Commit the Docker boundary**

```powershell
git add experiments/memory-gate-b/docker experiments/memory-gate-b/tests/test_taskspec_docker_contract.py
git commit -m "feat: publish isolated recall-only Gate B fixture"
```

### Task 4: Add the bounded Windows reproduction launcher

**Files:**
- Create: `experiments/memory-gate-b/windows/Invoke-IsolatedTaskSpecMemory.ps1`
- Create: `experiments/memory-gate-b/tests/test_taskspec_windows_launcher.py`

- [ ] **Step 1: Copy the verified launcher and contract**

```powershell
$Target = 'experiments\memory-gate-b'
New-Item -ItemType Directory -Force "$Target\windows" | Out-Null
Copy-Item -LiteralPath "$GateBSource\windows\Invoke-IsolatedTaskSpecMemory.ps1" -Destination "$Target\windows\Invoke-IsolatedTaskSpecMemory.ps1"
Copy-Item -LiteralPath "$GateBSource\tests\test_taskspec_windows_launcher.py" -Destination "$Target\tests\test_taskspec_windows_launcher.py"
```

- [ ] **Step 2: Run the Windows launcher contract**

```powershell
python experiments\memory-gate-b\tests\test_taskspec_windows_launcher.py -v
```

Expected: 5 tests pass and prove source identity, timeout, unconditional cleanup, no volume deletion, promotion-gate enforcement, and unchanged live-container checks.

- [ ] **Step 3: Commit the launcher**

```powershell
git add experiments/memory-gate-b/windows experiments/memory-gate-b/tests/test_taskspec_windows_launcher.py
git commit -m "feat: add bounded Windows Gate B launcher"
```

### Task 5: Publish sanitized evidence and operator documentation

**Files:**
- Create: `experiments/memory-gate-b/artifacts/taskspec-memory-result.json`
- Create: `experiments/memory-gate-b/artifacts/taskspec-memory-report.md`
- Create: `experiments/memory-gate-b/artifacts/container-receipt.json`
- Create: `experiments/memory-gate-b/README.md`
- Modify: `README.md`
- Modify: `verify/test_public_repository.py`

- [ ] **Step 1: Copy only the final Gate B evidence**

```powershell
$Target = 'experiments\memory-gate-b\artifacts'
New-Item -ItemType Directory -Force $Target | Out-Null
Copy-Item -LiteralPath "$GateBSource\artifacts\history-hybrid-gate-b\taskspec-memory-result.json" -Destination "$Target\taskspec-memory-result.json"
Copy-Item -LiteralPath "$GateBSource\artifacts\history-hybrid-gate-b\taskspec-memory-report.md" -Destination "$Target\taskspec-memory-report.md"
Copy-Item -LiteralPath "$GateBSource\artifacts\history-hybrid-gate-b\container-receipt.json" -Destination "$Target\container-receipt.json"
```

- [ ] **Step 2: Write the experiment README**

Create `experiments/memory-gate-b/README.md` with these sections and exact contracts:

```markdown
# Memory Gate B Experiment

This provider-neutral experiment verifies that Project Factory can add a small,
grounded, read-only memory result to a real MyPeople TaskSpec without weakening
the local task contract or changing the live runtime.

## What It Proves

- relevant recall returns at most three grounded claims;
- irrelevant recall returns no claims;
- no memory question causes no memory call;
- the locked Project Factory history dataset is bound to source commit
  `80dce6f866329b79061bb1ed6b0594f9fdf2dd45`;
- the disposable fixture has no external network, production volume, Docker
  socket, provider key, or write tool;
- actual provider tokens are `not_measured`; 236 tokens is only the estimated
  TaskSpec memory-context delta.

## Run On Windows

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\experiments\memory-gate-b\windows\Invoke-IsolatedTaskSpecMemory.ps1 -Image mypeople-node:upgrade-20260719T150005Z
```

The launcher requires Docker Desktop and an already reviewed MyPeople image. It
verifies that the live `mypeople` container is unchanged and cleans up its
unique disposable Compose project.

## Run Focused Tests

```powershell
$env:PYTHONPATH = 'experiments\memory-gate-b\src'
python -m unittest discover -s experiments\memory-gate-b\tests -v
```

## Runtime Boundary

This directory is not imported by `install.sh`, the default Compose deployment,
the Windows launcher, or the runtime supervisor. It is evaluation evidence, not
production memory. Cloudflare and other hosted providers are optional future
adapters to the same recall contract, not dependencies of this experiment.

## Promotion

Promotion requires a separate approved design, controlled live canaries,
measured task-quality improvement, honest token/cost attribution, secure
project isolation, and rollback evidence.
```

- [ ] **Step 3: Link the experiment from the root README**

Add this section before the root README verification section:

```markdown
## Experimental memory evaluation

[`experiments/memory-gate-b/`](experiments/memory-gate-b/) contains the
provider-neutral, read-only TaskSpec memory Gate B. It is reproducible evidence
and is not installed or enabled by default.
```

- [ ] **Step 4: Expand the public repository audit**

In `verify/test_public_repository.py`, add the experiment README and report to
`PUBLIC_FILES`:

```python
    ROOT / "experiments" / "memory-gate-b" / "README.md",
    ROOT / "experiments" / "memory-gate-b" / "artifacts" / "taskspec-memory-report.md",
```

Add this test:

```python
    def test_memory_gate_b_is_provider_neutral_and_not_activated(self):
        readme = (
            ROOT / "experiments" / "memory-gate-b" / "README.md"
        ).read_text(encoding="utf-8")
        self.assertIn("provider-neutral", readme)
        self.assertIn("not installed or enabled", (ROOT / "README.md").read_text(encoding="utf-8"))
        self.assertIn("not production memory", readme)
        self.assertIn("not dependencies of this experiment", readme)
```

- [ ] **Step 5: Run sanitation and packaging contracts**

```powershell
python verify\test_public_repository.py -v
python verify\test_memory_gate_b_experiment.py -v
git diff --check
```

Expected: all public repository and experiment packaging tests pass; `git diff --check` emits no output.

- [ ] **Step 6: Commit documentation and evidence**

```powershell
git add README.md verify/test_public_repository.py experiments/memory-gate-b/README.md experiments/memory-gate-b/artifacts
git commit -m "docs: publish reproducible memory Gate B evidence"
```

### Task 6: Register the focused suite and reproduce Gate B twice

**Files:**
- Modify: `verify/run-suite.sh`
- Update: `experiments/memory-gate-b/artifacts/taskspec-memory-result.json`
- Update: `experiments/memory-gate-b/artifacts/taskspec-memory-report.md`
- Update: `experiments/memory-gate-b/artifacts/container-receipt.json`

- [ ] **Step 1: Register the root experiment contract**

Insert after `python3 "$VERIFY/test_isolated_verifier.py"` in
`verify/run-suite.sh`:

```bash
python3 "$VERIFY/test_memory_gate_b_experiment.py"
```

- [ ] **Step 2: Run Gate B twice into separate temporary evidence roots**

```powershell
$Launcher = 'experiments\memory-gate-b\windows\Invoke-IsolatedTaskSpecMemory.ps1'
$Run1 = Join-Path $env:TEMP 'mypeople-gate-b-public-run-1'
$Run2 = Join-Path $env:TEMP 'mypeople-gate-b-public-run-2'
powershell -NoProfile -ExecutionPolicy Bypass -File $Launcher -Image 'mypeople-node:upgrade-20260719T150005Z' -EvidenceRoot $Run1
if ($LASTEXITCODE -ne 0) { throw "Gate B run 1 failed: $LASTEXITCODE" }
powershell -NoProfile -ExecutionPolicy Bypass -File $Launcher -Image 'mypeople-node:upgrade-20260719T150005Z' -EvidenceRoot $Run2
if ($LASTEXITCODE -ne 0) { throw "Gate B run 2 failed: $LASTEXITCODE" }
```

Expected: both commands exit 0 and each prints its evidence directory.

- [ ] **Step 3: Compare deterministic logical outputs**

```powershell
$Result1 = Get-ChildItem $Run1 -Recurse -Filter taskspec-memory-result.json | Select-Object -First 1
$Result2 = Get-ChildItem $Run2 -Recurse -Filter taskspec-memory-result.json | Select-Object -First 1
$Report1 = Get-ChildItem $Run1 -Recurse -Filter taskspec-memory-report.md | Select-Object -First 1
$Report2 = Get-ChildItem $Run2 -Recurse -Filter taskspec-memory-report.md | Select-Object -First 1
if ((Get-FileHash $Result1.FullName -Algorithm SHA256).Hash -ne (Get-FileHash $Result2.FullName -Algorithm SHA256).Hash) { throw 'result digest mismatch' }
if ((Get-FileHash $Report1.FullName -Algorithm SHA256).Hash -ne (Get-FileHash $Report2.FullName -Algorithm SHA256).Hash) { throw 'report digest mismatch' }
```

Expected result SHA-256: `7ddd325b789eb0b71c5ae601ab8e54a88674ea87bda39084db63caecfd404a8a`.

Expected report SHA-256: `d5676294786a7f3a9182a7d50cb38734f3222c119258927b0e5c065b17b5e462`.

- [ ] **Step 4: Refresh committed evidence from the second clean run**

```powershell
$Evidence = $Result2.Directory.FullName
Copy-Item -LiteralPath "$Evidence\taskspec-memory-result.json" -Destination 'experiments\memory-gate-b\artifacts\taskspec-memory-result.json'
Copy-Item -LiteralPath "$Evidence\taskspec-memory-report.md" -Destination 'experiments\memory-gate-b\artifacts\taskspec-memory-report.md'
Copy-Item -LiteralPath "$Evidence\container-receipt.json" -Destination 'experiments\memory-gate-b\artifacts\container-receipt.json'
```

- [ ] **Step 5: Verify live invariants and cleanup**

```powershell
docker inspect mypeople --format '{{.State.Running}}|{{.RestartCount}}|{{.Config.Image}}'
docker ps -a --filter 'name=mp-taskspec-' --format '{{.ID}}|{{.Names}}|{{.Status}}'
docker network ls --filter 'name=mp-taskspec-' --format '{{.ID}}|{{.Name}}'
```

Expected: live container reports `true|0|mypeople-node:upgrade-20260719T150005Z`; the two filtered residue lists are empty.

- [ ] **Step 6: Commit suite registration and refreshed evidence**

```powershell
git add verify/run-suite.sh experiments/memory-gate-b/artifacts
git commit -m "test: reproduce provider-neutral memory Gate B"
```

### Task 7: Complete verification and publish a draft pull request

**Files:**
- Verify only; no expected source edits.

- [ ] **Step 1: Run focused contracts**

```powershell
python verify\test_memory_gate_b_experiment.py -v
python verify\test_public_repository.py -v
git diff --check
```

Expected: all tests pass and the diff check emits no output.

- [ ] **Step 2: Run the complete isolated Project Factory verifier**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File verify\Invoke-IsolatedVerify.ps1 -Image 'mypeople-node:upgrade-20260719T150005Z' -TimeoutSeconds 1800
```

Expected: exit 0 and `Isolated MyPeople verification passed.`, including the focused experiment contract and J1-J52.

- [ ] **Step 3: Review exact publication scope**

```powershell
git status --short --branch
git diff origin/main...HEAD --stat
git diff origin/main...HEAD --name-only
git log --oneline origin/main..HEAD
```

Expected: only the approved design/plan, `experiments/memory-gate-b/`, the root README link, and two verification files are present.

- [ ] **Step 4: Push the branch**

```powershell
git push -u origin feat/memory-gate-b-experiment
```

- [ ] **Step 5: Open a draft pull request**

Create a draft PR targeting `main` with title:

```text
Publish provider-neutral memory Gate B experiment
```

The body must summarize the provider-neutral boundary, locked dataset, no-live-runtime guarantee, deterministic results, focused tests, full isolated verifier, and exact commands used.

- [ ] **Step 6: Record the published URL and leave the worktree intact**

Run:

```powershell
gh pr view --json number,title,state,isDraft,url,headRefName,baseRefName
git status --short --branch
```

Expected: a draft PR from `feat/memory-gate-b-experiment` to `main`, and a clean retained worktree for review feedback.
