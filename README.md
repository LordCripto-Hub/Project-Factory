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

## Memory boundary

MyPeople is an execution plane, not another memory system. Each task receives one compact, explicit context packet. External knowledge systems may help compile that packet, but MyPeople does not query several memory layers automatically.
