# Persistent Project Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist the Project Factory Git checkout, rehydrate `repo-project-factory`, and allow only an exact Boss-approved commit to reach the publisher.

**Architecture:** Extend the proven volume-backed runtime with one workspace volume and one idempotent workspace supervisor. Reuse MyPeople roster identity, ProjectProfile, atomic JSON, and file locks for a single-use publisher ledger.

**Tech Stack:** Python 3 standard library, Git, tmux, Docker Compose, PowerShell verification, unittest.

---

### Task 1: Lock the workspace contract with failing tests

**Files:**
- Create: `verify/test_project_workspace.py`
- Modify: `verify/test_docker_persistence.py`
- Modify: `docker/state-volumes.json`
- Modify: `docker/compose.volume-backed.yml`

- [ ] **Step 1: Write tests for the eighth volume and workspace validation**

The test must require this contract:

```python
"mypeople-workspaces": "/home/mp/workspaces"
```

It must reject relative workspace paths, paths outside the workspace root,
invalid tmux names, non-HTTPS repositories, and unexpected existing remotes.

- [ ] **Step 2: Run the tests and observe failure**

```powershell
python verify\test_project_workspace.py
python verify\test_docker_persistence.py
```

Expected: FAIL because the module and eighth volume do not exist.

- [ ] **Step 3: Add the volume contract**

Add this Compose mount and named volume:

```yaml
- mypeople-workspaces:/home/mp/workspaces

mypeople-workspaces:
  name: mypeople-workspaces
```

- [ ] **Step 4: Commit the contract**

```powershell
git add verify/test_project_workspace.py verify/test_docker_persistence.py docker/state-volumes.json docker/compose.volume-backed.yml
git commit -m "Define persistent project workspace volume"
```

### Task 2: Implement the idempotent workspace supervisor

**Files:**
- Create: `bin/project_workspace.py`
- Create: `bin/workspace-supervisor.py`
- Create: `docker/project-workspaces.json`
- Modify: `bin/runtime-supervisor.sh`
- Modify: `verify/test_project_workspace.py`

- [ ] **Step 1: Test clone and tmux idempotency**

Use fake Git and tmux runners. Require one clone for an absent workspace, zero
clone/fetch/pull operations for an existing valid workspace, and exactly one
`new-session` call when the tmux session is absent.

- [ ] **Step 2: Run the focused test and observe failure**

```powershell
python verify\test_project_workspace.py
```

Expected: FAIL because `ensure_workspace` and `ensure_tmux_session` are absent.

- [ ] **Step 3: Implement the supervisor without dependencies**

The production command is bounded to:

```text
git clone --origin origin --branch main --single-branch https://github.com/LordCripto-Hub/Project-Factory.git /home/mp/workspaces/project-factory
tmux new-session -d -s repo-project-factory -c /home/mp/workspaces/project-factory
```

No automatic pull, reset, merge, checkout, or push is permitted.

- [ ] **Step 4: Add the child to `runtime-supervisor.sh`**

```bash
spawn workspace-supervisor python3 "$ROOT/bin/workspace-supervisor.py"
```

- [ ] **Step 5: Run tests and commit**

```powershell
python verify\test_project_workspace.py
python verify\test_runtime_supervisor.py
git add bin/project_workspace.py bin/workspace-supervisor.py docker/project-workspaces.json bin/runtime-supervisor.sh verify/test_project_workspace.py verify/test_runtime_supervisor.py
git commit -m "Rehydrate persistent project workspace session"
```

### Task 3: Implement Boss approval and exclusive publication

**Files:**
- Create: `bin/project_publisher.py`
- Create: `verify/test_project_publisher.py`
- Modify: `bin/mp`
- Modify: `bin/mpcommon.py`
- Modify: `boss-CLAUDE.md`

- [ ] **Step 1: Write failing approval tests**

Require a managed master Boss roster record, a review-state project card with
evidence, a 40-character commit, an allowed branch, a bounded expiry, and an
atomic mode-0600 approval file.

- [ ] **Step 2: Write failing publication tests**

