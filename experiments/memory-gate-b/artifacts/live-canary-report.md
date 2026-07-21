# Active Live Canary Report

## Result

The bounded Memory Gate B canary passed on the live MyPeople runtime. One
synthetic public task was preserved through normal Boss routing, compiled with
three provenance-backed memory claims, assigned to one Codex worker, verified,
and moved to review with evidence.

The result is assessed as **useful**, but it is one canary rather than
statistical proof of a general quality or cost improvement.

## Measured Outcome

- Retrieval status: `ok`
- Claims requested, returned, and embedded: `3 / 3 / 3`
- Retrieval latency: `837 ms`
- Added context: `822 characters`, approximately `206 tokens`
- Provider token usage: `not_measured`
- Worker: pseudonymized as `worker-canary-01`
- Worker model: `gpt-5.6-luna`
- Worker outcome: `review` with one evidence artifact
- Verification: two required commands passed; ten focused tests passed

The token figure is an estimate of the added TaskSpec text. It is not provider
billing or measured total task usage.

## Activation Findings

The live exercise found three deployment-boundary defects that isolated tests
had not exposed:

1. The launcher verified one secret filename while the project profile stored
   another canonical filename.
2. The MCP SDK applied its loopback host policy because the server factory did
   not receive the Docker host and an explicit internal allowlist.
3. Windows PowerShell prefixed redirected input with a UTF-8 byte-order mark.
   The receiver now admits only the generated 64-character hexadecimal token
   and validates its exact length.

Each failure remained fail-closed: no worker was created until memory retrieval
succeeded, and no bypass was used.

## Rollback Evidence

After assessment, the synthetic task was deleted and its worker retired through
the normal queue-managed lifecycle. The sidecar, internal network, secret
volume, and main-container token were removed. The live MyPeople container
remained running with restart count `0`; Priorities and HUD both returned HTTP
`200`.

No raw question, retrieved claim, local path, account identity, session ID, or
secret is included in this public artifact.

## Exact Software

- Live runtime commit: `f337762d05a59c9255fcb3f1b6b5632585ddb34e`
- Canary commit: `04108d4ae9d09204a1f801fb1c8a210af2451db2`
- Canary base-image commit: `a5c812ca7904ecab9733eb239760703ffde94260`
- Dataset source commit: `80dce6f866329b79061bb1ed6b0594f9fdf2dd45`
- Live runtime image: `sha256:6d1f5f1d8fad8bc17e5d7b3646626a901911385fbcfeb0b376b9f99892d0dc10`
- Canary image: `sha256:9ffe2423f779dc164e994bdf898e23127ec9feaaac2fba17d0eccbbd7d17c67b`

## Remaining Gate

Run a controlled multi-task comparison against the same task set without
memory. Measure task success, rework, total provider tokens, elapsed time, and
human interventions before promoting this mechanism beyond an explicit,
project-scoped canary.
