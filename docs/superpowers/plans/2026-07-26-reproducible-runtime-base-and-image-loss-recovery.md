# Reproducible Runtime Base and Image-Loss Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild and safely recover the customized MyPeople deployment from repository-owned images when its Docker container and images are missing but its eight named volumes survive.

**Architecture:** A pinned Debian recovery base supplies only OS/runtime tools, while the existing runtime-image Dockerfile remains the application overlay. A new Windows recovery transaction verifies the candidate in isolation, creates a protected backup from read-only volume mounts, pins the exact image ID, recreates Compose over the existing volumes, and leaves memory disabled at a successful Gate B preflight.

**Tech Stack:** Docker BuildKit and Compose v2, Debian 12, PowerShell 5.1, Python `unittest`, existing MyPeople Docker migration module, existing isolated verifier.

**Approved design:** `docs/superpowers/specs/2026-07-26-reproducible-runtime-base-and-image-loss-recovery-design.md`

---

## Fixed boundaries

- Worktree: `C:\tmp\mypeople-memory-gate-b-live-canary`
- Branch: `feat/memory-gate-b-comparison`
- Starting commit: `d0d64fd`
- Canonical volumes: exactly the eight entries in `docker/state-volumes.json`
- No existing `mypeople` container or `mypeople-node:*` image is assumed.
- No volume deletion, rename, restore, or formatting is permitted.
- Tailscale and the floating microphone remain absent.
- Memory comparison remains disabled and no paired arm is executed.
- Public code and documentation remain English-only and secret-free.

### Task 1: Specify the reproducible base contract

**Files:**

- Create: `verify/test_reproducible_runtime_base.py`
- Modify: `verify/run-suite.sh`

- [ ] **Step 1: Write the failing Dockerfile contract test**

Create a test that reads `docker/Dockerfile.recovery-base` and requires the
approved defaults and security boundary:

```python
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ReproducibleRuntimeBaseContract(unittest.TestCase):
    def setUp(self):
        self.path = ROOT / "docker" / "Dockerfile.recovery-base"
        self.text = self.path.read_text(encoding="utf-8")

    def test_pins_compatible_runtime_and_non_root_identity(self):
        for token in (
            "FROM debian:12-slim",
            "ARG TTYD_VERSION=1.7.7",
            "ARG CLAUDE_VERSION=2.1.205",
            "ARG CODEX_VERSION=0.144.3",
            "groupadd --gid 1000 mp",
            "useradd --uid 1000 --gid 1000",
            "USER mp",
        ):
            self.assertIn(token, self.text)

    def test_installs_and_verifies_required_commands(self):
        for command in (
            "python3", "node", "npm", "tmux", "ttyd", "git",
            "rg", "codex", "claude",
        ):
            self.assertIn(f"command -v {command}", self.text)
        self.assertIn("sha256sum -c -", self.text)

    def test_contains_no_credentials_or_remote_network_runtime(self):
        self.assertNotRegex(
            self.text,
            re.compile(r"(?i)COPY .*?(auth|credential|token|\\.env|\\.codex|\\.claude)"),
        )
        self.assertNotIn("tailscale", self.text.lower())
        self.assertNotIn("TS_AUTHKEY", self.text)
```

- [ ] **Step 2: Run the test and verify RED**

```powershell
python verify\test_reproducible_runtime_base.py
```

Expected: failure because `docker/Dockerfile.recovery-base` does not exist.

- [ ] **Step 3: Register the focused test**

Add this command to `verify/run-suite.sh` beside the other Docker contracts:

```bash
python3 verify/test_reproducible_runtime_base.py
```

- [ ] **Step 4: Commit the red contract**

```powershell
git add verify/test_reproducible_runtime_base.py verify/run-suite.sh
git commit -m "test: define reproducible runtime base contract"
```

### Task 2: Implement and smoke the recovery base

**Files:**

- Create: `docker/Dockerfile.recovery-base`
- Modify: `.dockerignore`

- [ ] **Step 1: Add the minimal pinned base**

Implement this structure without project source or credentials:

