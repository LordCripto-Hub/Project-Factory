# Boss SSH Publication Broker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Boss request one CEO-approved, host-SSH-backed transaction that publishes an exact task commit, creates a GitHub pull request, waits for required checks, and merges into `main`, while engineers receive no GitHub credentials.

**Architecture:** Extend the existing append-oriented publication approval and Windows bridge rather than adding a second publisher. Container code validates immutable task/repository/branch/SHA authority and records state; a Windows-only broker converts the canonical repository to an SSH push target, uses the host SSH/GitHub CLI identities, and reports sanitized transitions. Priorities owns approval UX, while HUD exposes bounded broker health.

**Tech Stack:** Python 3 standard library, PowerShell 7/Windows PowerShell, Git/SSH, GitHub CLI, vanilla HTML/CSS/JavaScript, unittest, disposable Docker verification.

---

## File Map

- Modify `bin/project_publisher.py`: approval schema, immutable authority checks, state transitions, and sanitized receipts.
- Modify `bin/mp`: Boss request, CEO approve/reject, status, and broker-transition CLI commands.
- Modify `bin/queue-server.py`: bounded approval and broker-health HTTP projections/actions.
- Modify `bin/todos.html`: CEO publication approval card and task-thread status.
- Modify `bin/dashboard.html`: broker health on the existing HUD.
- Modify `bin/mypeople-ui.css`: Scorpion-styled approval and health states.
- Create `windows/Invoke-MyPeopleSshPublication.ps1`: host-only SSH/GitHub broker.
- Modify `windows/Install-MyPeopleShortcut.ps1`: install the broker beside the existing launcher files.
- Modify `docs/USER-MANUAL.md`: operation, security boundary, failure recovery, and SSH prerequisites.
- Modify `verify/test_project_publisher.py`: approval/state-machine unit contracts.
- Create `verify/test_boss_publication_approval_api.py`: HTTP projection and authorization contracts.
- Create `verify/test_ssh_publication_broker.py`: static and mocked broker security contracts.
- Modify `verify/test_windows_publisher_bridge.py`: compatibility and no-secret regression.
- Modify `verify/test_scorpion_premium_visuals.py`: approval/HUD visual contract.
- Modify `verify/test_public_repository.py`: English-only public documentation and no-secret claims.

### Task 1: Add the closed `pr_merge_when_green` approval schema

**Files:**
- Modify: `verify/test_project_publisher.py`
- Modify: `bin/project_publisher.py`

- [ ] **Step 1: Write failing schema tests**

Add tests that call `create_approval()` with `mode="pr_merge_when_green"`, `branch="main"`, `head_branch="task/task-1-project-factory"`, `merge_method="squash"`, and a fixed evidence digest. Assert the record contains schema version 2, `baseBranch == "main"`, the exact commit, `mergeMethod == "squash"`, a 64-character `evidenceDigest`, `approvedActions == ["push_branch", "create_pr", "merge_when_green"]`, and a single-use nonce. Add negative cases for non-`main` base, `direct_main`, invalid merge methods, missing evidence digest, and TTL outside 60–3600 seconds.

```python
approval = self.create(
    root,
    mode="pr_merge_when_green",
    base_branch="main",
    head_branch="task/task-1-project-factory",
    merge_method="squash",
    evidence_digest="e" * 64,
)
self.assertEqual(approval["approvedActions"], [
    "push_branch", "create_pr", "merge_when_green",
])
self.assertEqual(approval["baseBranch"], "main")
```

- [ ] **Step 2: Run the tests and observe RED**

Run: `python verify/test_project_publisher.py`

Expected: FAIL because the mode and new bound fields do not exist.

- [ ] **Step 3: Implement the minimal schema**

In `bin/project_publisher.py`, replace the public creation path's mode choices with `{"draft_pr", "pr_merge_when_green"}` while retaining legacy read compatibility for `direct_main`. Add strict validators:

```python
MERGE_METHODS = {"squash", "merge", "rebase"}
APPROVED_ACTIONS = ["push_branch", "create_pr", "merge_when_green"]
DIGEST = re.compile(r"^[0-9a-f]{64}$")
```

For the new mode, require `baseBranch == branch == "main"`, a `task/` head distinct from main, an allowed merge method, and a lowercase evidence digest. Generate a 32-byte nonce with `secrets.token_hex(32)`. Persist only allow-listed metadata and mode `0o600`.

- [ ] **Step 4: Run focused tests**

