# Boss SSH Publication Broker Design

Date: 2026-08-01  
Status: approved design, pending implementation plan

## Goal

Allow Boss to publish completed work to any GitHub repository accessible through the operator's host SSH identity, create a pull request, and merge it into `main` after required checks pass. Engineers remain unable to read or use GitHub credentials. Every externally visible mutation requires a short-lived CEO approval bound to one exact task and commit.

## Scope

This design extends the existing SHA-bound publisher and Windows credential bridge. It does not replace ProjectProfile, TaskSpec, workspace isolation, branch protection, evidence requirements, or the existing publication ledger.

The first implementation supports GitHub repositories with an SSH remote and a `main` base branch. Repository-specific protected-base configuration may be added later, but the broker must fail closed when the approved base is not `main`.

## Roles and Trust Boundaries

### Engineers

Engineers may edit an assigned workspace, run verification, and create local commits on task branches. They receive no SSH agent socket, private key, GitHub token, Git credential helper, GitHub CLI authentication, Docker socket, or broker capability.

An engineer completes work by returning:

- task ID;
- project and repository identity;
- task branch;
- immutable head SHA;
- verification evidence;
- requested PR title and bounded summary.

Engineers cannot publish, create a PR, merge, alter the remote, or approve their own work.

### Boss

Boss validates the task, workspace, branch, head SHA, evidence, clean-tree state, and project policy. Boss creates a publication request and presents it to the CEO in Priorities. Boss cannot read the host SSH private key or directly invoke arbitrary host commands.

### CEO

The CEO approves one closed publication transaction. One approval authorizes:

1. pushing the exact approved head SHA to the exact approved task branch;
2. creating or reconciling one pull request from that branch to `main`;
3. waiting for required GitHub checks and branch protection;
4. merging the same pull request when all required gates pass.

Approval does not authorize direct pushes to `main`, force pushes, arbitrary Git operations, another SHA, another repository, or another task.

### Host Publication Broker

The broker runs on Windows outside engineer containers. It is the only component allowed to use the operator's GitHub SSH identity and host GitHub CLI session. It accepts a structured request through the existing controlled bridge, validates it against the publication ledger, performs only allow-listed operations, and returns a sanitized receipt.

The broker never copies the SSH private key, SSH agent socket, `GH_TOKEN`, Git credential helper output, or GitHub CLI configuration into Docker.

## Architecture

The existing MyPeople publication ledger remains the source of truth for approvals and transaction state. The design adds a host-only SSH execution adapter behind the current publisher boundary.

```text
Engineer workspace
  -> local commit and evidence
  -> Boss validation
  -> pending CEO approval in Priorities
  -> CEO approval bound to task/repo/branch/SHA/base/actions
  -> Windows publication broker
  -> SSH branch push
  -> GitHub draft PR create/reconcile
  -> required-check and branch-protection gate
  -> GitHub merge
  -> sanitized receipt and task comment
```

No second approval is required when the approved PR remains unchanged and all required checks pass. A changed head SHA, base branch, repository, or PR identity invalidates the transaction and requires a new approval.

## Approval Contract

The immutable approval contains only allow-listed metadata:

- approval ID and schema version;
- task ID and ProjectProfile slug;
- canonical GitHub owner/repository;
- approved workspace identity;
- source branch;
- exact 40-character head SHA;
- base branch fixed to `main`;
- publication mode `pr_merge_when_green`;
- bounded title and body digest;
- allowed merge method selected by project policy;
- creation and expiry timestamps;
- single-use nonce;
- approving CEO identity label;
- expected verification/evidence digest.

The default expiry is 15 minutes. The approval may be consumed only once to begin the transaction. A transaction that has safely pushed its exact branch may resume idempotently after a process interruption, but it may not expand its authority or accept a new SHA.

## Repository Resolution

Boss may request publication to any GitHub repository only when all of the following are true:

- a ProjectProfile maps the task to a canonical GitHub owner/repository;
- the workspace remote normalizes to that same repository;
- the remote uses an accepted GitHub HTTPS or SSH form without embedded credentials;
- the host SSH identity has access;
- the approved source branch is a valid task branch;
- the base is `main`;
- the repository is not deny-listed by host policy.

The broker converts the validated canonical repository to an SSH push target internally. It does not trust a free-form remote URL supplied by an engineer or prompt.

## Publication Flow

1. The engineer reports completion with a local commit and evidence.
2. Boss verifies the TaskSpec acceptance criteria and verification commands.
3. Boss confirms the worktree is clean and the exact head SHA is reachable from the approved task branch.
4. Boss creates a pending publication approval and moves the task to CEO review.
5. Priorities displays repository, source branch, exact SHA, base, checks policy, merge method, and expiry.
6. The CEO approves or rejects the request.
7. On approval, the host broker independently revalidates every bound field.
8. The broker uses host SSH to push only `SHA:refs/heads/approved-branch` without force.
9. The broker uses the host GitHub CLI/API identity to create or reconcile one draft PR.
10. The broker verifies the PR head repository, branch, SHA, base, state, and task binding.
11. The PR is marked ready only after the local verification receipt remains valid.
12. The broker waits a bounded period for required checks and branch protection.
13. When all required checks pass and GitHub reports the PR mergeable, the broker merges using the approved method.
14. The broker records the PR URL, PR number, merge SHA, timestamps, and sanitized gate results.
15. Boss attaches the receipt to the task and may close it only after the merge SHA is confirmed on `main`.