```dockerfile
FROM debian:12-slim

ARG TARGETARCH
ARG TTYD_VERSION=1.7.7
ARG CLAUDE_VERSION=2.1.205
ARG CODEX_VERSION=0.144.3

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash ca-certificates curl git iproute2 jq nodejs npm procps python3 \
    ripgrep sudo tmux unzip \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 1000 mp \
    && useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash mp \
    && echo "mp ALL=(ALL) NOPASSWD:ALL" >/etc/sudoers.d/mp \
    && chmod 0440 /etc/sudoers.d/mp

RUN set -eux; \
    case "$TARGETARCH" in \
      amd64) asset=x86_64; digest=8a217c968aba172e0dbf3f34447218dc015bc4d5e59bf51db2f2cd12b7be4f55 ;; \
      arm64) asset=aarch64; digest=b38acadd89d1d396a0f5649aa52c539edbad07f4bc7348b27b4f4b7219dd4165 ;; \
      *) exit 1 ;; \
    esac; \
    curl -fsSL "https://github.com/tsl0922/ttyd/releases/download/${TTYD_VERSION}/ttyd.${asset}" -o /usr/local/bin/ttyd; \
    echo "${digest}  /usr/local/bin/ttyd" | sha256sum -c -; \
    chmod 0755 /usr/local/bin/ttyd

USER mp
WORKDIR /home/mp
ENV PATH="/home/mp/.local/bin:${PATH}"
RUN curl -fsSL https://claude.ai/install.sh | bash -s "${CLAUDE_VERSION}" \
    && curl -fsSL https://chatgpt.com/codex/install.sh | \
       CODEX_RELEASE="${CODEX_VERSION}" CODEX_NON_INTERACTIVE=1 sh

USER root
RUN cp -L /home/mp/.local/bin/claude /usr/local/bin/claude \
    && cp -L /home/mp/.local/bin/codex /usr/local/bin/codex \
    && for command in python3 node npm tmux ttyd git rg codex claude; do command -v "$command"; done

USER mp
ENTRYPOINT ["/usr/bin/env"]
CMD ["sleep", "infinity"]
```

- [ ] **Step 2: Harden build-context exclusions**

Ensure `.dockerignore` explicitly excludes:

```text
**/auth.json
**/*credential*
**/*token*
**/portable-state.tar.gz
```

- [ ] **Step 3: Run static tests and verify GREEN**

```powershell
python verify\test_reproducible_runtime_base.py
python verify\test_public_repository.py
git diff --check
```

Expected: all tests pass and no whitespace errors.

- [ ] **Step 4: Build the base and run a disposable command smoke**

```powershell
$sha = (git rev-parse --short=7 HEAD).Trim()
$base = "mypeople-node:recovery-base-$sha"
docker build --pull -f docker\Dockerfile.recovery-base -t $base .
docker run --rm --entrypoint sh $base -lc 'test "$(id -u)" = 1000 && for c in python3 node npm tmux ttyd git rg codex claude; do command -v "$c"; done'
```

Expected: exit `0`; every command resolves; UID is `1000`.

- [ ] **Step 5: Commit**

```powershell
git add docker/Dockerfile.recovery-base .dockerignore
git commit -m "build: add reproducible MyPeople runtime base"
```

### Task 3: Define image-loss recovery refusals

**Files:**

- Create: `verify/test_windows_docker_recovery.py`
- Create: `windows/Recover-MyPeopleDockerDeployment.ps1`

- [ ] **Step 1: Write the failing recovery-script contract**

The test must require:

```python
def test_recovery_is_fail_closed_and_volume_preserving(self):
    text = (ROOT / "windows" / "Recover-MyPeopleDockerDeployment.ps1").read_text()
    for token in (
        "[Parameter(Mandatory)][string]$CandidateImage",
        "[Parameter(Mandatory)][string]$VerificationReceipt",
        "Get-MyPeopleVolumeContract",
        "Enter-MyPeopleDockerOperationLock",
        "portable-state.tar.gz",
        "candidate-verified",
        "beforeBoardSha256",
        "beforeStableRosterSha256",
        "MYPEOPLE_MEMORY_COMPARISON_ENABLED=0",
        "recovery_failed",
    ):
        self.assertIn(token, text)
    for forbidden in (
        "docker volume rm",
        "docker compose down -v",
        "docker system prune",
        "docker volume prune",
    ):
        self.assertNotIn(forbidden, text)
```

