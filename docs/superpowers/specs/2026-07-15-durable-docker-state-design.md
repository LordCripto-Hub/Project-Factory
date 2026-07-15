# Durable Docker State and Recovery Design

Date: July 15, 2026

## Goal

Move MyPeople state out of the current container writable layer into named Docker volumes, replace `sleep infinity` as PID 1 with Docker init plus a foreground supervisor, and prove backup, restore, launcher recovery, and rollback without losing the live board, evidence, provider profiles, sessions, or recordings.

This design is the prerequisite for exact provider-session resume, deliberate Boss stop/reconcile, browser Boss controls, and activation of the Cloudflare memory MCP for a real project.

## Current Baseline

The live container is named `mypeople`, uses image `mypeople-node`, runs as user `mp`, has restart policy `unless-stopped`, and starts with `sleep infinity`. Its only mount is the read-only seed file. Current measured state is approximately:

- `/home/mp/mypeople`: 245 MB;
- `/home/mp/.codex`: 422 MB;
- `/home/mp/recordings`: 55 MB;
- container writable layer: 3.62 GB.

The existing one-click launcher can recover internal supervisors, but deleting or recreating the container would still lose state.

## Scope

### Included

- a guarded, one-time Windows migration command;
- a local immutable image snapshot of the verified pre-migration container;
- named volumes for mutable state only;
- Docker `init: true` and a foreground runtime supervisor;
- automatic rollback to the untouched previous container;
- a portable, current-user-protected backup that excludes provider credentials;
- a restore drill into isolated test volumes and a disposable verification container;
- one-click launcher support for the volume-backed deployment;
- focused contracts, migration dry-run, live smoke, and documentation.

### Excluded

- deleting the pre-migration container or its snapshot image;
- publishing credentials, sessions, recordings, board data, or backups;
- enabling Cloudflare memory during the Docker migration;
- exact Codex/Claude session resume;
- SQLite board migration;
- Boss lifecycle buttons;
- a public multi-architecture image release.

Those excluded product changes remain separate implementation cycles. The memory MCP activation begins only after this migration and restore drill pass.

## Alternatives Considered

### Mount the entire `/home/mp`

This is simple but couples application code, CLI installations, credentials, sessions, and mutable state. A volume would hide image updates and make future upgrades difficult. Rejected.

### Bind Windows directories into the container

This makes files visible from Windows but introduces avoidable Linux permission, file-watching, path, and performance differences. It also increases the chance that personal state is copied or indexed accidentally. Rejected as the default.

### Named volumes per state boundary

This preserves Linux ownership and modes, keeps application code in the image, and lets backup and restore address each state class explicitly. Selected.

## Volume Contract

The deployment creates these named volumes and never removes them automatically:

| Volume | Container path | Purpose |
|---|---|---|
| `mypeople-todos` | `/home/mp/mypeople/todos` | Board, comments, proofs, and board backups |
| `mypeople-run` | `/home/mp/mypeople/run` | Roster, provider bindings/homes, TaskSpecs, logs, and runtime records |
| `mypeople-status` | `/home/mp/mypeople/status` | Agent lifecycle status |
| `mypeople-config` | `/home/mp/.config/mypeople` | Queue and runtime configuration |
| `mypeople-codex` | `/home/mp/.codex` | Native Codex sessions and current container login state |
| `mypeople-claude` | `/home/mp/.claude` | Future or existing Claude session state |
| `mypeople-recordings` | `/home/mp/recordings` | Asciinema terminal recordings |

The existing read-only seed bind remains available only for provenance and reinstall diagnostics.

A future memory credential is not stored in these volumes. The memory activation cycle will inject it into a container `tmpfs` from the Windows DPAPI store during startup.

## Process Model

Compose enables `init: true`. Docker init becomes PID 1 and reaps orphaned children. `runtime-supervisor.sh` runs in the foreground and becomes the single service owner beneath init.

The runtime supervisor monitors queue server, Priorities server, queue client, board exporter, writable/read-only terminals, and `boss-supervisor.sh`. It handles `TERM` and `INT`, forwards shutdown to managed children, waits for them, and exits within a bounded timeout.

`mypeople up --detach` remains idempotent for manual recovery, but normal container startup no longer depends on a shell command executed after `sleep infinity`.

## Migration Transaction

The Windows migration command implements these states and writes each transition to a local transaction log:

