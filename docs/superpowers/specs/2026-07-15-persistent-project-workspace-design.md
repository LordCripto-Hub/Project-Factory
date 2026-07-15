# Persistent Project Workspace Design

## Decision

MyPeople will own one durable Git workspace volume and one durable publication
protocol. It will not introduce another task database, agent runtime, or memory
layer.

The first managed project is `project-factory`:

- repository: `https://github.com/LordCripto-Hub/Project-Factory.git`;
- workspace: `/home/mp/workspaces/project-factory`;
- branch: `main`;
- tmux session: `repo-project-factory`.

All values remain configurable through a project workspace manifest. No
credential or token is stored in the manifest, repository, approval ledger, or
Docker image.

## Persistence boundary

The named volume `mypeople-workspaces` is mounted at `/home/mp/workspaces`.
Container recreation and provider switching therefore preserve the working
tree, `.git`, local branches, commits, and tmux working directory. The portable
Docker backup and isolated restore drill include this volume.

## Workspace supervisor

A standard-library Python supervisor reads `docker/project-workspaces.json`.
For each entry it:

1. validates the slug, repository, branch, workspace containment, and tmux name;
2. clones only when the workspace is absent and the parent is empty;
3. refuses to replace an existing directory or rewrite a mismatched remote;
4. creates the configured tmux session when absent;
5. leaves fetch, pull, reset, merge, and checkout to an explicit task;
6. writes a compact health record under `run/workspaces/` and retries safely.

The runtime supervisor owns this child process, so Docker restart rehydrates the
tmux session without changing repository content.

## Boss-authorized publisher

`project-publisher` is the only runtime component allowed by the product
contract to invoke `git push`.

Boss creates an approval from a managed Boss session. The approval is an atomic,
mode-0600 JSON record bound to:

- project slug;
- task ID;
- full 40-character commit;
- allowed branch;
- approving Boss identity;
- creation and expiry timestamps;
- a random approval ID.

Approval requires a live roster record where the actor is the master Boss. The
matching priority must belong to the project, be in review, and contain evidence.

Publication takes an exclusive file lock, reloads the approval, and verifies:

- the approval is pending and unexpired;
- the workspace is a clean Git worktree;
- `HEAD` equals the approved commit;
- the current branch and destination branch are allowed by ProjectProfile;
- `origin` matches the configured repository.

It then executes one non-force push of the exact object:

```text
git push --porcelain origin <commit>:refs/heads/<branch>
```

The approval is single-use. Success records a receipt and marks it `published`.
Failure records a sanitized error and keeps an auditable failed state. Secrets
never appear in the receipt. Git authentication must be supplied by an external
credential helper or future secret reference; the workspace and publisher do
not copy host credentials into Docker.

## Threat boundary

This is a governance and least-credential contract, not an adversarial sandbox
between processes sharing the same Linux user. Workers receive `push` as a
forbidden TaskSpec action and no publishing credential. A future hardened
deployment can run the publisher under a separate user or GitHub App without
changing the approval schema.

## Verification

- Unit tests cover manifest validation, clone refusal, idempotent tmux creation,
  Boss-only approval, exact-commit publication, expiry, one-time consumption,
  dirty-worktree rejection, and remote/branch mismatch.
- Docker contract tests require the workspace volume and runtime child.
- A live smoke verifies the clone, tmux session, ProjectProfile, restart
  persistence, and a no-network publication preflight.
- No test performs a real push.

