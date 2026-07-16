# MyPeople User Manual

Last reviewed: July 14, 2026.

## Active configuration

- Boss: Codex `gpt-5.6-sol`.
- Nightwatch: Codex `gpt-5.6-luna`.
- Delegated workers: Codex `gpt-5.6-luna` under the Boss policy.
- Container: `mypeople`.
- Priorities: <http://localhost:9933/>.

The backend and model are stored per agent in the roster. The supervisor revives each agent with its saved configuration. Initial startup without a roster creates Boss with Sol and Nightwatch with Luna; there is no silent internal fallback to Claude.

## Quick tour

Open these addresses from Windows:

- Priorities: <http://localhost:9933/>
- Wall: <http://localhost:9933/wall>
- Terminal Graph: <http://localhost:9933/terminal-graph>
- Dashboard/HUD: <http://localhost:9900/dashboard>
- Writable web terminal: <http://localhost:7681/>
- Read-only web terminal: <http://localhost:7682/>

Normal flow:

1. Create a card with a concrete objective and acceptance criteria.
2. Boss receives the event automatically.
3. Open the card and inspect its comments for the plan, response, or blocker.
4. Boss creates Luna workers when delegation is useful and retains integration authority.
5. Require a comment, evidence, and verification before treating work as complete.

Recommended minimal test card:

```text
Health check. Do not delegate or modify files. Comment with the visible model and confirm: queue, mp, verify.
```

The expected model is `gpt-5.6-sol`.

## Checking Boss and Nightwatch

From PowerShell:

```powershell
docker exec mypeople /home/mp/mypeople/bin/mp status
docker exec mypeople /home/mp/mypeople/bin/mp peek main:Boss
docker exec mypeople /home/mp/mypeople/bin/mp peek nightwatch:Nightwatch
docker exec mypeople pgrep -af gpt-5.6
```

Attach to tmux:

```powershell
docker exec -it mypeople tmux attach -t mc-main
docker exec -it mypeople tmux attach -t mc-nightwatch
```

Detach without stopping the session with `Ctrl+B`, then `D`.

## Durable control queue

Control commands are persisted in `run/control-queue.json` inside the durable
runtime volume. A restart automatically preserves commands that were still
`queued`. Commands already handed to a client but lacking a result become
`uncertain`; they are never replayed automatically because `send`, `answer`,
`spawn`, `kill`, and `revive` can have side effects.

Inspect or explicitly retry one queue command:

```bash
mp queue-status <queue-task-id>
mp queue-retry <queue-task-id>
```

Only `failed` or `uncertain` commands are retryable. The journal is private,
atomic, bounded to active work plus the newest 500 terminal records, and stores
no provider or Git credential.

## Switching models

Boss to Sol:

```powershell
docker exec mypeople /home/mp/mypeople/bin/mp switch main:Boss --backend codex --model gpt-5.6-sol
```

Boss to Luna:

```powershell
docker exec mypeople /home/mp/mypeople/bin/mp switch main:Boss --backend codex --model gpt-5.6-luna
```

Nightwatch:

```powershell
docker exec mypeople /home/mp/mypeople/bin/mp switch nightwatch:Nightwatch --backend codex --model gpt-5.6-luna
```

`mp switch` saves the requested model before closing the tmux window. When
backend and provider profile are unchanged, it performs an exact session resume
with the new model and verifies that the provider session ID did not change.
Direct backend changes are rejected with `fresh_handoff_required`; use the
provider-switch transaction described below.

## Switching provider accounts

Provider profiles keep authentication separate from role and model selection. Credentials remain in the protected local Windows store under `%LOCALAPPDATA%\MyPeople\credentials`; they are copied into isolated runtime homes and are never committed to Git.

Save the current Windows Codex login once:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\Save-MyPeopleProviderProfile.ps1 -Provider codex -Profile codex-primary -FromCurrentWindowsLogin
```

Switch every agent that inherits the global profile:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\Switch-MyPeopleProviderProfile.ps1 -Profile codex-primary
```

Assign a profile only to Boss:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\Switch-MyPeopleProviderProfile.ps1 -Profile codex-primary -Agent node-1/main:Boss
```

Remove that override and make Boss inherit the global profile again:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\Switch-MyPeopleProviderProfile.ps1 -InheritGlobal -Agent node-1/main:Boss
```