## Merge Policy

The default merge method is squash unless ProjectProfile explicitly selects another GitHub-supported method. The broker must never bypass branch protection, dismiss reviews, override failed checks, use administrator bypass, or force a merge.

If no required checks exist, the broker still requires GitHub to report the PR as mergeable and confirms the remote head SHA matches the approval. Repositories may require at least one check through ProjectProfile policy.

The bounded wait expires without merging. The PR remains open, the transaction becomes `waiting_or_blocked`, and Priorities shows the blocking checks. Retrying the same transaction is allowed only while the PR head, base, repository, and approval-bound SHA remain unchanged.

## SSH and Secret Handling

- The broker uses the host SSH agent or host key configuration; private key paths and key contents are never accepted as request fields.
- SSH host-key verification is mandatory. The broker cannot disable `StrictHostKeyChecking`.
- The accepted host must be GitHub's configured SSH host for the canonical repository.
- No secret is written to the approval ledger, Board, task comments, receipts, Git configuration, environment snapshots, or logs.
- Publisher subprocess output is sanitized before persistence.
- Engineers and ordinary Boss shells cannot invoke the broker entrypoint directly.
- The broker process receives only the minimum request metadata and inherits credentials only on the host side.

## State Machine

```text
pending_approval
  -> rejected
  -> expired
  -> approved
  -> validating
  -> branch_pushed
  -> pr_created
  -> waiting_checks
  -> merge_blocked
  -> merged
  -> failed_closed
```

Every transition is append-oriented and idempotent. Terminal failure records contain a stable reason code and sanitized detail. Approval replay, mismatched SHA, changed PR head, repository mismatch, expired approval, missing SSH access, failed checks, and unmergeable state all fail closed.

## HUD and Priorities

Priorities shows a compact CEO approval card containing:

- repository;
- task and project;
- source branch and abbreviated immutable SHA;
- target `main`;
- verification status;
- merge method;
- expiry;
- Approve and Reject controls.

The task thread shows sanitized progress: approval granted, branch pushed, PR created, checks pending, blocked reason, and merge result.

HUD exposes only broker health states:

- `available`;
- `ssh_unavailable`;
- `github_cli_unavailable`;
- `authentication_failed`;
- `rate_limited`;
- `unknown`.

HUD never displays account email, token, private key path, SSH fingerprint, credential output, or raw GitHub response bodies.

## Error Handling and Recovery

- Failure before branch push consumes no Git mutation and leaves a retryable or rejected receipt according to the reason.
- Failure after exact branch push may resume idempotently without pushing another SHA.
- An existing matching PR is reconciled; a conflicting PR fails closed.
- Failed or pending checks never trigger a merge.
- A changed remote branch head invalidates the approval.
- A merge timeout leaves the PR open and reports the blocking condition.
- Revoked SSH or GitHub CLI authentication changes broker health and blocks new transactions without affecting local work.
- Broker failure never restarts Docker, Boss, Nightwatch, or engineers.

## Compatibility

The existing Windows publication bridge remains the host boundary. Existing approval ledger records and `draft_pr` flows remain readable. The new `pr_merge_when_green` mode is additive. HTTPS remotes may remain configured in workspaces because the broker derives its SSH push target from the canonical repository rather than rewriting persistent remotes.

## Testing Strategy

Implementation must follow TDD and use an isolated worktree.

Focused tests must cover:

- engineers have no SSH/GitHub credential surfaces;
- only Boss can create an approval request;
- approvals bind task, repository, branch, SHA, base, evidence, mode, and expiry;
- replay, expiry, mismatch, force, direct-main, arbitrary remote, and shell injection fail closed;
- SSH push arguments are exact and do not expose secrets;
- PR create/reconcile is idempotent;
- changed PR head or base blocks merge;
- failed, pending, cancelled, or missing required checks block merge;
- green protected PR merges exactly once;
- receipts and HUD projections are sanitized;
- Windows compatibility remains intact.

Integration tests must use temporary repositories and mocked GitHub/SSH boundaries without real credentials or external mutations. A later gated E2E may use a disposable private repository after separate approval.

## Rollout

1. Implement and verify entirely in an isolated worktree.
2. Run focused publisher, worker-isolation, HUD, public-repository, and Windows bridge tests.
3. Run the complete disposable-Docker verifier.
4. Present implementation evidence and residual risks.
5. Obtain explicit approval before merge, GitHub publication, or live deployment.
6. Activate against one disposable repository before enabling arbitrary ProjectProfile repositories.

## Non-Goals

- Giving engineers GitHub credentials.
- Direct or forced pushes to `main`.
- Automatic administrator bypass of repository protections.
- Storing SSH keys in Docker volumes or MyPeople configuration.
- Supporting non-GitHub forges in the first version.
- Automatically deleting remote branches or closing unrelated pull requests.