1. **Preflight**: verify Docker, the `mypeople` container, expected paths, free disk space, source commit, health endpoints, Boss/Nightwatch status, provider-profile status, and absence of another migration lock.
2. **Quiesce**: stop new task intake, record the board signature and roster/session counts, then stop the container cleanly.
3. **Snapshot**: commit the stopped container to an immutable local tag containing the timestamp and original container/image IDs.
4. **Create volumes**: create only missing named volumes and record whether each volume was created or reused.
5. **Seed volumes**: start a disposable staging container from the snapshot image, mount the new volumes at staging paths, and copy state with ownership, modes, timestamps, and symlinks preserved. Credential-bearing paths never transit through a host plaintext archive.
6. **Portable backup**: create a user-ACL-protected backup under `%LOCALAPPDATA%\MyPeople\backups\docker-migration\<timestamp>`. Include the board, proofs, TaskSpecs, roster metadata, configuration with secret values redacted, Codex/Claude session files excluding auth files, recordings, hashes, source commit, image IDs, volume names, and restore instructions.
7. **Preserve old container**: rename the stopped container to `mypeople-pre-volumes-<timestamp>`. Do not delete it.
8. **Launch**: create the new `mypeople` container from the snapshot image with Compose, named volumes, `init: true`, the same ports, hostname, restart policy, capabilities, and seed bind.
9. **Verify**: check container health, PID 1, supervisor uniqueness, board signature, proof count, roster identity/model/profile fields, session inventories, recordings count, Priorities/HUD/terminal endpoints, Boss/Nightwatch readiness, and one non-mutating Boss inbox ping.
10. **Restore drill**: copy the portable non-secret backup into isolated test volumes, start a disposable container with provider launches disabled, and verify board/proof/roster integrity without contacting Codex, Claude, Cloudflare, or paid APIs.
11. **Commit**: mark the transaction successful and leave the old container stopped, the snapshot image, backup, and test evidence available for human review.

## Rollback

Any failure after the old container is stopped triggers rollback:

1. stop and remove only the new `mypeople` container if it exists;
2. retain every newly created volume for diagnosis;
3. rename `mypeople-pre-volumes-<timestamp>` back to `mypeople`;
4. start the original container;
5. run the original launcher health checks;
6. report the failed stage and evidence path.

Rollback never removes volumes, the snapshot image, backup files, or the previous container state. Cleanup is a separate human-approved operation.

## Launcher Behavior After Migration

The desktop shortcut continues to be the normal entry point. It detects the volume-backed deployment manifest, runs Compose idempotently, rehydrates the selected provider profile, and waits for Priorities, HUD, terminal, Boss, and Nightwatch.

Because mutable state is external, the launcher may recreate a missing container from the pinned local image and Compose definition. It must never run `docker compose down -v`, delete a named volume, rebuild implicitly, or select a different image tag without an explicit upgrade transaction.

## Security

- Backups, transaction logs, and manifests remain outside Git under `%LOCALAPPDATA%\MyPeople` with current-user-only ACLs.
- Portable backups redact queue, provider, Nightwatch, Tailscale, Cloudflare, and other credential values.
- Provider auth files move directly from the snapshot filesystem into Docker volumes and are not written to the portable backup.
- Commands and logs never print secret values.
- Migration scripts use exact container, volume, image, and path allowlists.
- Destructive cleanup is not part of migration or rollback.

## Verification Contract

Focused static/unit tests must prove:

- the volume list and target paths are exact;
- the migration refuses unexpected container names, paths, active locks, insufficient disk, or missing health evidence;
- portable backup redaction catches known secret fields and auth filenames;
- rollback commands never remove volumes or the preserved container;
- the launcher uses the pinned deployment and does not invoke destructive Compose flags;
- the runtime supervisor owns Boss supervision, handles signals, and does not duplicate children.

The live migration must additionally produce:

- before/after board hashes and task/proof counts;
- before/after roster identity, backend, model, profile, and session inventory;
- PID 1 evidence showing Docker init rather than `sleep`;
- one running instance of every managed service;
- HTTP 200 from Priorities and HUD plus terminal connectivity;
- Boss and Nightwatch `alive`;
- a successful isolated restore drill;
- a rollback rehearsal before the old container is eligible for later cleanup.

## Cloudflare Memory Phase Boundary

After the Docker transaction is successful, a separate design and plan will activate the existing read-only Cloudflare MCP for one real `project-factory` profile. That cycle will add DPAPI-to-tmpfs secret injection, an explicit feature flag, read-only `recall`, `topK <= 3`, `hops = 0`, project isolation, provenance verification, a no-question/no-network test, and immediate disable/rollback. It will not write real memory or make recall global.