Run: `python verify/test_project_publisher.py`

Expected: PASS, including all existing draft-PR compatibility cases.

- [ ] **Step 5: Commit**

```bash
git add bin/project_publisher.py verify/test_project_publisher.py
git commit -m "feat: bind merge-when-green publication approvals"
```

### Task 2: Implement fail-closed publication transitions

**Files:**
- Modify: `verify/test_project_publisher.py`
- Modify: `bin/project_publisher.py`
- Modify: `bin/mp`

- [ ] **Step 1: Write failing transition tests**

Add tests for `approve_request`, `reject_request`, `record_branch_push`, `record_pull_request`, `record_checks`, and `record_merge`. Assert the exact state path:

```text
pending_approval -> approved -> validating -> branch_pushed
-> pr_created -> waiting_checks -> merged
```

Assert rejection, expiry, nonce replay, repository mismatch, changed SHA/head/base, failed checks, an unmergeable PR, and a second merge all raise `PublisherError`. Assert pending or failed checks result in `merge_blocked` without a merge transition.

- [ ] **Step 2: Observe RED**

Run: `python verify/test_project_publisher.py`

Expected: FAIL because the transition functions and states are absent.

- [ ] **Step 3: Implement locked transitions**

Add a single helper that loads and updates records under `json_lock`:

```python
def transition(approval_id, expected, target, *, approvals_dir=None,
               validate=lambda record: None, updates=None, now=None):
    root = approvals_root(approvals_dir)
    path = approval_path(approval_id, root)
    with json_lock(path + ".lock"):
        record = load_json(path, None)
        if not isinstance(record, dict) or record.get("status") not in expected:
            raise PublisherError("publication transition mismatch")
        validate(record)
        record.update(updates or {})
        record["status"] = target
        record["updatedAt"] = time.time() if now is None else float(now)
        atomic_json(path, record, mode=0o600)
        return record
```

Each public transition must provide its own exact validator and append a sanitized receipt containing IDs, timestamps, state, repository slug, abbreviated SHA, PR number/URL, check summary, or merge SHA—never command output or credentials.

Add CLI commands:

```text
mp publish-request <approval-id> --approve|--reject --by CEO
mp publish-branch-complete <approval-id> --sha <sha>
mp publish-pr-complete <approval-id> --number <n> --url <url> --head-sha <sha>
mp publish-checks <approval-id> --state pending|failed|passed --digest <sha256>
mp publish-merge-complete <approval-id> --merge-sha <sha>
```

Require `--by CEO` for approve/reject. Remove `direct_main` from new CLI creation choices but keep status reading for old ledger entries.

- [ ] **Step 4: Run focused tests**

Run: `python verify/test_project_publisher.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bin/project_publisher.py bin/mp verify/test_project_publisher.py
git commit -m "feat: enforce publication approval state machine"
```

### Task 3: Expose CEO approval safely in Priorities

**Files:**
- Create: `verify/test_boss_publication_approval_api.py`
- Modify: `bin/queue-server.py`
- Modify: `bin/todos.html`
- Modify: `bin/mypeople-ui.css`

- [ ] **Step 1: Write failing API/UI tests**

Require `GET /todo/publication-approvals` to return only pending records with approval ID, task ID, repository slug, head branch, abbreviated SHA, base, merge method, expiry, and verification status. Require `POST` with `op=approve|reject`, `approvalId`, and `by=CEO`; reject unknown fields and non-CEO actors. Assert HTML contains Approve/Reject controls and never renders nonce, workspace path, remote URL, credential, or raw command.

- [ ] **Step 2: Observe RED**

Run: `python verify/test_boss_publication_approval_api.py`

Expected: FAIL because the endpoint and controls do not exist.

- [ ] **Step 3: Implement bounded projection and actions**

Add a queue-server projection with an explicit allow-list:

```python
PUBLIC_APPROVAL_FIELDS = {
    "approvalId", "taskId", "projectSlug", "repositorySlug",
    "headBranch", "shortSha", "baseBranch", "mergeMethod",
    "expiresAt", "status", "verificationStatus",
}
```

Route actions through the `mp publish-request` authority rather than editing JSON directly. In `todos.html`, poll pending approvals through the existing single-flight coordinator cadence, render one compact Scorpion card per request, confirm approval text, and refresh the task thread after action. Use text nodes only; do not assign untrusted values to `innerHTML`.

- [ ] **Step 4: Run API and visual contracts**

Run:

