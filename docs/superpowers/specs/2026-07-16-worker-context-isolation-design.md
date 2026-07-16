# Worker Context Isolation Design

## Goal

Guarantee that an owner worker starts in the `workingDirectory` compiled into
its TaskSpec and mount the MyPeople worker lifecycle contract without creating
or modifying `AGENTS.md` or `CLAUDE.md` inside the assigned project checkout.

## Problem

The current owner-spawn flow compiles a TaskSpec but continues to use the
optional `--cwd` value or a runtime fallback. A missing `--cwd` can therefore
start the worker outside the project selected on the card. A conflicting value
is not rejected.

The Codex path also appends the MyPeople worker contract to `AGENTS.md` in the
selected cwd. In a Git workspace this dirties the checkout, can block the
publisher, and can accidentally commit runtime doctrine into the product.
Claude workers do not receive an equivalent contract.

## Chosen design

### TaskSpec owns the owner-worker cwd

After compiling the TaskSpec and before provider resolution or tmux creation,
`mp spawn --owner-task` reads the compiled document and resolves its
`workingDirectory` with `realpath`.

- If `--cwd` is omitted, the TaskSpec directory is used.
- If `--cwd` is present, its resolved path must equal the TaskSpec directory.
- The directory must already exist and be a directory.
- Missing, invalid, unreadable, or conflicting data fails before tmux creation
  and notifies Boss with a typed, content-free error.

Temporary and unclassified workers retain their current cwd behavior.

### MyPeople doctrine lives in runtime state

The canonical worker contract remains a small constant in `bin/mp` for this
cycle. It is materialized atomically under:

`run/roles/worker/<sha256>/CONTRACT.md`

The digest is calculated from the exact UTF-8 contract. The file and its
directories are private to the runtime user. The project checkout is never
modified.

For Codex, the contract is passed as the documented one-run
`developer_instructions` configuration override. Codex continues to discover
the repository's own `AGENTS.md` normally.

For Claude, the same materialized file is passed with
`--append-system-prompt-file`. Claude continues to discover the repository's
own `CLAUDE.md` normally.

The first-turn message tells both backends to read TaskSpec and explains that
the lifecycle contract is already mounted. It does not tell them to read a
runtime file inside the checkout.

### Context receipts

Each owner roster record stores:

- `taskspec_path`;
- `taskspec_sha256`;
- `role_contract_path`;
- `role_contract_sha256`; and
- `role_contract_version`.

These are compact receipts, not a second memory source. The TaskSpec remains
the task/project context source and the repository instruction files remain
project-owned.

## Security and state boundaries

- No repository file is created, appended, replaced, or chmodded.
- Runtime contract content contains no credentials or project content.
- TaskSpec errors expose stable codes, not its objective, memory claims, or
  context question.
- The contract digest is evidence of mounted doctrine, not proof that every
  instruction was followed.
- Existing provider homes, auth state and session-switch transactions are
  unchanged.
- Boss and Nightwatch doctrine are out of scope for this cycle.

## Failure behavior

Owner spawn fails before tmux when:

- TaskSpec cannot compile;
- TaskSpec JSON cannot be read;
- `workingDirectory` is absent, non-absolute, missing, or not a directory;
- explicit `--cwd` conflicts after path resolution; or
- the runtime contract cannot be materialized.

The existing target-exists guard still runs before TaskSpec compilation to
avoid unnecessary context and memory work.

## Token-cost target

Codex already received the worker contract through the generated project
`AGENTS.md`, so moving it to `developer_instructions` should be token-neutral.
Claude gains the same small contract for backend parity. The contract is capped
at the current compact size and must not duplicate TaskSpec, project
instructions, board history, or provider-session history.

Cwd validation, digests and roster receipts consume no model tokens.

## Verification

- Observe new cwd and no-worktree-mutation contracts fail against the current
  implementation.
- Unit-test derived cwd, matching cwd, conflicting cwd, missing directory and
  malformed TaskSpec before any tmux call.
- Verify Codex receives `developer_instructions` and Claude receives the same
  external contract file.
- Verify a pre-existing project `AGENTS.md` and `CLAUDE.md` remain byte-exact.
- Verify roster receipts match the exact TaskSpec and role-contract bytes.
- Run focused project-context, worker-handoff, provider-switch and publisher
  contracts.
- Run the full isolated verifier before publication.

## Non-goals

- Exact provider session resume.
- Deliberate-stop or fleet reconciliation state.
- Boss/Nightwatch role unification.
- HUD controls or receipt rendering.
- Enforcement of every TaskSpec action.
- SQLite board migration.

