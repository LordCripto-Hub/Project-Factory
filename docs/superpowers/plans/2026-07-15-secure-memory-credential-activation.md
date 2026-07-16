# Secure Memory Credential Activation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add reversible DPAPI-to-tmpfs credential delivery and verify the controlled, read-only Cloudflare MCP path without exposing a persistent bearer to workers.

**Architecture:** Windows owns the encrypted bearer credential and streams it into a disposable container tmpfs only for the synthetic E2E. Project profiles carry only a restricted file reference, while the existing Python compiler and Node gateway remain the only recall path. Persistent activation is fail-closed until a separate broker identity isolates the credential from workers.

**Tech Stack:** PowerShell 5.1, Windows DPAPI, Docker Compose tmpfs, Python 3, Node MCP SDK, unittest.

---

### Task 1: Restrict secret-file references at the ProjectProfile boundary

**Files:**
- Modify: `bin/project_context.py`
- Modify: `verify/test_project_context.py`
- Modify: `verify/test_memory_gateway.py`

- [ ] **Step 1: Write failing validation and gateway tests**

Add tests proving that `file:///run/mypeople-secrets/MYPEOPLE_MEMORY_TOKEN` is
accepted, paths outside that directory are rejected, a missing file becomes
`unauthorized`, and the resolved value is present only in the gateway child
environment.

- [ ] **Step 2: Run the focused tests and confirm RED**

```powershell
docker exec -e PYTHONPATH=/home/mp/mypeople/bin mypeople python3 /home/mp/mypeople/verify/test_project_context.py
docker exec -e PYTHONPATH=/home/mp/mypeople/bin mypeople python3 /home/mp/mypeople/verify/test_memory_gateway.py
```

Expected: the new `file://` cases fail because only `env://` is supported.

- [ ] **Step 3: Implement the closed credential resolver**

Add a resolver that accepts either the existing `env://NAME` pattern or the
exact `/run/mypeople-secrets/NAME` file root, reads at most 4096 bytes, rejects
empty or oversized values, and returns the environment name/value used only by
the gateway child. Do not add the reference or value to the TaskSpec.

- [ ] **Step 4: Run the focused tests and confirm GREEN**

Run the two commands from Step 2. Expected: all tests pass.

### Task 2: Add an atomic ProjectProfile activation helper

**Files:**
- Create: `bin/memory_profile.py`
- Create: `bin/memory-profile`
- Create: `verify/test_memory_profile.py`
- Modify: `install.sh`

- [ ] **Step 1: Write failing profile-update tests**

Cover enable, disable, revision increment, filename/body slug matching, HTTPS
validation, atomic mode-0600 writes, refusal to enable without the tmpfs secret,
and preservation of all non-memory profile fields.

- [ ] **Step 2: Run the new test and confirm RED**

```powershell
docker exec -e PYTHONPATH=/home/mp/mypeople/bin mypeople python3 /home/mp/mypeople/verify/test_memory_profile.py
```

Expected: import or executable-not-found failure.

- [ ] **Step 3: Implement the minimal updater and CLI**

The CLI accepts `enable|disable`, `--project`, `--server-url`, and the runtime
profile/secret paths. It uses `validate_profile`, changes only `revision` and
`memory`, writes atomically, and prints metadata only.

- [ ] **Step 4: Run the new and existing profile tests**

```powershell
docker exec -e PYTHONPATH=/home/mp/mypeople/bin mypeople python3 /home/mp/mypeople/verify/test_memory_profile.py
docker exec -e PYTHONPATH=/home/mp/mypeople/bin mypeople python3 /home/mp/mypeople/verify/test_project_context.py
```

Expected: all tests pass.

### Task 3: Add the Windows DPAPI store and tmpfs injector

**Files:**
- Create: `windows/MyPeople.Memory.psm1`
- Create: `windows/Set-MyPeopleMemoryCredential.ps1`
- Create: `windows/Set-MyPeopleMemoryActivation.ps1`
- Create: `verify/Test-WindowsMemory.ps1`
- Create: `verify/test_windows_memory.py`

- [ ] **Step 1: Write failing PowerShell contract and round-trip tests**

