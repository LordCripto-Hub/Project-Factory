# Volume-Backed Image Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a permanent, provider-independent, backup-first command for upgrading the pinned volume-backed MyPeople image with automatic tag-based rollback.

**Architecture:** A PowerShell transaction reuses the Docker migration helpers for hashes, redaction, and evidence. It verifies a reviewed image in the isolated verifier, produces a consistent portable backup, updates the pinned Compose deployment with `--force-recreate`, and restores the prior image tag on any post-mutation failure.

**Tech Stack:** PowerShell 5.1, Docker Desktop/Compose v2, Python contract tests, existing MyPeople migration module.

---

### Task 1: Lock the upgrade safety contract

**Files:**
- Create: `verify/Test-WindowsDockerUpgrade.ps1`
- Modify: `verify/test_docker_persistence.py`

- [ ] **Step 1: Add failing static contracts**

Require `windows/Upgrade-MyPeopleDockerImage.ps1`, explicit `CandidateImage`,
clean Git state, `Invoke-IsolatedVerify.ps1`, protected portable backup,
authentication-file exclusions, archive hash comparison, `--force-recreate`,
stable board/roster checks, eight named volumes, read-only seed bind, project
tmux, image-tag rollback, and transaction evidence. Forbid `docker rename`,
`down -v`, volume removal, provider-profile imports, provider activation, and
Boss-alive gates.

- [ ] **Step 2: Run the contracts and observe RED**

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File verify\Test-WindowsDockerUpgrade.ps1
python -B verify\test_docker_persistence.py
```

Expected: failure because the permanent upgrade command does not exist.

### Task 2: Implement the permanent transaction

**Files:**
- Create: `windows/Upgrade-MyPeopleDockerImage.ps1`

- [ ] **Step 1: Implement preflight and isolated candidate verification**

Validate Docker, clean Git state, candidate image, pinned deployment, live
image, health endpoints, eight named volumes, and sufficient free space. Run
`verify/Invoke-IsolatedVerify.ps1` against the exact candidate before mutation.

- [ ] **Step 2: Implement consistent portable backup**

Stop the live container, mount all eight volumes read-only in a temporary
helper, copy only portable state, remove secret-like files, sanitize workspace
Git configs, create the archive, compare container and host SHA-256 values, and
restart the old deployment before proceeding.

- [ ] **Step 3: Implement deployment and rollback**

Back up the pinned `.env` and Compose content, bind the candidate image, run
Compose with `--force-recreate`, and verify health, PID 1, supervisors, volumes,
seed bind, tmux, and stable hashes. On failure restore the old pinned files and
recreate the previous image. Never activate a provider.

- [ ] **Step 4: Run GREEN contracts**

Run the Task 1 commands. Expected: both pass.

### Task 3: Document and verify the public workflow

**Files:**
- Modify: `README.md`
- Modify: `docs/USER-MANUAL.md`

- [ ] **Step 1: Document build, verify, upgrade, evidence, and rollback**

Document the exact English commands and state clearly that provider sessions
are independent of code upgrades.

- [ ] **Step 2: Run focused and complete verification**

Run the new PowerShell contract, Docker persistence test, public repository
test, `git diff --check`, and the full isolated verifier against the live
candidate image.

- [ ] **Step 3: Commit, review, push, and open the GitHub pull request**

Keep backup data, deployment `.env`, provider state, and transaction evidence
outside Git.
