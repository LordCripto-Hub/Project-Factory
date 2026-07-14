# Provider Session Orchestration Design

## Status

Approved for implementation on 2026-07-14.

The current runtime passes the complete verification suite, including Boss inbox
delivery. The remaining operational risk is identity persistence: all Codex
agents currently share `/home/mp/.codex/auth.json`, and the container has no
external mount for that directory. Recreating the container can therefore lose
the active login.

## Goals

- Switch the active AI provider profile without losing the MyPeople control
  plane, task history, role assignments, or explicit work context.
- Support one global profile by default and optional per-agent overrides from
  the first backend version.
- Stop and revive managed roles in a deterministic order.
- Validate the new provider login before resuming work.
- Roll back automatically if activation or revival fails.
- Keep credentials and private account metadata outside Git.
- Define a provider adapter contract that supports Codex now and Claude or
  another provider later.
- Keep every tracked document, comment, script message, test description, and
  user-facing string in English.
- Replace the already-published development history with one sanitized public
  baseline after creating a local recovery bundle.

## Non-goals

- No HUD controls for profile management in this iteration.
- No simultaneous mixed-provider user interface.
- No automated creation of third-party accounts or bypass of provider login
  flows.
- No transfer of hidden reasoning or private chain-of-thought between sessions.
- No claim that a force-push erases copies already present in forks, clones,
  provider caches, or third-party archives. Any exposed credential must still
  be revoked independently.
- No plaintext credentials in the repository, board, handoffs, logs, or task
  evidence.

## Chosen approach

MyPeople will use a provider-neutral session orchestrator. A global binding is
the default for every managed role. An optional agent binding can override that
default for a specific agent. The first implementation activates a global Codex
profile imported from the current Windows Codex login, while the data model and
command contract already support per-agent bindings.

This approach is preferred over directly copying one authentication file
because it adds preflight validation, explicit handoffs, audit state, ordered
revival, and rollback. It is preferred over immediately isolating every agent
because global operation remains simple while hybrid operation stays possible.

The public migration uses a separate safety transaction. It first verifies the
sanitized tree, records the current remote object ID, and writes a local Git
bundle outside the repository. It then creates a new root commit from the exact
verified tree and updates the public branch with `--force-with-lease` pinned to
the previously observed remote object ID. The backup reference and bundle are
never pushed.

## Architecture

### 1. Provider profiles

A provider profile is non-secret metadata:

```json
{
  "id": "codex-primary",
  "provider": "codex",
  "credentialRef": "local://codex/codex-primary",
  "defaultModel": "gpt-5.6-luna",
  "roleModels": {
    "boss": "gpt-5.6-sol",
    "nightwatch": "gpt-5.6-luna",
    "engineer": "gpt-5.6-luna"
  },
  "enabled": true
}
```

The metadata is persisted in MyPeople state. The referenced credential is
stored only on the Windows host under:

```text
%LOCALAPPDATA%\MyPeople\credentials\<provider>\<profile-id>\
```

The directory receives user-only permissions. Logs may mention the profile ID
and provider but never filenames containing account identity, token material,
or credential contents.

Profile metadata is persisted at
`%LOCALAPPDATA%\MyPeople\state\provider-profiles.json`. Active bindings are
persisted separately at
`%LOCALAPPDATA%\MyPeople\state\provider-bindings.json`. Both files contain
references only and are safe to inspect, but they remain local runtime state
rather than repository configuration.

### 2. Bindings

Bindings are provider-neutral:

```json
{
  "globalProfile": "codex-primary",
  "agentProfiles": {
    "node-1/main:Boss": "codex-primary"
  }
}
```

`globalProfile` is required. `agentProfiles` is optional and sparse. Removing
an override makes the agent inherit the global profile. The initial CLI exposes
global switching and backend support for agent overrides. HUD controls are a
later consumer of the same contract, not a second implementation.

### 3. Provider adapters

Each adapter implements the same operations:

- `inspect_source`: verify that a source login exists without exposing it.
- `save_profile`: persist a provider credential in the host credential store.
- `activate_profile`: install the selected credential into the target runtime.
- `validate_runtime`: run the provider's non-secret login-status check.
- `runtime_environment`: return the isolated environment required by a process.
- `launch_arguments`: return the backend and model arguments for a role.
- `restore_previous`: restore the last known-good runtime credential.

The Codex adapter uses the current Windows Codex login as an import source and
`codex login status` for validation. A future Claude adapter can use its native
credential location and login-status command without changing orchestration.

### 4. Runtime isolation

Codex officially uses `CODEX_HOME` as the root for configuration,
authentication, logs, sessions, skills, and other state. MyPeople assigns one
runtime home to each Codex provider profile:

```text
/home/mp/mypeople/run/provider-homes/codex/<profile-id>/
```

Every Codex process receives the `CODEX_HOME` resolved from its effective
binding. Agents on the same profile may share that profile home, matching the
current global-account behavior. An agent override points only that agent at a
different profile home, enabling simultaneous accounts without replacing the
global credential.

The Windows profile store is the recovery source. The launcher rehydrates
missing runtime homes before starting agents and synchronizes provider-managed
credential updates back to the protected host profile without copying logs or
session transcripts into the credential store.

### 5. Explicit context handoffs

Provider sessions are not treated as durable project memory. Before stopping an
agent, the orchestrator writes a compact handoff containing:

- switch transaction ID and timestamp;
- agent ID, role, provider profile, backend, and model;
- current task ID and task state, when present;
- latest public status summary;
- repository working directory;
- verification commands associated with the task or project;
- references to task comments and evidence;
- a bounded terminal tail for operational recovery, with secret redaction.