Inspect non-secret status without making a paid provider request:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\Get-MyPeopleProviderStatus.ps1
```

A switch is transactional: it records one private, bounded handoff per selected
agent, stops only the selected active roles, installs and validates the target
profile, writes bindings atomically, starts Boss before Nightwatch and workers,
verifies the roster, and commits. The forward path requires an explicit fresh
handoff and honestly records a new provider session. It never describes a
backend or provider-profile change as an exact resume. A failed phase restores
the previous binding and roster, then uses exact session resume against the old
profile storage. The transaction lock, `stopped` phase, private handoff path,
agent identity, cwd, task, and role receipts must all match. Startup rehydrates
the configured global profile before services launch.

Profile switching currently uses PowerShell. HUD controls for global and per-agent account selection are a future interface layer over this same transaction contract.

## Creating a worker manually

Boss normally creates workers. For an advanced owner-task test:

```powershell
docker exec mypeople /home/mp/mypeople/bin/mp spawn main:Worker-1 --backend codex --model gpt-5.6-luna --boss main:Boss --owner-task CARD_ID
```

Omit `--cwd` for the normal path. The owner worker uses the TaskSpec-owned
working directory from its ProjectProfile. An explicit `--cwd` is accepted only
when it resolves to that exact directory; a mismatch fails before tmux
creation. Keep the explicit Codex backend and model while Claude is disabled.

## One-click Windows startup

Install the desktop shortcut once:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\Install-MyPeopleShortcut.ps1
```

The installer copies the required launcher files to `%LOCALAPPDATA%\MyPeople\launcher`. The shortcut starts Docker Desktop when required, runs the pinned Compose deployment when it exists, rehydrates the selected provider profile, checks Priorities, queue/HUD, terminal readiness, and that Boss and Nightwatch are alive, then opens Priorities. It never deletes a volume or changes the pinned image.

### Ready degraded

The desktop shortcut keeps Priorities, HUD, and the terminal available when the
configured provider cannot be validated. New provider launches remain paused,
and the launcher never imports another Windows login automatically. Refresh the
saved profile explicitly, then run the shortcut again; a successful validation
runs `mp providers-resume` and restores Boss and Nightwatch.

In degraded mode, interactive startup opens Priorities and displays a warning.
Non-interactive startup prints the same bounded warning and exits successfully
after the control-plane health gates pass. Provider output, tokens, credential
paths, and raw HTTP response bodies are not copied into the launcher log.

Manual startup remains available:

```powershell
docker start mypeople
docker exec mypeople /home/mp/mypeople/bin/mypeople up --detach
docker exec mypeople /home/mp/mypeople/bin/mp status
```

The volume-backed container uses restart policy `unless-stopped`, Docker `init: true`, and one foreground runtime supervisor. The launcher also retains a legacy fallback for a preserved pre-migration container.

## Durable Docker state

Mutable state is separated into:

| Volume | Container path | Contents |
|---|---|---|
| `mypeople-todos` | `/home/mp/mypeople/todos` | Board, comments, proofs, and backups |
| `mypeople-run` | `/home/mp/mypeople/run` | Roster, bindings, TaskSpecs, logs, and runtime records |
| `mypeople-status` | `/home/mp/mypeople/status` | Agent lifecycle status |
| `mypeople-config` | `/home/mp/.config/mypeople` | Queue and runtime configuration |
| `mypeople-codex` | `/home/mp/.codex` | Codex sessions and local login state |
| `mypeople-claude` | `/home/mp/.claude` | Claude sessions and local login state |
| `mypeople-recordings` | `/home/mp/recordings` | Terminal recordings |
| `mypeople-workspaces` | `/home/mp/workspaces` | Managed Git checkouts, local branches, and commits |

Run the read-only preflight first:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\Migrate-MyPeopleDockerState.ps1
```

Review the reported `transaction.json` under `%LOCALAPPDATA%\MyPeople\backups\docker-migration\<timestamp>`. It must show `stage: planned`, `execute: false`, exactly eight volume names, and `rollbackAttempted: false`.

Execute only after the preflight is green:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\Migrate-MyPeopleDockerState.ps1 -Execute
```

The transaction:

1. stops the original container and commits an immutable snapshot;
2. builds and tests a separate candidate image from the reviewed repository;
3. seeds empty named volumes directly from the snapshot;
4. writes a current-user-protected portable backup with provider auth excluded;
5. renames the original container to `mypeople-pre-volumes-<timestamp>`;
6. launches the candidate through pinned Compose;
7. verifies hashes, process ownership, services, and an isolated provider-disabled restore.

