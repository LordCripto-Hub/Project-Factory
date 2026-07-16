# Worker Context Isolation Implementation Plan

**Goal:** Derive every owner worker cwd from TaskSpec and mount one
backend-neutral MyPeople worker contract outside project Git worktrees.

**Architecture:** Add typed TaskSpec runtime resolution before provider or tmux
work. Materialize a digest-addressed contract under `run/roles`, inject it into
Codex with the documented `developer_instructions` one-run override and into
Claude with `--append-system-prompt-file`, then record TaskSpec and doctrine
receipts in roster state.

**Tech stack:** Python 3, tmux, Codex CLI configuration, Claude CLI system
prompt file, existing ProjectProfile/TaskSpec and roster contracts.

---

### Task 1: Lock cwd ownership with failing tests

- Extend `verify/test_taskspec_spawn.py`.
- Require omitted cwd to derive from TaskSpec.
- Require matching explicit cwd to pass.
- Require conflicting, missing and malformed cwd to fail before tmux.
- Observe RED.

### Task 2: Lock doctrine isolation and backend parity

- Replace the worktree-mutation expectations in
  `verify/test_worker_handoff.py`.
- Require a digest-addressed external contract.
- Require byte-exact preservation of project `AGENTS.md` and `CLAUDE.md`.
- Require Codex `developer_instructions` and Claude
  `--append-system-prompt-file`.
- Require compact roster receipts.
- Observe RED.

### Task 3: Implement typed cwd and receipt helpers

- Add TaskSpec read, validation and SHA-256 helpers to `bin/mp`.
- Resolve owner cwd before provider selection and `_build_launch_args`.
- Keep target-exists ordering and typed Boss notification.
- Store TaskSpec receipts.

### Task 4: Implement the external worker contract

- Replace `ensure_worker_doctrine(cwd)` with atomic runtime materialization.
- Add the backend-specific launch adapters.
- Unify the first-turn owner handoff wording.
- Store role contract receipts.

### Task 5: Verify and review

- Run focused TaskSpec, worker handoff, project context, provider switch,
  publisher and public repository contracts.
- Run PowerShell-independent Python syntax checks and `git diff --check`.
- Run the complete disposable isolated verifier.
- Request independent review of path, instruction and secret boundaries.

### Task 6: Publish

- Push a focused English branch and open a PR.
- Merge only when clean and mergeable.
- Upgrade the live image in a separate backup-first transaction; code merge
  alone must not mutate the running container.

