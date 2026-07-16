# Volume-Backed Image Upgrade Design

## Goal

Provide one permanent Windows command for upgrading an already volume-backed
MyPeople deployment to a reviewed local image without losing board state,
workspaces, recordings, provider homes, or the pinned rollback image.

## Scope

The command upgrades application code only. It does not log into Codex or
Claude, validate provider quotas, revive agents, change provider bindings, or
enable remote memory. Provider state remains exactly as recorded in the
persistent volumes.

## Transaction

`windows/Upgrade-MyPeopleDockerImage.ps1` accepts an explicit candidate image.
It requires a clean source repository, the pinned deployment files, a healthy
control plane, the eight named volumes, and a candidate that already passes the
isolated verifier.

The transaction:

1. records the current and candidate image IDs, board hash, stable roster hash,
   exact writable mounts, and source commit;
2. pins both image IDs to unique transaction-owned candidate and rollback tags,
   then verifies the source packaged inside the candidate image;
3. stops MyPeople briefly and creates a protected portable backup under
   `%LOCALAPPDATA%\MyPeople\backups\docker-upgrade\<timestamp>`;
4. excludes common authentication and secret-bearing filenames from that
   archive while still classifying it as sensitive local restore material;
5. verifies the copied archive hash and restarts the current deployment;
6. writes the reviewed Compose file and transaction-owned candidate tag to the
   deployment;
7. recreates the service with `docker compose up -d --force-recreate`;
8. verifies Priorities, HUD, the local terminal, PID 1, supervisor uniqueness,
   all eight exact writable volume mappings, the read-only seed bind, the persistent project tmux
   session, and unchanged board/stable-roster hashes;
9. retains both transaction-owned tags and completes.

`portable-state.tar.gz` must never be published, committed, attached, or
uploaded. The redacted configuration and transaction metadata are the shareable
evidence; the archive exists only for local recovery.

## Rollback

Rollback restores the previous Compose content and rewrites the image binding
to the transaction-owned rollback tag over the unchanged named volumes. It never
renames a Compose-managed container because Compose labels follow the renamed
container and can cause it to be recreated. It never removes volumes or invokes
`docker compose down -v`.

Rollback is successful only when the exact mount contract and the pre-upgrade
board/stable-roster hashes still match. A mismatch is recorded as
`recovery-required` because image rollback cannot reverse durable data changes;
the protected local archive is then the recovery source.

## Provider Independence

The command must not import provider-profile modules, activate a profile,
validate OAuth, run `mypeople up`, or require Boss and Nightwatch to be alive.
An exhausted or intentionally stopped provider is a valid pre-upgrade state.
The roster is checked only for stable identity preservation.

## Verification

Static contracts require explicit candidate and clean-repository gates,
packaged-source isolated verification, backup classification and hash comparison,
`--force-recreate`, atomic cross-operation locking, transaction-owned image tags,
rollback without `docker rename`, no provider activation, exact eight-volume and
seed-bind checks, tmux and health gates, stable-state checks, and protected
transaction evidence.

A real upgrade retains the prior image, portable backup, and transaction
records. Cleanup is a separate human-approved operation.