Use a temporary `LOCALAPPDATA` to prove DPAPI save/load equality, metadata-only
settings, no plaintext secret on disk, strict URL/project validation, and
static stdin-based Docker injection with no secret in arguments or output.

- [ ] **Step 2: Run the Windows test and confirm RED**

```powershell
python verify/test_windows_memory.py
```

Expected: the module and scripts are missing.

- [ ] **Step 3: Implement DPAPI, settings, injection, and enable/disable entry points**

Use `[Security.Cryptography.ProtectedData]` with `CurrentUser`, ACL-protected
directories, atomic writes, and a hidden redirected-stdin Docker process. The
setup command may generate a 32-byte high-entropy token and rotate the Worker
secret through Wrangler stdin; it must never print the token.

- [ ] **Step 4: Run the Windows tests and confirm GREEN**

```powershell
python verify/test_windows_memory.py
```

Expected: all tests pass and no plaintext credential appears in fixtures.

### Task 4: Make one-click startup clear or reject persistent memory

**Files:**
- Modify: `docker/compose.volume-backed.yml`
- Modify: `windows/Start-MyPeople.ps1`
- Modify: `verify/test_windows_launcher.py`
- Modify: `verify/test_docker_persistence.py`

- [ ] **Step 1: Add failing launcher and Compose assertions**

Assert a `tmpfs` at `/run/mypeople-secrets` with uid/gid 1000 and mode 0700,
fail-closed rejection of persistent enabled settings, disabled-startup cleanup,
and no token in Compose environment or volumes.

- [ ] **Step 2: Run the tests and confirm RED**

```powershell
python verify/test_windows_launcher.py
python verify/test_docker_persistence.py
```

- [ ] **Step 3: Implement startup cleanup and fail-closed rejection**

Import the memory module, read non-secret settings, clear the tmpfs secret when
disabled, and reject an enabled persistent setting until the separate broker
security gate is complete. Do not change provider-profile startup behavior.

- [ ] **Step 4: Run launcher and persistence tests**

Expected: all tests pass.

### Task 5: Rotate and run the synthetic E2E in an agent-free container

**Files:**
- Modify: `docs/USER-MANUAL.md`
- Create: `verify/test_memory_activation_e2e.py`

- [ ] **Step 1: Add the E2E harness with a synthetic-only guard**

The harness must hard-code the pilot endpoint/project, verify the exact
`/health` contract, compile positive and cross-project-negative bounded
TaskSpecs through the real gateway, assert project/provenance, and never edit a
durable ProjectProfile or board.

- [ ] **Step 2: Rotate the Cloudflare secret and store it with DPAPI**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File windows\Set-MyPeopleMemoryCredential.ps1 -Generate -CloudflareRepository C:\tmp\mypeople-memory-cloudflare-work
```

Expected: success metadata only; no token output.

- [ ] **Step 3: Start a disposable candidate container and execute the E2E**

Use the reviewed candidate image without starting managed agents, run the
synthetic activation test, confirm the tmpfs credential is absent afterward,
and remove the disposable container. Expected: bounded claims, zero
cross-project results, complete provenance, and `aiUsage: not_measured`.

- [ ] **Step 4: Run regression and secret checks**

```powershell
docker exec mypeople bash /home/mp/mypeople/verify/verify.sh
git grep -n -I -E "(Bearer [A-Za-z0-9_-]{12,}|AUTH_TOKEN=|MYPEOPLE_MEMORY_TOKEN=.+)" -- .
git diff --check
```

Expected: verifier green, secret scan empty, diff check clean.

### Task 6: Publish both repositories deliberately

**Files:**
- External memory repository: merge `feat/project-scoped-pilot` into `main` after checks.
- Project Factory repository: commit the activation cycle and publish through the Boss-authorized Windows credential bridge.

- [ ] **Step 1: Review both clean diffs and English/public policy checks**
- [ ] **Step 2: Merge the verified memory PR without force push**
- [ ] **Step 3: Publish Project Factory only after a fresh Boss approval binds the exact SHA**
- [ ] **Step 4: Verify local, Docker, and remote SHAs plus live health**
