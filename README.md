# Project Factory - MyPeople with Codex

MyPeople is a local coordination environment for Codex agents running through Docker and tmux. It provides a Boss, Nightwatch, delegated workers, Priorities, and an operational HUD.

This repository contains only the installable product: source code, documentation, plugins, Windows launchers, and verification. Live runtime state is intentionally excluded from version control.

Provenance: this implementation was generated and hardened from the public `delattre1/plow-seedlab-mypeople` seed. The seed does not declare a license, so this repository does not imply or add one.

## Runtime state excluded from Git

- `run/`, `status/`, and `todos/`
- Codex or Claude sessions
- recordings and screenshots
- `.env` files, tokens, keys, and credentials
- `node_modules/` and generated test artifacts

## Quick start inside Linux or Docker

```bash
export INSTALL_DIR=/home/mp/mypeople
bash install.sh
mypeople up --detach
mp status
```

Default interfaces:

- Priorities: <http://localhost:9933/>
- Wall: <http://localhost:9933/wall>
- Terminal Graph: <http://localhost:9933/terminal-graph>
- HUD: <http://localhost:9900/dashboard>
- Writable terminal: <http://localhost:7681/>
- Read-only terminal: <http://localhost:7682/>

The standard Compose deployment binds these ports to **127.0.0.1**, does not
request **NET_ADMIN** or **/dev/net/tun**, and never starts Tailscale. To
dictate text, focus a MyPeople text box or writable terminal and press
**Win + H**; Windows owns microphone permission and transcription.

Remote networking is optional. An operator may explicitly add
docker/compose.tailscale.yml to the Compose command to enable the bundled
Tailscale runtime, or configure UPSTREAM_QUEUE_URL, UPSTREAM_QUEUE_SECRET, and
TTYD_PUBLIC_URL for another LAN, VPN, or authenticated proxy. The one-click
launcher never enables the remote override automatically.

Windows operators can install the desktop shortcut with:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\Install-MyPeopleShortcut.ps1
```

The installer copies the launcher to `%LOCALAPPDATA%\MyPeople\launcher`, so the desktop shortcut does not depend on the repository remaining in its original directory.

### Ready degraded

The desktop shortcut keeps Priorities, HUD, and the terminal available when the
configured provider cannot be validated. New provider launches remain paused,
and the launcher never imports another Windows login automatically. Refresh the
saved profile explicitly, then run the shortcut again; a successful validation
runs `mp providers-resume` and restores Boss and Nightwatch.

## Durable Docker state

MyPeople uses a pinned local image plus eight named volumes:

- `mypeople-todos` for the board, comments, proofs, and board backups;
- `mypeople-run` for the roster, provider bindings, TaskSpecs, and runtime records;
- `mypeople-status` for lifecycle status;
- `mypeople-config` for queue and runtime configuration;
- `mypeople-codex` and `mypeople-claude` for provider session state;
- `mypeople-recordings` for terminal recordings.
- `mypeople-workspaces` for managed Git working trees, local commits, and branches.

The control queue journal also lives in `mypeople-run`. Queued commands survive
a queue-server restart. Commands with an unknown post-delivery outcome are
quarantined as `uncertain` and require explicit `mp queue-retry`; MyPeople does
not automatically duplicate side effects.

The migration is dry-run-first:

```powershell
# Preflight and local transaction plan; does not stop or rename the container
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\Migrate-MyPeopleDockerState.ps1

