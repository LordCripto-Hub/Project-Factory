# Boss SSH Publication Broker Verification

Date: 2026-08-01  
Branch: `feat/boss-ssh-publication-broker`  
Source commit: `df0226a99e8fbade4b978144e99287d3158c1869`  
Candidate image: `mypeople-node:boss-ssh-publisher-df0226a`  
Candidate image digest: `sha256:7480bc895fd7053c683f20835973cba4e7bfb1a226ee212351da463263247392`

## Scope

This verification covers the Boss-only GitHub publication broker. Engineers do
not receive repository credentials. A CEO approval is bound to one task, one
head SHA, one `task/*` branch, `main`, an evidence digest, and an explicit merge
method. The Windows host broker then performs the approved branch push over
SSH, reconciles or creates the exact pull request, waits for required checks,
and merges with `--match-head-commit`.

The live MyPeople container was not restarted, rebuilt, or modified by this
verification. No real SSH key, GitHub token, branch push, pull request, or
merge was attempted.

## Corrections and evidence

### 1. Approval schema

- Bug/risk: an approval could not express a bounded PR-to-`main` transaction.
- Implementation: schema version 2 records `baseBranch`, `headBranch`,
  `mergeMethod`, `evidenceDigest`, `approvedActions`, and a transaction nonce.
- Green evidence: `verify/test_project_publisher.py` (11 tests before the
  state-machine additions; 13 after the transition coverage).

### 2. Lossless publication state machine

- Bug/risk: branch push, PR creation, checks, and merge were not represented as
  independently resumable transitions.
- Implementation: atomic, locked transitions now move through
  `approved -> branch_pushed -> pr_created -> waiting_checks -> merged`; failed
  checks and SHA changes close the path instead of allowing a replay.
- Green evidence: `verify/test_project_publisher.py`; the full Docker verifier.

### 3. CEO approval surface

- Bug/risk: the browser needed a public approval surface without exposing
  private approval records or secrets.
- Implementation: `/todo/publication-approvals` returns an allow-listed
  projection; `/todo/publication-approval` accepts only browser-authenticated
  CEO approve/reject actions. Priorities renders bounded cards with safe DOM
  text and explicit confirmation.
- Green evidence: `verify/test_boss_publication_approval_api.py`; Scorpion visual
  contracts and full Docker verifier.

### 4. Host SSH broker

- Bug/risk: the Docker sandbox cannot directly use the Windows host SSH agent,
  while the old publisher had no resumable host bridge.
- Implementation: `windows/Invoke-MyPeopleSshPublication.ps1` performs a
  preflight inside Docker, exports only the approved commit as a temporary Git
  bundle, pushes the exact `task/*` ref through
  `git@github.com:<owner>/<repo>.git`, reconciles the exact PR, waits for
  required checks, and merges with head-SHA matching. Temporary bundles and
  directories are removed in `finally`.
- Green evidence: `verify/test_ssh_publication_broker.py`,
  `verify/test_windows_publisher_bridge.py`, PowerShell parser validation, and
  the full Docker verifier.

### 5. Publisher health

- Bug/risk: publication capability was not visible in the HUD and failures
  could be mistaken for an unavailable service.
- Implementation: the broker writes a private bounded receipt through
  `mp publish-broker-health`; the HUD exposes only `available`,
  `ssh_unavailable`, `github_cli_unavailable`, `authentication_failed`,
  `rate_limited`, or `unknown`, plus a short reason code and timestamp.
- Green evidence: API/HUD contract tests and the full Docker verifier.

### 6. Windows launcher and public documentation

- Implementation: the desktop installer now copies the SSH broker. README and
  the user manual document the approval lifecycle, the host boundary, SSH/CLI
  prerequisites, and the no-credentials engineer rule.
- Green evidence: `verify/test_public_repository.py` and the full Docker
  verifier.

## Verification summary

Focused host-safe contracts passed:

- project publisher
- CEO publication API
- SSH broker static/security contract
- Windows publisher bridge
- Scorpion visual contract
- public repository contract

The Windows host cannot import the Linux runtime modules that use `fcntl`; the
legacy worker-handoff, project-context, and provider-session tests therefore
remain Docker tests rather than host tests. The disposable candidate image ran
the complete verifier successfully, including those suites and the browser
journeys:

```text
Isolated MyPeople verification passed.
```

## Residual risks and deployment recommendation

- The host still needs a configured `gh` CLI session for PR API operations and
  a normal GitHub SSH setup for Git transport. The broker never stores those
  credentials in MyPeople.
- No real GitHub transaction was attempted in this verification; live
  publication remains intentionally unverified until a human approves a real
  task.
- Required-check polling depends on the repository's branch-protection rules
  and the installed `gh` version.
- The candidate is ready for review, not for automatic deployment. Keep the
  branch isolated until the CEO reviews this evidence and explicitly approves
  merge/deployment.