Handoffs contain conclusions and next actions, not hidden reasoning. They are
stored under `%LOCALAPPDATA%\MyPeople\handoffs\<transaction-id>\` and
referenced when the agent is revived. Task history, evidence, roster records,
and provider-neutral project context remain the authoritative sources.

### 6. Switch transaction

The switch is a state machine:

```text
preflight
  -> acquire switch lock
  -> snapshot bindings, roster, and current credential reference
  -> capture agent handoffs
  -> pause automatic agent revival
  -> stop managed agent and recorder processes
  -> activate selected profile or bindings
  -> validate provider login
  -> revive Boss
  -> revive Nightwatch
  -> revive active workers
  -> inject handoffs
  -> verify health, roster, roles, and Boss inbox delivery
  -> commit binding state
  -> release lock
```

The TODO server, queue/HUD, board exporter, and terminal services stay online.
Only provider-backed agent processes are restarted. This keeps Priorities and
operational evidence available throughout the switch.

### 7. Failure and rollback behavior

Every transaction records its phase without recording credentials.

- Preflight failure changes nothing.
- Failure before credential activation resumes the existing agents.
- Authentication validation failure restores the previous credential and
  bindings before revival.
- Partial revival failure stops only agents created by the failed transaction,
  restores the previous binding snapshot, and revives the previous roster.
- A stale lock can be recovered only after confirming that no switch process is
  active.
- If rollback cannot restore a healthy Boss, the control plane remains online,
  the transaction is marked blocked, and the launcher reports the exact
  recovery command.

The previous credential is never deleted automatically. Profile deletion is a
separate, explicit operation.

## Command surface

The first implementation provides Windows entry points because credentials are
stored on the host:

```powershell
.\windows\Save-MyPeopleProviderProfile.ps1 -Provider codex -Profile codex-primary -FromCurrentWindowsLogin
.\windows\Switch-MyPeopleProviderProfile.ps1 -Profile codex-primary
.\windows\Switch-MyPeopleProviderProfile.ps1 -Profile codex-secondary -Agent node-1/main:Engineer-1
.\windows\Get-MyPeopleProviderStatus.ps1
```

The normal one-click launcher rehydrates the active profile into the container
before reviving managed roles. It never prints credential contents.

Future HUD buttons will call a narrow authenticated backend around these same
operations. The HUD must show preflight, switching, validation, revival,
rollback, and blocked states; it must not read or receive credential files.

## Persistence and recovery

The host-side MyPeople directory is the recovery anchor for provider profiles,
active bindings, transaction state, and handoffs. Startup performs the
following checks:

1. The container exists and the control plane is reachable.
2. The active binding references an available host profile.
3. The provider credential inside the container matches the selected profile
   by a non-secret fingerprint.
4. The provider login status is valid.
5. The roster is revived only after these checks pass.

This makes provider identity survive a container restart or recreation. Broader
external persistence for the board, recordings, and all runtime state remains a
separate infrastructure migration and must include a tested backup and restore
before container recreation.

## Public repository policy

The repository is intended for community sharing.

- English is required for tracked documentation, code comments, CLI output,
  test names, UI strings, examples, and commit messages.
- Tracked files must not address or identify a private operator.
- Local machine paths, account identifiers, credentials, tokens, and personal
  operational notes must not be committed.
- Provider examples use generic profile and agent names.
- Secret scanning and an English/public-content audit run before every push.
- Localized interfaces may be added later through explicit locale files. Until
  then, the tracked default interface is English.
- The first community release replaces the published development history with
  one sanitized root commit. The previous history remains only in a protected
  local bundle for recovery.

The implementation includes a one-time audit and translation of the current
tree plus a lightweight verification contract to prevent regressions.

## Verification strategy

### Unit and contract tests

- Profile IDs and provider names reject unsafe input.
- Credential references never serialize secret content.
- Global bindings resolve correctly.
- Per-agent overrides take precedence and fall back to the global profile.
- Role models resolve deterministically.
- Handoffs are bounded and redact known secret patterns.
- Switch locks reject concurrent transactions.
- State transitions reject invalid phase ordering.

### Transaction tests

- A successful global Codex switch stops and revives all managed roles.
- An agent override restarts only the affected agent.
- Failed login validation restores the previous profile.
- Failed Boss revival triggers rollback.
- Automatic supervisors do not race the switch.
- The previous roster and task ownership survive rollback.

### Runtime verification

- `codex login status` succeeds inside the container.
- Queue, TODO, HUD, and terminal health remain available during switching.
- Boss revives first, Nightwatch second, then active workers.
- Role, backend, and model records match resolved bindings.
- A real non-destructive Boss inbox ping succeeds after revival.
- The complete MyPeople verification suite remains green.

### Repository verification

- No tracked credential or known token pattern exists.
- No tracked personal operator references exist.
- The maintained English-only file set passes the repository language audit.
- Every blob reachable from the rewritten public branch passes the
  non-disclosing history audit.
- The force-push lease matches the remote object ID captured immediately before
  the rewrite, so concurrent remote work cannot be overwritten silently.
- PowerShell scripts parse on Windows.
- Documentation examples match the implemented commands.

## Acceptance criteria

1. The current Windows Codex login can be saved as a named host profile without
   exposing credential content.
2. A single command switches every managed role to that profile.
3. Optional per-agent bindings work through the backend and CLI contract.
4. Boss, Nightwatch, and active workers return with their roles and explicit
   handoffs after a successful switch.
5. A forced validation failure restores the previous profile and roster.
6. Restarting MyPeople rehydrates and validates the active profile before agent
   revival.
7. No secret is committed, logged, displayed in the HUD, or stored in a task.
8. All currently tracked public content is appropriate for a community-facing
   English repository.
9. The complete verifier and new provider-session tests pass.
10. Public `main` starts at a sanitized root commit, while the prior history is
    recoverable from a local bundle that is not reachable from the remote.