If a post-stop stage fails, rollback removes only the failed new container, renames the untouched original back to `mypeople`, and starts it. New volumes, backup evidence, and images are retained for diagnosis.

The launcher reads `%LOCALAPPDATA%\MyPeople\deployment\.env` and `compose.volume-backed.yml`. It may recreate the container from the pinned image, but never rebuilds implicitly or deletes state.

The standard deployment publishes Priorities, HUD, and terminal ports only on
127.0.0.1. It does not grant NET_ADMIN, mount /dev/net/tun, request a Tailscale
auth key, or start tailscaled.

Tailscale remains an explicit remote-network override:

    docker compose --project-name mypeople --env-file .env -f compose.volume-backed.yml -f compose.tailscale.yml up -d

Only use that second file when remote access is intentionally configured.
Alternatively, cross-host nodes can use explicit UPSTREAM_QUEUE_URL,
UPSTREAM_QUEUE_SECRET, and TTYD_PUBLIC_URL values with a LAN, VPN, or
authenticated reverse proxy. The desktop launcher always uses the local
Compose file alone.

Never run `docker compose down -v` or delete MyPeople volumes as a startup or recovery step. Preserved containers, images, backups, and restore-test volumes are cleaned only in a separate human-approved operation.

Cloudflare memory remains disabled until the Docker migration, restore drill, desktop-launcher recovery, and rollback rehearsal all pass.

### Safe image upgrades after migration

Use the permanent transaction only from a clean, reviewed repository. Build the
candidate from the currently pinned live image:

```powershell
$sha = (git rev-parse --short=7 HEAD).Trim()
$image = "mypeople-node:integration-$sha"
$base = docker inspect mypeople --format '{{.Config.Image}}'
docker build -f docker/Dockerfile.runtime-image --build-arg BASE_IMAGE=$base -t $image .
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\Upgrade-MyPeopleDockerImage.ps1 -CandidateImage $image
```

Before changing the live deployment, `Upgrade-MyPeopleDockerImage.ps1` runs the
complete isolated verifier against the application source packaged inside that
exact image. It pins the verified candidate ID and the current rollback ID to
unique transaction-owned tags. It then stops MyPeople briefly, creates a
current-user-protected portable backup, compares the archive hash before and
after the Docker copy, restarts the old deployment, and only then recreates the
service with the pinned candidate over the same eight named volumes.

The transaction verifies Priorities, HUD, the local terminal, Docker init,
supervisor uniqueness, every exact writable volume name-to-destination mapping,
the read-only seed bind, the
`repo-project-factory` tmux session, and unchanged board and stable-roster
hashes. On failure it restores the previous Compose content with the retained
transaction-owned rollback tag. It never runs `docker compose down -v`, removes
a volume, or uses container renaming as rollback.

Rollback rechecks the exact mounts and pre-upgrade board/stable-roster hashes.
If the failed candidate changed persistent data, `transaction.json` records
`rollbackStatus: recovery-required`; image rollback alone cannot undo that data
mutation, so recover from the protected local archive.

Evidence is stored under:

```text
%LOCALAPPDATA%\MyPeople\backups\docker-upgrade\<timestamp>
```

Retain `transaction.json`, `portable-state.tar.gz`, the candidate tag, the
rollback tag, and the upgrade record until the new deployment has been used
successfully. The archive is **sensitive local restore material**, not ordinary
evidence. Never publish, commit, attach, or upload it, even though obvious auth,
credential, token, key, environment, package-registry, PEM, and P12 filenames
are excluded. Share only redacted configuration and transaction metadata.

Provider sessions are independent of code upgrades. The transaction does not
activate a provider profile, open OAuth, validate quota, run `mypeople up`, or
require Boss and Nightwatch to be alive. Logged-out, exhausted, and deliberately
stopped providers remain unchanged for a later provider-management cycle.

The connected-client registry remains process memory. Provider conversations
are durable provider state, while Priorities, ProjectProfile, TaskSpec, Git
workspace, evidence, and bounded handoffs remain authoritative project state.

## Persistent project workspace and publication

Project Factory lives at `/home/mp/workspaces/project-factory` on the
`mypeople-workspaces` volume. Docker or provider restarts preserve the Git
checkout. The runtime supervisor recreates only the shell session:

```powershell
docker exec mypeople tmux has-session -t repo-project-factory
docker exec -it mypeople tmux attach -t repo-project-factory
docker exec mypeople git -C /home/mp/workspaces/project-factory status --short --branch
```