Also require refusal when `mypeople` already exists, any canonical volume is
missing, the receipt image ID differs, or free space is below the threshold.

- [ ] **Step 2: Run and verify RED**

```powershell
python verify\test_windows_docker_recovery.py
```

Expected: failure because the recovery script does not exist.

- [ ] **Step 3: Add a `-PlanOnly` interface first**

Create the script with these parameters:

```powershell
param(
    [Parameter(Mandatory)][string]$CandidateImage,
    [Parameter(Mandatory)][string]$VerificationReceipt,
    [switch]$Execute,
    [ValidateRange(1, 1024)][int]$MinimumFreeGiB = 4
)
```

`-PlanOnly` is represented by omitting `-Execute`. It performs all read-only
preflight checks, writes a protected transaction receipt with stage `planned`,
and prints the receipt path. It never changes Compose, a container, or a
volume.

- [ ] **Step 4: Implement exact preflight data**

Use the existing module interfaces:

```powershell
$contract = Get-MyPeopleVolumeContract -Root $root
$operationLock = Enter-MyPeopleDockerOperationLock `
    -Path $operationLockPath -Owner "recovery:$stamp"

if (Test-MyPeopleDockerObject -Type container -Name 'mypeople') {
    throw 'Recovery requires the mypeople container to be absent.'
}
foreach ($name in $contract.Keys) {
    if (-not (Test-MyPeopleDockerObject -Type volume -Name $name)) {
        throw "Required state volume is missing: $name"
    }
}
```

Parse the isolated verifier receipt, require `status: pass`, compare its
`imageId` to `docker image inspect`, and record source commit plus candidate
image ID before any mutation.

- [ ] **Step 5: Run static contracts and commit**

```powershell
python verify\test_windows_docker_recovery.py
powershell -NoProfile -Command "[void][scriptblock]::Create([IO.File]::ReadAllText('windows\Recover-MyPeopleDockerDeployment.ps1'))"
git diff --check
git add verify/test_windows_docker_recovery.py windows/Recover-MyPeopleDockerDeployment.ps1
git commit -m "feat: add fail-closed image-loss recovery preflight"
```

### Task 4: Implement backup, deploy, and honest failure state

**Files:**

- Modify: `windows/Recover-MyPeopleDockerDeployment.ps1`
- Modify: `verify/test_windows_docker_recovery.py`
- Modify: `verify/run-suite.sh`

- [ ] **Step 1: Add failing tests for execution ordering**

Require source ordering:

```python
self.assertLess(text.index("candidate-verified"), text.index("portable-backup"))
self.assertLess(text.index("portable-backup"), text.index("deploy"))
self.assertLess(text.index("deploy"), text.index("complete"))
```

Require the archive helper to mount every source volume read-only, remove
credential-shaped files from the portable copy, verify host/container SHA-256,
and atomically update only `MYPEOPLE_IMAGE`.

- [ ] **Step 2: Verify RED**

```powershell
python verify\test_windows_docker_recovery.py
```

Expected: execution-order assertions fail.

- [ ] **Step 3: Add read-only state capture and portable backup**

Reuse the reviewed archive body from
`windows/Upgrade-MyPeopleDockerImage.ps1`, but do not stop or start a live
container because none exists. Mount each canonical volume at
`/src/<volume-name>:ro`, copy only the approved state subset, delete
credential-shaped filenames from the portable copy, and verify the copied
archive hash.

Capture board and stable roster hashes from the helper:

```powershell
$boardHash = (Invoke-MyPeopleDocker -Arguments @(
    'exec', $helper, 'sha256sum',
    '/src/mypeople-todos/board.v2.json'
) -Capture).Split()[0]
$rosterJson = Invoke-MyPeopleDocker -Arguments @(
    'exec', $helper, 'cat', '/src/mypeople-run/roster.json'
) -Capture
$stableRosterHash = Get-MyPeopleStableRosterHash -Json $rosterJson
```

- [ ] **Step 4: Add exact image pinning and Compose recovery**

Tag the candidate image ID to `mypeople-node:recovery-<timestamp>`, preserve
the previous environment text, atomically replace only `MYPEOPLE_IMAGE`, copy
the reviewed Compose file, then run:

```powershell
docker compose --project-name mypeople `
  --env-file $environmentPath -f $composePath `
  up --detach --force-recreate
