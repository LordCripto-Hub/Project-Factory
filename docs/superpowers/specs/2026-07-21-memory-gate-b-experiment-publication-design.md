# Provider-Neutral Memory Gate B Experiment Publication

**Date:** 2026-07-21

**Status:** Approved design pending written-spec review

## Purpose

Publish the completed read-only TaskSpec memory experiment inside Project
Factory without promoting it into the MyPeople production runtime. The public
package must let maintainers reproduce the experiment, inspect its evidence,
and evaluate future memory providers against one bounded contract.

The experiment is provider-neutral. It does not require Cloudflare, a hosted
memory service, an LLM call, or provider credentials.

## Location

All experiment-owned files live below:

```text
experiments/memory-gate-b/
```

The package is isolated from `bin/`, the default Docker deployment, installer,
Windows launcher, runtime supervisor, and production volumes. No production
entrypoint imports or invokes experiment code.

## Published Package

The directory contains only the material needed to understand and reproduce
Gate B:

- a concise English `README.md`;
- the deterministic Project Factory history fixture and its source-SHA lock;
- the hybrid retrieval and bounded TaskSpec-memory adapter;
- the recall-only authenticated HTTPS MCP fixture;
- disposable Docker orchestration and a bounded Windows launcher;
- focused unit and contract tests;
- deterministic result, report, and sanitized container receipt;
- a license/provenance note identifying generated project-history evidence.

The package does not copy internal conversation history, temporary worktree
paths, raw terminal transcripts, credentials, OAuth material, or redundant
implementation-planning documents.

## Source And Dataset Identity

The fixture is generated only from committed public Git evidence. Its manifest
records the exact Project Factory source commit used by the completed gate and
the SHA-256 digest of every generated artifact.

The final dataset remains bound to source commit
`80dce6f866329b79061bb1ed6b0594f9fdf2dd45`. Directory names may use the
unambiguous twelve-character prefix `80dce6f86632`, while manifests and checks
use the full commit identity.

The preliminary dataset is not published or accepted as a fallback.

## Runtime Boundary

Gate B exercises the real TaskSpec compiler through an explicit read-only
boundary in a disposable container. It must prove all of the following:

1. A relevant question adds no more than the configured top-K grounded claims.
2. An irrelevant question adds no claims.
3. A task without a memory question does not call memory.
4. Local task instructions, repository identity, verification commands, and
   permissions are never removed to make space for memory.
5. The memory service can expose recall only; it cannot write project state or
   execute tools.
6. MyPeople production containers, networks, volumes, roster, board, queue,
   and provider sessions remain unchanged.

The fixture MCP server is an experimental protocol implementation, not a
Cloudflare dependency. A hosted, local, or future provider may be evaluated
later only if it implements the same closed recall response and passes the same
security and quality gates.

## Evidence Contract

Committed evidence includes deterministic logical results and a sanitized
execution receipt. Machine-specific timestamps, container IDs, temporary
paths, and hostnames are excluded from logical digests.

The reference result records:

- relevant case: `ok`, three grounded claims;
- irrelevant case: `ok`, zero claims;
- no-question case: `not_requested`, zero claims;
- two memory gateway calls in total;
- bounded memory delta of 942 characters and 236 estimated context tokens;
- actual provider tokens as `not_measured`, because Gate B performs no model
  request and the provider did not expose billable usage.

Repeated runs must produce the same logical result and report digests. Exact
provider cost must never be inferred from the context estimate.

## Public Safety And Sanitation

The experiment must pass the existing public repository audit plus focused
checks that reject:

- personal absolute paths;
- email addresses and account identifiers;
- tokens, keys, cookies, authorization headers, and credential-shaped values;
- private provider session identifiers;
- non-English public documentation;
- writable production mounts or Docker socket access;
- external network access during the deterministic reference run;
- any automatic install or production activation hook.

Ephemeral TLS material is generated inside the disposable container and is
never committed.

## Reproduction Interface

The public README exposes one Windows command and one Docker Compose command.
Both commands:

- select the locked dataset explicitly;
- use a unique Compose project name;
- apply a hard timeout;
- write evidence to a caller-selected directory;
- clean up containers and networks unconditionally;
- never delete or mount MyPeople production volumes;
- return a non-zero exit code for contract, digest, timeout, or cleanup failure.

The full Project Factory verifier adds focused static and unit contracts for
the experiment. The expensive disposable Gate B reproduction remains an
explicit command rather than running implicitly during installation or normal
startup.

## Repository Integration

The first publication changes Project Factory only by adding the isolated
experiment and registering its focused verification contracts. It does not
enable memory in a ProjectProfile, change MyPeople Docker images, or modify the
live system.

The pull request targets `main` and is reviewable independently of the open
lossless-routing work. The dataset may reference the exact routing commit as
historical source evidence without requiring that feature branch at runtime.

## Promotion Rule

No experiment module moves into production `bin/` code until a separate,
human-approved design demonstrates:

- measurable task-quality improvement;
- honest token, latency, and cost attribution;
- safe project isolation and credential handling;
- a rollback path;
- no duplicated memory layer;
- passing controlled live canaries.

Future Gate C learning, prevention, or automatic memory writes are explicitly
out of scope for this publication.

## Verification

Before publication:

1. Run every focused experiment unit and contract test.
2. Run the experiment twice and compare logical result/report SHA-256 digests.
3. Run the public repository sanitation audit.
4. Run the complete isolated Project Factory verifier, including J1-J52.
5. Confirm the live MyPeople container stayed healthy with unchanged restart
   count and no residual experiment containers, networks, or volumes.
6. Review the final Git diff and stage only experiment-owned files.

## Success Criteria

- Gate B is reproducible from the public Project Factory repository.
- The package has no Cloudflare or paid-provider dependency.
- The production runtime and default startup path are unchanged.
- Evidence remains source-bound, deterministic, bounded, and sanitized.
- The repository clearly labels the package as an experiment, not production
  memory.