```powershell
python verify/test_boss_publication_approval_api.py
python verify/test_scorpion_premium_visuals.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bin/queue-server.py bin/todos.html bin/mypeople-ui.css verify/test_boss_publication_approval_api.py verify/test_scorpion_premium_visuals.py
git commit -m "feat: add CEO publication approval surface"
```

### Task 4: Build the host-only SSH publication broker

**Files:**
- Create: `verify/test_ssh_publication_broker.py`
- Create: `windows/Invoke-MyPeopleSshPublication.ps1`
- Modify: `windows/Install-MyPeopleShortcut.ps1`
- Modify: `verify/test_windows_publisher_bridge.py`

- [ ] **Step 1: Write failing static and mocked tests**

Assert the script:

- accepts only a 24-hex approval ID;
- obtains preflight JSON from `docker exec mypeople ... publish --check`;
- accepts only `github.com/<owner>/<repo>` canonical slugs;
- constructs `git@github.com:<owner>/<repo>.git` internally;
- invokes `git push --porcelain <ssh-target> <40-sha>:refs/heads/<task-branch>` without force;
- sets `GIT_TERMINAL_PROMPT=0` and never disables host-key checking;
- invokes only fixed `gh pr list/create/view/ready/checks/merge` verbs;
- never accepts a key path, raw remote, arbitrary command, token, or engineer input;
- clears transient environment values in `finally`;
- returns sanitized reason codes.

Use mocked `git`, `gh`, and `docker` executables in a temporary PATH; no network or real credential may be used.

- [ ] **Step 2: Observe RED**

Run: `python verify/test_ssh_publication_broker.py`

Expected: FAIL because the broker does not exist.

- [ ] **Step 3: Implement the exact broker**

The script flow must be:

```powershell
param([Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{24}$')][string]$ApprovalId)
$env:GIT_TERMINAL_PROMPT = '0'
try {
    $preflight = (& docker exec mypeople /home/mp/mypeople/bin/mp publish $ApprovalId --check | Out-String) | ConvertFrom-Json
    if ($preflight.mode -ne 'pr_merge_when_green' -or $preflight.status -notin @('approved','branch_pushed','pr_created','waiting_checks','merge_blocked')) { throw 'approval_state_invalid' }
    # Validate every allow-listed field, derive SSH target, push exact SHA,
    # reconcile PR, wait for checks, merge only when GitHub reports green.
} finally {
    Remove-Item Env:GIT_TERMINAL_PROMPT -ErrorAction SilentlyContinue
}
```

Use PowerShell argument arrays, never `Invoke-Expression`, `cmd /c`, interpolated shell strings, `--admin`, or `--force`. Bound check waiting to 15 minutes with 10-second polling. Treat `gh pr checks` pending as retryable, failed as `merge_blocked`, and only a fully successful exit plus matching `headRefOid` as green. Before merge, re-read PR JSON and compare repository, base, head, and head SHA. Use the approved merge method with `gh pr merge --squash|--merge|--rebase --match-head-commit <sha>` and no admin bypass.

- [ ] **Step 4: Run broker and compatibility tests**

Run:

```powershell
python verify/test_ssh_publication_broker.py
python verify/test_windows_publisher_bridge.py
```

Expected: PASS without network access.

- [ ] **Step 5: Commit**

```bash
git add windows/Invoke-MyPeopleSshPublication.ps1 windows/Install-MyPeopleShortcut.ps1 verify/test_ssh_publication_broker.py verify/test_windows_publisher_bridge.py
git commit -m "feat: add host SSH publication broker"
```

### Task 5: Add broker health to the existing HUD

**Files:**
- Modify: `verify/test_boss_publication_approval_api.py`
- Modify: `bin/queue-server.py`
- Modify: `bin/dashboard.html`
- Modify: `bin/mypeople-ui.css`

- [ ] **Step 1: Write failing health tests**

Require a sanitized projection with exactly `available`, `ssh_unavailable`, `github_cli_unavailable`, `authentication_failed`, `rate_limited`, or `unknown`; `checkedAt`; and optional stable reason code. Assert no account, email, key path, fingerprint, token, remote URL, or raw stderr crosses the endpoint.

- [ ] **Step 2: Observe RED**

Run: `python verify/test_boss_publication_approval_api.py`

Expected: FAIL because broker health is absent.

- [ ] **Step 3: Implement health projection**

