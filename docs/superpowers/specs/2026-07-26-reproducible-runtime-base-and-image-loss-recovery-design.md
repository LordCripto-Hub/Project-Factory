# Reproducible Runtime Base and Image-Loss Recovery Design

## Goal

Make the customized MyPeople deployment recoverable when Docker images and the
container have been deleted but the eight named state volumes and protected
portable backups still exist.

The recovery must rebuild a reviewed runtime image from repository-owned
instructions, verify it without mounting live state, back up the surviving
volumes, recreate the service over those same volumes, and stop at the memory
comparison preflight. It must not enable memory, create comparison cards, or
run provider comparison arms.

## Incident Boundary

The cleanup observed on 2026-07-26 left:

- no `mypeople` container;
- no `mypeople-node:*` image;
- the pinned deployment manifest and environment file;
- all eight canonical MyPeople volumes;
- protected portable backups through `20260722T185325Z`;
- approximately 217 GiB free on the Windows system drive.

The pinned runtime Dockerfile currently requires an earlier local
`mypeople-node` image. That dependency is not reproducible after image cleanup.
The state archives intentionally contain volume data, not Docker image layers,
so they cannot restore the missing executable base.

## Selected Approach

Add one repository-owned recovery base and one host recovery transaction.

The base is infrastructure only. It contains the stable OS and tools required
by the existing `/home/mp/mypeople` runtime:

- Debian 12;
- non-root user `mp` with UID and GID 1000;
- Python 3, Git, curl, jq, tmux, procps, iproute2, unzip, sudo, Node.js, npm,
  ripgrep, and CA certificates;
- ttyd 1.7.7 downloaded for the target architecture and verified against the
  existing upstream SHA-256 values;
- Claude CLI 2.1.205 and Codex CLI 0.144.3 installed without credentials;
- no Tailscale daemon, auth key, provider authentication, project data, or
  user secrets.

The existing `docker/Dockerfile.runtime-image` remains the application overlay:
it copies the reviewed repository source into `/home/mp/mypeople`. The recovery
base therefore does not become a second application source of truth.

## Repository Changes

### Base image

Create `docker/Dockerfile.recovery-base`.

All external executable versions are build arguments with pinned defaults.
The Dockerfile must fail if the ttyd checksum is wrong, an unsupported
architecture is requested, or either agent CLI is absent after installation.
No credential file or host home directory may enter the build context.

### Contract tests

Create `verify/test_reproducible_runtime_base.py` to require:

- pinned Debian, ttyd, Claude, and Codex defaults;
- UID/GID 1000 and user `mp`;
- checksum verification before ttyd becomes executable;
- required runtime commands;
- absence of `COPY` instructions for auth, credential, token, `.env`, or host
  home paths;
- no Tailscale installation or activation;
- final non-root user.

Extend the public-repository sanitation check so the new Dockerfile remains
English-only and secret-free.

### Recovery transaction

Create `windows/Recover-MyPeopleDockerDeployment.ps1`.

The script accepts an explicit verified candidate image. It refuses to run
when:

- a `mypeople` container already exists;
- any canonical volume is missing;
- an unexpected writable mount is requested;
- the candidate image has not passed the isolated verifier receipt supplied to
  the transaction;
- the pinned Compose or environment file is absent;
- another Docker operation lock is active;
- free space is below the existing safety threshold.

Before Compose mutation, the script:

1. acquires the existing MyPeople Docker operation lock;
2. inspects exactly the eight canonical named volumes;
3. captures stable board and roster hashes through a read-only helper;
4. creates a new protected portable archive using the existing migration
   module and exclusion rules;
5. records the archive SHA-256, byte count, candidate image ID, source commit,
   and previous deployment environment;
6. pins the candidate image ID to a unique recovery deployment tag;
7. atomically updates only `MYPEOPLE_IMAGE` in the deployment environment.

It then runs the pinned Compose deployment and verifies:

- container user and init contract;
- exactly eight writable named volumes plus the read-only seed bind;
- localhost-only published ports;
- unchanged board and stable-roster hashes;
- Priorities, queue/HUD, and terminal readiness;
- memory comparison disabled;
- no memory sidecar or synthetic comparison resources;
- restart count zero.

Provider credentials are not copied by the recovery transaction. The existing
Windows launcher rehydrates the selected protected provider profile only after
the control plane is healthy.

## Failure And Rollback

The recovery transaction is fail-closed.

If failure occurs after Compose mutation, it removes only the transaction-owned
failed container, restores the previous deployment environment, leaves all
named volumes intact, retains the new protected archive, and records
`recovery_failed`. Because no previous image survives, it must not claim that
the old service was restored. The next attempt requires a newly verified image
or an explicit operator decision.

No volume is deleted, renamed, reformatted, or restored automatically. Archive
restoration remains a separate explicit operation.

## Verification Flow

1. Run static base-image contract tests.
2. Build the recovery base from the clean feature worktree.
3. Build the application runtime overlay at the exact repository commit.
4. Run the complete isolated verifier against the candidate image, including
   J1-J52 and focused memory-comparison contracts.
5. Run a disposable container smoke with no live volumes:
   `python3`, `node`, `npm`, `tmux`, `ttyd`, `git`, `rg`, `codex`, and `claude`
   must all resolve; the process must run as `mp`.
6. Run recovery-script refusal tests against fake Docker responses.
7. Execute the host recovery transaction over the surviving volumes.
8. Run `windows/Start-MyPeople.ps1 -NoBrowser -NonInteractive`.
9. Verify provider binding, Boss, Nightwatch, control-plane health, volume
   mounts, restart count, and comparison flag.
10. Run `windows/Start-MyPeopleMemoryComparison.ps1 -Action Preflight`.

The preparation stage ends after a successful preflight. A separate explicit
approval is required before executing paired provider arms.

## Security And Cost Boundaries

- Builds may access Debian repositories and the official Claude, Codex, and
  ttyd distribution endpoints only.
- No OAuth flow is opened during image build.
- Credentials remain in the protected Windows profile store and named volumes.
- The recovery base contains no provider session or project data.
- The preparation stage makes no paid model request beyond the launcher's
  existing non-generative provider validation.
- Docker build size and duration are operational costs; provider-token cost for
  this stage is `not_measured` because no comparison arm is executed.

## Acceptance Criteria

- The base and runtime images can be rebuilt with no pre-existing
  `mypeople-node` image.
- Static, disposable, and isolated verification pass.
- A new protected archive is created before live state is mounted read-write.
- The recreated service uses the original eight volumes without changing
  stable board or roster hashes.
- Priorities, queue/HUD, terminal, Boss, and Nightwatch are healthy.
- The memory comparison preflight passes.
- Memory remains disabled and no comparison card, worker, conversation, or
  sidecar remains after preparation.
- The repository contains no credential, private archive, local account path,
  or non-English public documentation.

## Non-Goals

- Running the three live Gate B pairs.
- Enabling memory globally.
- Restoring Tailscale or the removed floating microphone.
- Upgrading agent CLI versions beyond the pinned compatibility versions.
- Deleting old volumes, backups, build cache, or unrelated Docker projects.
- Replacing MyPeople with the upstream Python-package runtime.