```

Verify the exact image ID, mount contract, hashes, local port bindings,
comparison flag `0`, restart count `0`, and HTTP/terminal health.

- [ ] **Step 5: Implement honest rollback**

On failure after deployment mutation:

```powershell
docker rm -f mypeople
[IO.File]::WriteAllText($environmentPath, $oldEnvironment, $utf8NoBom)
[IO.File]::WriteAllText($composePath, $oldCompose, $utf8NoBom)
$state.stage = 'recovery_failed'
$state.oldServiceRestored = $false
```

Do not alter volumes or claim rollback success. Preserve the archive and
transaction receipt.

- [ ] **Step 6: Verify and commit**

```powershell
python verify\test_windows_docker_recovery.py
python verify\test_reproducible_runtime_base.py
python verify\test_public_repository.py
git diff --check
git add windows/Recover-MyPeopleDockerDeployment.ps1 verify/test_windows_docker_recovery.py verify/run-suite.sh
git commit -m "feat: recover MyPeople from surviving volumes"
```

### Task 5: Build and qualify the exact runtime candidate

**Files:**

- Create locally only: `%LOCALAPPDATA%\MyPeople\state\recovery-verification-<sha>.json`

- [ ] **Step 1: Confirm a clean source boundary**

```powershell
git status --short
$fullSha = (git rev-parse HEAD).Trim()
$shortSha = (git rev-parse --short=7 HEAD).Trim()
```

Expected: clean worktree and non-empty SHA values.

- [ ] **Step 2: Build the application overlay**

```powershell
$base = "mypeople-node:recovery-base-$shortSha"
$candidate = "mypeople-node:recovery-candidate-$shortSha"
docker build -f docker\Dockerfile.runtime-image `
  --build-arg BASE_IMAGE=$base -t $candidate .
```

- [ ] **Step 3: Run disposable runtime smoke**

```powershell
docker run --rm --entrypoint sh $candidate -lc `
  'test "$(id -u)" = 1000 && test -x /home/mp/mypeople/bin/runtime-supervisor.sh && for c in python3 node npm tmux ttyd git rg codex claude; do command -v "$c"; done'
```

- [ ] **Step 4: Run the complete isolated verifier**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File verify\Invoke-IsolatedVerify.ps1 `
  -Image $candidate -TimeoutSeconds 1800 -UsePackagedSource
```

Expected: focused contracts and J1-J52 pass without mounting live volumes.

- [ ] **Step 5: Write the protected verification receipt**

Write schema version, `status: pass`, source commit, image reference, exact
image ID, verifier command, timestamp, and no credentials:

```json
{
  "schemaVersion": 1,
  "status": "pass",
  "sourceCommit": "<full SHA>",
  "image": "mypeople-node:recovery-candidate-<short SHA>",
  "imageId": "sha256:<exact ID>",
  "verification": "isolated-packaged-source",
  "comparisonExecuted": false
}
```

Protect the containing `%LOCALAPPDATA%\MyPeople\state` directory with the same
ACL helper used by provider profiles.

### Task 6: Recover the live control plane over surviving volumes

**Files:**

- Runtime evidence only under `%LOCALAPPDATA%\MyPeople\backups\docker-recovery\<timestamp>`

- [ ] **Step 1: Run plan-only recovery**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File windows\Recover-MyPeopleDockerDeployment.ps1 `
  -CandidateImage $candidate `
  -VerificationReceipt $receipt
```

Expected: stage `planned`, all eight volumes present, container absent,
candidate image ID matches, and no Docker mutation.

- [ ] **Step 2: Review the redacted receipt**

Confirm it contains no auth value, complete session token, provider transcript,
or portable archive contents. Confirm the candidate/source/image IDs match.