The host broker writes a private, atomic, allow-listed health receipt through a dedicated `mp publish-broker-health` transition. Queue server projects it read-only. Add a compact `GitHub publisher` datum to the existing HUD status area; do not create another dashboard or polling loop.

- [ ] **Step 4: Run tests**

Run:

```powershell
python verify/test_boss_publication_approval_api.py
python verify/test_scorpion_premium_visuals.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bin/queue-server.py bin/dashboard.html bin/mypeople-ui.css verify/test_boss_publication_approval_api.py verify/test_scorpion_premium_visuals.py
git commit -m "feat: expose bounded GitHub publisher health"
```

### Task 6: Document operation and prove public safety

**Files:**
- Modify: `docs/USER-MANUAL.md`
- Modify: `README.md`
- Modify: `verify/test_public_repository.py`

- [ ] **Step 1: Write failing documentation tests**

Require English documentation for engineer isolation, CEO approval, exact SHA binding, SSH host broker, checks-before-merge, failure recovery, and prohibition of direct/forced main pushes. Reject private paths, account identifiers, key paths, tokens, and copied secrets.

- [ ] **Step 2: Observe RED**

Run: `python verify/test_public_repository.py`

Expected: FAIL because the operator workflow is undocumented.

- [ ] **Step 3: Write the operator workflow**

Document these exact commands:

```powershell
docker exec mypeople mp approve-publish <task-id> --project <slug> --commit <40-sha> --branch main --mode pr_merge_when_green --head task/<task-id>-<slug> --merge-method squash --evidence-digest <sha256>
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\Invoke-MyPeopleSshPublication.ps1 -ApprovalId <24-hex-id>
```

Explain that the second command normally runs from the approved UI bridge, manual use is recovery-only, host SSH and `gh` must both authenticate to the same repository, and no key is copied into Docker.

- [ ] **Step 4: Run public checks**

Run: `python verify/test_public_repository.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/USER-MANUAL.md verify/test_public_repository.py
git commit -m "docs: explain Boss SSH publication workflow"
```

### Task 7: Integrated disposable verification and gated handoff

**Files:**
- Create: `docs/verification/boss-ssh-publication-broker-2026-08-01.md`

- [ ] **Step 1: Run all focused tests from a clean tree**

```powershell
python verify/test_project_publisher.py
python verify/test_boss_publication_approval_api.py
python verify/test_ssh_publication_broker.py
python verify/test_windows_publisher_bridge.py
python verify/test_scorpion_premium_visuals.py
python verify/test_public_repository.py
```

Expected: all tests pass and no test contacts GitHub.

- [ ] **Step 2: Run existing isolation regressions**

```powershell
python verify/test_worker_handoff.py
python verify/test_project_context.py
python verify/test_provider_session.py
```

Expected: engineers still receive no publisher or host credential capability.

- [ ] **Step 3: Build and verify a candidate image**

```powershell
$base = docker inspect mypeople --format '{{.Config.Image}}'
$sha = (git rev-parse HEAD).Trim()
$image = "mypeople-node:boss-ssh-publisher-$($sha.Substring(0,7))"
docker build -f docker/Dockerfile.runtime-image --build-arg "BASE_IMAGE=$base" --build-arg "MYPEOPLE_SOURCE_SHA=$sha" --build-arg "MYPEOPLE_IMAGE_REF=$image" -t $image .
powershell -NoProfile -ExecutionPolicy Bypass -File verify/Invoke-IsolatedVerify.ps1 -Image $image -TimeoutSeconds 1800 -UsePackagedSource
```

Expected: full isolated verification passes without host credentials, network access to GitHub, or live volumes.

- [ ] **Step 4: Capture UI evidence**

Capture Priorities with a pending approval and HUD with each sanitized broker-health class at 1440×900 and 390×844. Assert zero external requests, horizontal overflow, unnamed controls, and undersized interactive targets.

- [ ] **Step 5: Write verification evidence**

Record red/green history, commands, exact source/image SHA, mocked broker scenarios, visual manifest, full verifier result, live non-interference proof, and residual risks in `docs/verification/boss-ssh-publication-broker-2026-08-01.md`.

- [ ] **Step 6: Commit and stop**

```bash
git add docs/verification/boss-ssh-publication-broker-2026-08-01.md
git commit -m "docs: verify Boss SSH publication broker"
```

Do not merge, push, deploy, use real SSH credentials, create a real PR, or mutate a live repository. Present the candidate and request a separate approval for a disposable-repository E2E and later live deployment.
