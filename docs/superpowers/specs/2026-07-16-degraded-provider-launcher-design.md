# Degraded Provider Launcher Design

## Goal

Keep the local MyPeople control plane available from the Windows desktop
shortcut even when the configured model-provider profile cannot be validated.
Provider failure must pause new agent launches without preventing access to
Priorities, HUD, the terminal, Docker state, persistent tasks, or evidence.

## Current Failure

`windows/Start-MyPeople.ps1` currently treats provider activation or validation
failure as a fatal launcher error. A revoked or temporarily unavailable Codex
session therefore prevents the one-click shortcut from opening an otherwise
healthy local control plane. The failure is reproducible when `codex login
status` reports a stored session while a bounded `codex exec` probe returns
`401 token_invalidated`.

## Chosen Approach

The launcher will establish a provider-launch gate before the runtime supervisor
can start, then support two explicit outcomes after Docker and bounded memory
rehydration:

- **Ready:** the configured provider profile activates and passes its bounded
  runtime probe. The launcher clears the provider-launch pause marker, starts
  MyPeople, waits for Boss and Nightwatch, and opens Priorities.
- **Ready degraded:** no global provider is configured, or profile activation or
  validation fails. The launcher writes a sanitized warning, creates or retains
  the provider-launch pause marker, starts the non-provider services, skips the
  Boss/Nightwatch readiness gate, and still opens Priorities.

The launcher will never import another Windows login automatically. Updating a
stored provider profile remains an explicit operator action through
`Save-MyPeopleProviderProfile.ps1`.

## Startup Flow

1. Validate or start Docker Desktop.
2. Establish the provider-launch gate before container startup. The pinned
   deployment runs a profile-scoped, networkless helper with access only to the
   runtime volume. The legacy fallback copies the same marker into the stopped
   container before `docker start`.
3. Start or recreate the pinned volume-backed Compose deployment.
4. Rehydrate the bounded memory credential state. Memory cleanup or secret
   boundary failures remain fatal.
5. Resolve the configured global provider profile.
6. Attempt profile activation and the real bounded runtime probe inside Docker.
7. On success, run `mp providers-resume` before `mypeople up --detach`.
8. On missing profile or provider failure, run `mp providers-pause` with a
   non-secret reason before `mypeople up --detach`.
9. In both outcomes, require Priorities, HUD, and terminal health.
10. Require Boss and Nightwatch only in the Ready outcome.
11. Open Priorities. In degraded mode, also show a concise warning in
    interactive launches and print it in non-interactive launches.

## Error And State Contract

- Docker, Compose, memory-secret cleanup, Priorities, HUD, and terminal failures
  remain fatal because the control plane is not usable.
- Provider activation, authentication, quota, and runtime-probe failures are
  degraded-state conditions, not control-plane failures.
- Provider errors are logged without tokens, credential paths, provider output,
  or raw HTTP response bodies.
- Degraded startup does not kill already-running agents, change bindings, copy
  credentials, or revive new agents.
- The pre-start gate prevents Boss or Nightwatch from being revived during the
  provider validation window; pausing only after Compose startup is forbidden.
- A later successful launcher run removes the pause marker and restores normal
  Boss/Nightwatch startup.
- The desktop shortcut stays hidden and continues to open
  `http://localhost:9933/` with one click.

## Alternatives Rejected

### Keep fail-fast provider validation

This preserves the current behavior but makes the local task/evidence control
plane unavailable for an unrelated external authentication failure.

### Automatically copy the current Windows Codex login

This is convenient but can silently replace the account intentionally assigned
to a provider profile. Credential import remains explicit and auditable.

## Verification

- Add a launcher regression contract that requires explicit ready/degraded
  branches, provider pause/resume commands, unconditional control-plane health
  gates, conditional Boss/Nightwatch gates, sanitized warnings, and no automatic
  credential import.
- Observe the new regression test fail against the current launcher before any
  production edit.
- Run the launcher contract, provider pause/resume tests, provider-profile
  tests, PowerShell parser checks, and public-repository checks.
- Run a normal live launcher smoke with the valid profile and verify Priorities,
  HUD, terminal, Boss, Nightwatch, and `providers-status`.
- Verify the installed launcher copy matches the reviewed repository version
  and reinstall the desktop shortcut after deployment.

## Non-Goals

- No automatic account selection or OAuth UI.
- No provider-profile redesign, per-agent account UI, or hybrid-provider work.
- No change to model routing, model budgets, task handoffs, or Boss controls.
- No activation of the external Cloudflare memory provider.