- [ ] **Step 3: Execute recovery**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File windows\Recover-MyPeopleDockerDeployment.ps1 `
  -CandidateImage $candidate `
  -VerificationReceipt $receipt `
  -Execute
```

Expected: `RECOVERY PASS`, new protected archive, exact eight-volume mount
contract, unchanged board/stable-roster hashes, HTTP `200/200`, terminal ready,
restart count `0`, and comparison flag `0`.

- [ ] **Step 4: Rehydrate provider profile and agents**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File windows\Start-MyPeople.ps1 `
  -NoBrowser -NonInteractive
```

Expected: provider profile validates; Boss and Nightwatch become alive. If the
provider is unavailable, the launcher must report degraded mode and keep
provider launches paused rather than opening OAuth.

- [ ] **Step 5: Verify live invariants**

```powershell
docker inspect -f 'running={{.State.Running}} restart={{.RestartCount}} image={{.Config.Image}}' mypeople
docker exec mypeople /home/mp/mypeople/bin/mp status
docker exec mypeople tmux has-session -t repo-project-factory
```

Also verify no comparison card, worker, conversation, sidecar, or temporary
result directory exists.

### Task 7: Stop at memory preflight and publish the recovery path

**Files:**

- Modify: `README.md`
- Modify: `docs/USER-MANUAL.md`
- Modify: `docs/superpowers/plans/2026-07-26-reproducible-runtime-base-and-image-loss-recovery.md`

- [ ] **Step 1: Run Gate B preflight only**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File windows\Start-MyPeopleMemoryComparison.ps1 `
  -Action Preflight
```

Expected: exact dataset/source/fixture/offline bindings qualify; Boss is alive;
the feature remains opt-in; no paired arm is created.

- [ ] **Step 2: Document rebuild and recovery commands**

Document:

- base build;
- application overlay build;
- isolated verification receipt;
- plan-only recovery;
- explicit recovery;
- one-click launcher;
- Gate B preflight;
- explicit warning that backups do not contain Docker image layers and that
  `docker compose down -v` remains forbidden.

- [ ] **Step 3: Run final verification**

```powershell
python verify\test_reproducible_runtime_base.py
python verify\test_windows_docker_recovery.py
python verify\test_public_repository.py
powershell -NoProfile -ExecutionPolicy Bypass `
  -File verify\Invoke-IsolatedVerify.ps1 `
  -Image $candidate -TimeoutSeconds 1800 -UsePackagedSource
git diff --check
git status --short
```

Manually confirm:

- memory comparison flag is `0`;
- no synthetic resource exists;
- board and stable-roster hashes match the recovery receipt;
- the protected archive and verification receipt are not tracked by Git;
- public text is English-only.

- [ ] **Step 4: Commit documentation and plan tracking**

```powershell
git add README.md docs/USER-MANUAL.md docs/superpowers/plans/2026-07-26-reproducible-runtime-base-and-image-loss-recovery.md
git commit -m "docs: document reproducible MyPeople recovery"
```

- [ ] **Step 5: Push the existing feature branch**

```powershell
git push origin feat/memory-gate-b-comparison
```

Update draft PR #12. This completes preparation only. Running the three paired
Gate B cases requires a new explicit approval.

---

## Execution record

Completed on 2026-07-26:

- rebuilt a repository-owned Debian 12 base with pinned Node 22, Codex, Claude,
  ttyd, ffmpeg, and non-root UID/GID 1000;
- made the application overlay rebuild locked Playwright, browser, and memory
  gateway dependencies instead of relying on deleted image layers;
- added the fail-closed Windows image-loss recovery transaction;
- passed the complete isolated packaged-source verifier and J1-J52 contracts;
- produced a protected portable backup and recovered the live container over
  the unchanged eight canonical volumes;
- verified exact image ID, restart count zero, preserved board and stable-roster
  hashes, memory flag zero, and live Boss and Nightwatch roles.

The Gate B live preflight was attempted and correctly refused because recovery
kept `MYPEOPLE_MEMORY_COMPARISON_ENABLED=0` and did not start the sidecar. That
preflight is an activation-dependent live gate, not a passive audit. Enabling
it or running paired cases remains outside this recovery approval and requires
a new explicit approval.
