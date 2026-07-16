# Volume-Backed Image Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a permanent, provider-independent, backup-first command for upgrading the pinned volume-backed MyPeople image with automatic tag-based rollback.

**Architecture:** A PowerShell transaction reuses the Docker migration helpers for hashes, redaction, atomic locking, and evidence. It verifies the source packaged inside a reviewed image, pins candidate and rollback IDs to transaction-owned tags, produces a consistent sensitive local restore archive, updates the pinned Compose deployment with `--force-recreate`, and restores the retained rollback tag on any post-mutation failure.

**Tech Stack:** PowerShell 5.1, Docker Desktop/Compose v2, Python contract tests, existing MyPeople migration module.

---

### Task 1: Lock the upgrade safety contract

**Files:**
- Create: `verify/Test-WindowsDockerUpgrade.ps1`
- Modify: `verify/test_docker_persistence.py`

- [ ] **Step 1: Add failing static contracts**

Require `windows/Upgrade-MyPeopleDockerImage.ps1`, explicit `CandidateImage`,
clean Git state, packaged-source `Invoke-IsolatedVerify.ps1`, protected portable
backup, sensitive-restore-material classification, archive hash comparison,
atomic cross-operation locking, `--force-recreate`, stable board/roster checks,
exact writable volume mappings, read-only seed bind, project tmux,
transaction-owned image-tag rollback, and transaction evidence. Forbid `docker rename`,
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
image, health endpoints, exact writable named-volume mappings, and sufficient
free space. Acquire one atomic Docker-operation lock, pin both image IDs, and run
`verify/Invoke-IsolatedVerify.ps1` against packaged candidate source before mutation.

- [ ] **Step 2: Implement consistent portable backup**

Stop the live container, mount all eight volumes read-only in a temporary
helper, copy only portable state, remove common secret-bearing filenames,
sanitize workspace Git configs, classify the archive as non-publishable sensitive
restore material, compare container and host SHA-256 values, and restart the old
deployment before proceeding.

- [ ] **Step 3: Implement deployment and rollback**

Back up the redacted `.env` and Compose content, bind the transaction-owned
candidate tag, run Compose with `--force-recreate`, and verify health, PID 1,
supervisors, exact volumes, seed bind, tmux, and stable hashes. On failure restore
the old Compose content and recreate the retained rollback tag. Never activate a
provider.

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

Keep backup data, deployment `.env`, provider state, and local transaction
artifacts outside Git. Never publish the portable restore archive.