The workspace supervisor clones only when the path is absent. It never runs
`fetch`, `pull`, `reset`, `merge`, or `checkout` automatically. If an
existing path is not a Git checkout or its `origin` differs from the manifest,
the supervisor records a blocked state under `run/workspaces/` and preserves
the directory for review.

An unauthenticated first clone works only while the configured GitHub
repository is public. For a private repository, bootstrap the volume through an
operator-controlled credential or credential-free Git bundle, then retain the
clean HTTPS `origin`. MyPeople never copies the host credential into Docker.

Worker TaskSpecs permit reading, editing, testing, and committing, while
`push` remains forbidden. Publication is a two-stage Boss gate:

```bash
# Run inside the managed Boss terminal after the card is in review with evidence.
mp approve-publish <task-id> --project project-factory --commit <40-character-sha> --branch main --mode draft_pr --head task/<task-id>-project-factory --title "Short PR title"

# Safe validation: checks the ledger and Git state without network mutation.
mp publish <approval-id> --check

# This direct command is reserved for the credential bridge. Running it in a
# regular Boss or worker shell is rejected and leaves the approval pending.
mp publish-status <approval-id>
```

The approval expires after 15 minutes by default and is bound to the task,
project, full commit, base branch, head branch, PR title/body, repository,
workspace, profile revision, and Boss identity. Publication is serialized by a
file lock and never uses force push or tags. A successful draft branch push is
recorded as `branch_pushed`; if host PR creation is interrupted, the same bridge
can resume idempotently before approval expiry. Final success is `pr_created`.

Creating a valid Boss publication approval is also the review-resume boundary:
the approved priority is transitioned from `review` to `working` before the
approval is returned. If that transition cannot be persisted, the pending
approval is removed and the command fails, so a card cannot silently remain in
review while publication work resumes.

Git credentials are deliberately not installed by MyPeople. Configure a local
external credential helper or future secret reference before a real
publication. Never place a token in `origin`, `.git/config`, the approval
ledger, a priority comment, Docker Compose, or Git. Portable backups remove
credential helper and extra-header configuration from copied Git metadata.

For this private repository on Windows, the supported operator bridge reads the
existing Git Credential Manager entry into memory and sends it over stdin only
to the approved publisher process:

```powershell
# Validate the Boss approval without reading a credential or pushing.
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\Publish-MyPeopleProject.ps1 -ApprovalId <approval-id> -CheckOnly

# Push the exact commit to its approved task branch, create/reconcile the draft
# PR through the host gh login, and record the sanitized PR receipt.
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\Publish-MyPeopleProject.ps1 -ApprovalId <approval-id>
```

The bridge never writes or prints the credential. The transient secret exists
only in the host process, stdin payload, publisher process, and Git askpass
environment for the duration of that one publication. This is a governance
boundary, not isolation from a malicious same-user process inside the container.
GitHub CLI authentication remains on Windows; Docker receives no `gh` token and
does not create the pull request itself. The legacy `direct_main` mode remains
available for explicitly approved compatibility workflows, while `draft_pr` is
the recommended mode.

### Revive semantics

The HUD Revive action calls the queue server, which invokes `mp revive` using
the persisted roster configuration. Revive is eligible only for a dead or
retired roster entry. It refuses an already-alive agent or an existing live
window, and it refuses an owner whose task is done, cancelled, deleted, has a
fresh-owner replacement pending, or has been reassigned. A valid owner revive
requires the saved provider session ID and transcript plus matching backend,
provider profile, real working directory, TaskSpec SHA-256, and role contract
SHA-256. It performs exact session resume with the saved Boss, model, working
directory, and owner task; it does not create a second active owner.

Operator commands:

```powershell
docker exec mypeople /home/mp/mypeople/bin/mp kill main:Boss --reason operator-request
docker exec mypeople /home/mp/mypeople/bin/mp revive main:Boss
docker exec mypeople /home/mp/mypeople/bin/mp reconcile
docker exec mypeople /home/mp/mypeople/bin/mp switch main:Boss --backend codex --model gpt-5.6-luna
```

`mp kill` persists the deliberate stop before process mutation. Deliberately
stopped agents remain stopped until explicit revive. For accidental window
loss, the supervisor calls `mp reconcile` every 15 seconds. Recovery uses a
30-second cooldown and stops after three recovery attempts with a typed
`blocked` state. Only a stale initial process that never captured any session
may receive three labeled bootstrap retries. There is no silent fresh fallback
after an exact-resume failure; inspect the typed error and provider/profile
state instead.

