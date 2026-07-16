# Isolated Full Verifier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the complete MyPeople verification suite only inside a disposable, credential-free Docker boundary.

**Architecture:** Host launchers create a unique Compose project and evidence directory. A hardened, portless service runs a guarded suite against disposable runtime data and is always torn down.

**Tech Stack:** Bash, PowerShell, Docker Compose, Python `unittest`.

---

### Task 1: Isolation contract

**Files:**
- Create: `verify/test_isolated_verifier.py`
- Modify: `verify/core_verify.py`

- [ ] Write tests that require fail-closed markers, unique project names, no host ports/credentials/production volumes, bounded execution, cleanup, and failure evidence.
- [ ] Run `python verify/test_isolated_verifier.py` and confirm it fails because the isolated entrypoints do not exist.
- [ ] Add the isolation guard to `core_verify.py` and keep the focused test red until the orchestrator exists.

### Task 2: Disposable Linux/Docker verifier

**Files:**
- Modify: `verify/verify.sh`
- Create: `verify/compose.isolated.yml`
- Create: `verify/container-entrypoint.sh`
- Create: `verify/run-suite.sh`

- [ ] Move the existing suite command list into `run-suite.sh` behind a mandatory isolation guard.
- [ ] Add a hardened Compose service with a read-only source mount, tmpfs runtime/credential paths, no host ports, no Docker socket, `network_mode: none`, dropped capabilities, and synthetic environment values.
- [ ] Implement unique-project orchestration, timeout handling, deterministic exit codes, unconditional cleanup, and failure evidence retention in `verify.sh`.
- [ ] Run `python verify/test_isolated_verifier.py` and confirm the Linux/Docker contracts pass.

### Task 3: Windows host entrypoint

**Files:**
- Create: `verify/Invoke-IsolatedVerify.ps1`

- [ ] Implement the same unique project, timeout, output capture, cleanup, evidence, and exit-code contract without importing live MyPeople configuration.
- [ ] Run `python verify/test_isolated_verifier.py` and confirm all focused contracts pass.

### Task 4: Verification and documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/USER-MANUAL.md`

- [ ] Document both safe host commands and the evidence/exit-code contract.
- [ ] Run focused verifier contracts, public repository tests, shell syntax checks, and PowerShell parsing.
- [ ] Run a disposable Docker smoke and confirm no verification container/project remains.
- [ ] Review `git diff --check`, commit the isolated verifier, and report the exact evidence.