# Explicit live migration after reviewing the dry-run record
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\Migrate-MyPeopleDockerState.ps1 -Execute
```

The live transaction retains the old container as `mypeople-pre-volumes-<timestamp>`, creates immutable snapshot and candidate image tags, and stores a protected portable backup plus restore evidence under `%LOCALAPPDATA%\MyPeople\backups\docker-migration\<timestamp>`. The pinned Compose definition and local image binding live under `%LOCALAPPDATA%\MyPeople\deployment` and let the desktop launcher recreate a missing container without deleting state.

Never run `docker compose down -v` or delete MyPeople volumes as a startup or recovery step. Cleanup of preserved containers, images, backups, or restore-test volumes is a separate human-approved operation.

Cloudflare memory remains disabled during this migration. Its first real profile is a separate, bounded, read-only activation cycle after backup, restore, launcher recovery, and rollback are verified.

### Upgrade an existing volume-backed deployment

Build a reviewed image from a clean repository, then run the permanent upgrade
transaction:

```powershell
$sha = (git rev-parse --short=7 HEAD).Trim()
$image = "mypeople-node:integration-$sha"
$base = docker inspect mypeople --format '{{.Config.Image}}'
docker build -f docker/Dockerfile.runtime-image --build-arg BASE_IMAGE=$base -t $image .
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\Upgrade-MyPeopleDockerImage.ps1 -CandidateImage $image
```

The command runs the complete isolated verifier before live mutation, creates a
protected portable backup under
`%LOCALAPPDATA%\MyPeople\backups\docker-upgrade\<timestamp>`, recreates the
service over the same eight volumes, and restores a transaction-owned rollback
tag on failure. The verifier executes the application source packaged inside
the candidate image, not the host checkout. Candidate and rollback image IDs
are each pinned to unique transaction tags before mutation. The command does
not delete volumes or preserve Compose containers by renaming them.

Automatic rollback also rechecks the exact mount contract and the pre-upgrade
board and stable-roster hashes. If application code changed durable data before
failing, the transaction records `recovery-required` instead of claiming a
successful rollback; use the protected local archive for manual recovery.

`portable-state.tar.gz` is sensitive local restore material even after obvious
credential filenames are excluded. Never publish, attach, commit, or upload
that archive. Only the redacted configuration and transaction metadata are
shareable diagnostic evidence.

Provider sessions are independent of code upgrades. An exhausted, logged-out,
or intentionally stopped provider remains in that state; the upgrade does not
open OAuth, validate provider quotas, or revive agents.

## Persistent Project Factory workspace

The runtime rehydrates one shell-only tmux session without changing Git content:

```bash
docker exec -it mypeople tmux attach -t repo-project-factory
git -C /home/mp/workspaces/project-factory status --short --branch
```

The first start clones the configured public repository when the workspace is
absent. Later starts only validate `origin`; they never pull, reset, merge, or
checkout automatically.

Workers may commit but receive `push` as a forbidden ProjectProfile action.
After a matching priority reaches review with evidence, Boss binds one
short-lived approval to the full commit:

```bash
mp approve-publish <task-id> --project project-factory --commit <40-character-sha> --branch main --mode draft_pr --head task/<task-id>-project-factory --title "Short PR title"
mp publish <approval-id> --check
```

The Windows `Publish-MyPeopleProject.ps1` bridge consumes the approval. Docker
pushes only the approved SHA to the approved `task/...` head, then the host
GitHub CLI login creates or reconciles the matching draft pull request and
records its number and URL. `project-publisher` is the only product component
that invokes `git push`.
It rejects dirty worktrees, changed commits, remote or branch mismatches,
expired approvals, and reuse. Git authentication remains an external credential
helper or secret reference; credentials are never copied into the workspace,
approval ledger, image, or repository.

The legacy `direct_main` mode remains available only for explicitly approved
compatibility workflows. `draft_pr` is the recommended public collaboration
contract.

## Documentation

- [User manual](docs/USER-MANUAL.md)
- [Minimal architecture](docs/MINIMAL-ARCHITECTURE.md)

## Safe full verification

The full suite runs only in a disposable, credential-free container. It never
targets the live `mypeople` container or its board volumes:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\verify\Invoke-IsolatedVerify.ps1 -Image <reviewed-local-image>
```

```bash
MYPEOPLE_VERIFY_IMAGE=<reviewed-local-image> bash verify/verify.sh
```

The launchers publish no host ports, apply a bounded timeout, always remove
their unique Compose project, delete evidence after success, and print the
retained evidence path after failure. Exit codes are `0` for success, `1` for
a suite failure, `124` for timeout, and `125` for orchestration failure.
Provider and Tailnet-dependent runtime fixtures are synthetic; this suite does
not validate live provider authentication or remote Tailnet reachability.

## Memory boundary

MyPeople is an execution plane, not another memory system. Each task receives one compact, explicit context packet. External knowledge systems may help compile that packet, but MyPeople does not query several memory layers automatically.