Require a pending unexpired approval, clean workspace, exact HEAD, matching
origin, and allowed branch. Assert that the runner receives exactly:

```python
["git", "-C", workspace, "push", "--porcelain", "origin", f"{commit}:refs/heads/{branch}"]
```

- [ ] **Step 3: Run the test and observe failure**

```powershell
python verify\test_project_publisher.py
```

Expected: FAIL because the publisher module is absent.

- [ ] **Step 4: Implement approval and publication commands**

Expose:

```text
mp approve-publish <task-id> --project project-factory --commit <sha> --branch main
mp publish <approval-id>
mp publish-status <approval-id>
```

Publication must use `json_lock`, transition the ledger atomically, append a
sanitized JSONL receipt, and never use `--force`.

- [ ] **Step 5: Add doctrine and commit**

Document that workers commit and provide evidence but never push; Boss verifies
the exact commit before creating the one-time approval.

```powershell
python verify\test_project_publisher.py
python verify\test_codex_boss_doctrine.py
git add bin/project_publisher.py bin/mp bin/mpcommon.py boss-CLAUDE.md verify/test_project_publisher.py verify/test_codex_boss_doctrine.py
git commit -m "Gate project publication on Boss approval"
```

### Task 4: Include the workspace in backup and recovery

**Files:**
- Modify: `windows/Migrate-MyPeopleDockerState.ps1`
- Modify: `windows/Test-MyPeopleDockerRestore.ps1`
- Modify: `verify/Test-WindowsDockerMigration.ps1`

- [ ] **Step 1: Extend the contract test**

Require archive copy from `/home/mp/workspaces` and restore into
`/mnt/mypeople-workspaces` while retaining secret-file exclusion.

- [ ] **Step 2: Run and observe failure**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File verify\Test-WindowsDockerMigration.ps1
```

- [ ] **Step 3: Add archive and restore paths**

Archive `/home/mp/workspaces` into `/tmp/portable/home/mp/workspaces` and restore
the tree to the isolated workspace volume. Do not add credential files.

- [ ] **Step 4: Run and commit**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File verify\Test-WindowsDockerMigration.ps1
git add windows/Migrate-MyPeopleDockerState.ps1 windows/Test-MyPeopleDockerRestore.ps1 verify/Test-WindowsDockerMigration.ps1
git commit -m "Back up persistent project workspaces"
```

### Task 5: Document, deploy, and verify the live runtime

**Files:**
- Modify: `docs/USER-MANUAL.md`
- Modify: `README.md`
- Modify: `verify/verify.sh`

- [ ] **Step 1: Document the operator flow in English**

Include attach, approval, publication, credential boundary, recovery, and the
fact that the tmux session is re-created while Git content remains untouched.

- [ ] **Step 2: Run focused verification**

```powershell
python verify\test_project_workspace.py
python verify\test_project_publisher.py
python verify\test_docker_persistence.py
python verify\test_runtime_supervisor.py
powershell -NoProfile -ExecutionPolicy Bypass -File verify\Test-WindowsDockerMigration.ps1
git diff --check
```

Expected: all commands PASS and `git diff --check` is silent.

- [ ] **Step 3: Commit and deploy a pinned image**

Commit the documentation, copy the committed source into a temporary container
derived from the current pinned image, run focused tests there, commit a new
image tag, update the pinned Compose deployment, and retain the previous image
and environment file for rollback.

- [ ] **Step 4: Run live smoke checks**

```powershell
docker exec mypeople git -C /home/mp/workspaces/project-factory status --short --branch
docker exec mypeople tmux has-session -t repo-project-factory
docker exec mypeople python3 /home/mp/mypeople/verify/test_project_workspace.py
docker exec mypeople python3 /home/mp/mypeople/verify/test_project_publisher.py
```

Expected: repository on `main`, tmux exit 0, and both focused tests PASS.

- [ ] **Step 5: Verify restart persistence**

Record the workspace HEAD, stop `mypeople`, run the Windows launcher, and verify
the same HEAD plus a live `repo-project-factory` session.

