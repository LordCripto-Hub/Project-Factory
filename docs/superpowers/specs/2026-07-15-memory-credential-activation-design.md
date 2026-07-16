# Secure Memory Credential Activation Design

## Status

Security-reviewed implementation follow-up to the durable Docker migration.
This cycle verifies the existing synthetic, read-only Cloudflare MCP pilot in
an agent-free disposable container. It does not authorize persistent
activation, real memory data, writes, automatic capture, paid features, or
direct MCP credentials for workers.

## Security boundary

- The Cloudflare bearer secret is encrypted for the current Windows user with
  DPAPI and stored below `%LOCALAPPDATA%\MyPeople\memory`.
- The one-shot runner decrypts the secret only in memory and streams it over
  stdin into `/run/mypeople-secrets/MYPEOPLE_MEMORY_TOKEN` in a disposable
  container with no Boss, Nightwatch, or engineer processes.
- `/run/mypeople-secrets` is a container `tmpfs`, mode `0700`; the token
  file is mode `0600` and is removed in `finally`.
- The secret never appears in Compose environment variables, `docker inspect`,
  Git, project profiles, task cards, TaskSpecs, comments, or launcher logs.
- A ProjectProfile may reference only `env://NAME` or an absolute file below
  `/run/mypeople-secrets/`; arbitrary file references fail closed.
- The Python compiler rejects symlinked secret files and passes the value only
  to the bounded Node gateway child environment.
- The gateway executable path is fixed to the reviewed installation and the
  pilot credential is pinned to the exact synthetic MCP URL.
- The current main container is not a valid persistent secret boundary because
  all workers share the `mp` identity. Persistent activation stays blocked
  until a separate broker identity owns the credential and gateway.

## Activation contract

Windows can store non-secret settings with the project slug, fixed MCP URL, and
DPAPI credential reference. The persistent enable command fails closed. The
synthetic E2E requires:

1. a valid DPAPI credential;
2. the configured Docker `tmpfs`;
3. a disposable agent-free container;
4. the exact pinned synthetic MCP URL;
5. successful secret injection immediately before the bounded E2E.

The atomic profile updater remains available for the future broker cycle and
is idempotent. The current E2E uses an in-memory `pilot-alpha` profile and
does not modify the board or any durable ProjectProfile. Disabled startup
clears stale tmpfs state; an enabled persistent setting is rejected.

## Pilot boundary

The E2E uses synthetic project data and the Cloudflare Worker at
`https://mypeople-memory-sandbox.labmkt.workers.dev/mcp`. The Worker exposes
only `recall`, accepts `topK <= 3`, requires `hops = 0`, and keeps Workers AI
disabled by configuration. The test requires an `a01` claim for
`pilot-alpha`, rejects a beta-only query from that project, validates exact
health/provenance/bounds, and reports AI usage as `not_measured`. It does not
claim measured zero AI usage without provider telemetry. The
`project-factory` profile remains disabled.

## Rollback

The E2E runner always removes the tmpfs file in `finally` and verifies its
absence. Removing the disposable container destroys the tmpfs independently.
The live Docker runtime, board, Git, tasks, and Cloudflare synthetic sandbox
remain untouched.