A same-backend, same-profile model switch uses exact session resume. A backend
or profile change is a new conversation and must use the provider transaction's
explicit fresh handoff. `mp reconcile` never calls that fresh path.

The publisher records a short sanitized Git failure detail in the approval
ledger. URLs and secret-shaped values are redacted; credential contents are
never recorded.

## Known limitations

- The transient queue is lost when its process restarts.
- Legacy roster records without a captured provider session ID cannot use exact
  resume; replace them only through an explicit operator-controlled handoff.
- ProjectProfile and TaskSpec are available, but external memory remains disabled until the Phase B security and deployment gate.
- Standard ports are bound to `127.0.0.1`; port 7681 remains the explicitly writable local terminal.
- The complete verifier creates temporary cards only inside its disposable, portless container and never targets the live board.
- The board Git exporter may quarantine small snapshots during heavy test churn; review them before treating the exporter as backup.
- The board Git exporter defaults to `todos/board-backup/` inside the durable
  `mypeople-todos` volume. An explicit `EXPORT_REPO` may override it for an
  operator-controlled external target.
- Preserved migration containers, images, backups, and restore-test volumes require an explicit cleanup review; startup never removes them.

## Technical verification

Focused contracts:

```powershell
docker exec -e PYTHONPATH=/home/mp/mypeople/bin mypeople python3 /home/mp/mypeople/verify/test_codex_boss_switch.py
docker exec -e PYTHONPATH=/home/mp/mypeople/bin mypeople python3 /home/mp/mypeople/verify/test_codex_boss_doctrine.py
docker exec mypeople python3 /home/mp/mypeople/verify/test_boss_supervisor_backend.py
docker exec mypeople python3 /home/mp/mypeople/verify/test_codex_message_submit.py
docker exec mypeople python3 /home/mp/mypeople/verify/test_project_workspace.py
docker exec mypeople python3 /home/mp/mypeople/verify/test_project_publisher.py
```

Complete suite (always disposable and isolated):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\verify\Invoke-IsolatedVerify.ps1 -Image <reviewed-local-image>
```

On Linux or from a Docker-capable shell:

```bash
MYPEOPLE_VERIFY_IMAGE=<reviewed-local-image> bash verify/verify.sh
```

Do not run the full suite with `docker exec mypeople`. Both host launchers
create a unique Compose project with no host ports, external network, live
volumes, Docker socket, or provider credentials. A timeout is enforced and
cleanup always targets only that unique project. Evidence is deleted on
success and retained under the printed temporary path on failure. Exit codes
are `0` success, `1` suite failure, `124` timeout, and `125` host or cleanup
failure.

Provider and Tailnet-dependent runtime fixtures are synthetic. Use separate,
read-only diagnostics when live provider authentication or remote Tailnet
reachability must be checked.

The release process records fresh results before publication; do not rely on an older chat statement as verification.

## Applied runtime repairs

- Priorities owner links use a native local route instead of creating an empty popup or publishing a private network address.
- Terminal routes redirect to the local wrapper with the exact tmux target.
- Terminal Graph uses the same native link path.
- Heartbeats replace each host's agent set, and Wall/Graph discard nonexistent local tmux windows.
- Owner workers start in the TaskSpec-owned working directory. MyPeople mounts
  one digest-addressed runtime contract for Codex or Claude and never modifies
  the project's `AGENTS.md` or `CLAUDE.md`.
- Owner roster records retain the TaskSpec SHA-256, role contract SHA-256,
  contract version, and runtime paths as compact context receipts.
- `mp complete` requires a summary and proof, comments on the card, moves it to review with `verified=false`, and notifies Boss.
- Workers cannot close their own cards; Boss or CEO verifies and integrates.

Worker completion example:

```bash
mp complete "Fixed the terminal popup" --proof "python verify/test_priorities_terminal_popup.py: 3 passed"
```

## Memory architecture

MyPeople is the execution plane, not another memory system. Each task receives one compiled `TaskSpec`. External durable knowledge and targeted recall may contribute to that packet, but they are not queried automatically alongside complete Codex history. See [Minimal Architecture](MINIMAL-ARCHITECTURE.md).

## Synthetic memory activation and security boundary

The Cloudflare MCP pilot is available only as a one-shot synthetic E2E. It
uses the fixed endpoint
`https://mypeople-memory-sandbox.labmkt.workers.dev/mcp`, exposes only
`recall`, returns at most three provenance-complete claims, fixes graph hops
at zero, and never writes project memory.

