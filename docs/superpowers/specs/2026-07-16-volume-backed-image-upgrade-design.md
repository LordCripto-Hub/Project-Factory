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

1. records the current image, board hash, stable roster hash, counts, mounts,
   and source commit;
2. stops MyPeople briefly and creates a protected portable backup under
   `%LOCALAPPDATA%\MyPeople\backups\docker-upgrade\<timestamp>`;
3. excludes authentication, credential, token, and key files from that archive;
4. verifies the copied archive hash and restarts the current deployment;
5. writes the reviewed Compose file and candidate image to the pinned
   deployment;
6. recreates the service with `docker compose up -d --force-recreate`;
7. verifies Priorities, HUD, the local terminal, PID 1, supervisor uniqueness,
   all eight volumes, the read-only seed bind, the persistent project tmux
   session, and unchanged board/stable-roster hashes;
8. records the old image as the rollback image and completes.

## Rollback

Rollback restores the previous pinned `.env` and Compose content, then runs
Compose with the previous image tag over the unchanged named volumes. It never
renames a Compose-managed container because Compose labels follow the renamed
container and can cause it to be recreated. It never removes volumes or invokes
`docker compose down -v`.

## Provider Independence

The command must not import provider-profile modules, activate a profile,
validate OAuth, run `mypeople up`, or require Boss and Nightwatch to be alive.
An exhausted or intentionally stopped provider is a valid pre-upgrade state.
The roster is checked only for stable identity preservation.

## Verification

Static contracts require explicit candidate and clean-repository gates,
isolated verification, backup redaction and hash comparison, `--force-recreate`,
image-tag rollback without `docker rename`, no provider activation, eight-volume
and seed-bind checks, tmux and health gates, stable-state checks, and protected
transaction evidence.

A real upgrade retains the prior image, portable backup, and transaction
records. Cleanup is a separate human-approved operation.