Persistent memory activation is blocked. Boss, engineers, and services
currently share the same Linux user inside the main container, so a token
placed there would not be isolated from workers. The permanent design requires
a separate credential broker identity before real project data or a live
ProjectProfile can be enabled.

The safe pilot procedure is:

1. Rotate the synthetic Worker bearer and store it under the current Windows
   account with DPAPI by running `Set-MyPeopleMemoryCredential.ps1`.
2. Start a disposable agent-free container from the reviewed candidate image
   with a `tmpfs` mounted at `/run/mypeople-secrets`.
3. Run `Test-MyPeopleMemoryPilot.ps1 -Container <pilot-container>`.
4. The runner injects the credential over stdin, compiles positive and
   cross-project-negative TaskSpecs through the real gateway, and clears the
   tmpfs credential in `finally`.
5. Remove the disposable container after the postcondition confirms that the
   credential file is absent.

Do not target the live `mypeople` container while agents are running. The
pilot credential is pinned to the exact synthetic MCP URL, the gateway path
cannot be replaced by runtime configuration, and symlinked credential files
fail closed.

Keyword recall in this pilot does not intentionally invoke a GPT, Codex,
OpenAI API, or Workers AI model. Usage is still reported as `not_measured`
unless provider telemetry proves otherwise. The model-token impact comes only
from claims embedded in a worker prompt and is bounded to three short claims.

## Windows dictation

MyPeople does not request microphone permission, upload audio, run a
transcription model, or expose a browser microphone control.

1. Focus the intended text field or writable terminal.
2. Press **Win + H**.
3. Speak and let Windows insert the recognized text.
4. Review the text before sending it or pressing Enter.

Windows owns microphone permission, language selection, transcription, and
the dictation UI. This works in Brave and other browsers because MyPeople only
receives the text Windows types into the focused control.

## Recommended next stage

1. Add deliberate Boss stop, reconcile, revive, model, and provider-profile controls to Priorities.
2. Add adaptive, cost-bounded worker model selection without changing task ownership.
3. Bind local services safely and protect the writable terminal.
4. Evaluate a JSON-to-SQLite board migration with a tested JSON rollback path.
5. Activate read-only Cloudflare recall for one real ProjectProfile through a separate security-gated cycle.

## Bounded external memory pilot

Phase A gives every owner task one explicit project contract without turning MyPeople into another memory system.

1. Copy `examples/project-profile.example.json` to `run/project-profiles/<project-slug>.json`.
2. Set the repository, working directory, context files, verification commands, allowed actions, forbidden actions, and limits in that local ProjectProfile.
3. In Priorities, set **Project** to the matching slug. Add a **Context question** only when the task needs targeted durable recall.
4. When Boss starts an owner worker, MyPeople compiles a mode-0600 TaskSpec under `run/taskspecs/` before creating the process. The worker reads `$MYPEOPLE_TASKSPEC_PATH` first, starts in its declared `workingDirectory`, and receives the same external MyPeople lifecycle contract on Codex or Claude without changing project files.

No Context question means no memory process or network call. A profile with `memory.enabled=false` also makes no memory call. When recall is requested, timeout, authorization, project-isolation, response-shape, or budget failures stop worker creation and return only a typed error.

The read-only MCP pilot permits only `recall`, with top K at most 3 and graph hops fixed at 0. The credential remains an environment reference such as `env://MYPEOPLE_MEMORY_TOKEN`; never write the token value into a profile, Git, TaskSpec, event, URL, or comment.

Verification commands must be single, reviewable commands and cannot contain shell metacharacters, substitutions, redirections, pipes, or line breaks. MCP server URLs cannot contain user information, a query string, or a fragment. The gateway child receives only essential runtime variables plus the referenced memory credential; unrelated provider and application secrets do not cross that boundary.

If an owner terminal target already exists, MyPeople rejects the spawn before compiling context or calling MCP. This avoids paid recall, TaskSpec overwrite, and false-success handoffs.

Inspect compiled contracts locally:

```bash
jq . run/taskspecs/<task-id>.json
tail -n 20 run/taskspec-events.jsonl | jq .
```

The event log contains metadata only: task/project identifiers, profile revision, memory status, requested, returned, and embedded claim counts, timing, response characters, and `aiUsage` as measured or `not_measured`. It does not contain questions, claims, tokens, or server URLs.

Phase A does not deploy Cloudflare, write external memory, enable a live profile, import real data, or expose MCP tools directly to Boss/engineers. Those actions require the separate Phase B approval and security gate.
