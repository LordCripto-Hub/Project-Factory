# MyPeople User Manual

Last reviewed: July 14, 2026.

## Active configuration

- Boss: Codex `gpt-5.6-sol`.
- Nightwatch: Codex `gpt-5.6-luna`.
- Delegated workers: Codex `gpt-5.6-luna` under the Boss policy.
- Container: `mypeople`.
- Priorities: <http://localhost:9933/>.

The backend and model are stored per agent in the roster. The supervisor revives each agent with its saved configuration. Initial startup without a roster creates Boss with Sol and Nightwatch with Luna; there is no silent internal fallback to Claude.

## Quick tour

Open these addresses from Windows:

- Priorities: <http://localhost:9933/>
- Wall: <http://localhost:9933/wall>
- Terminal Graph: <http://localhost:9933/terminal-graph>
- Dashboard/HUD: <http://localhost:9900/dashboard>
- Writable web terminal: <http://localhost:7681/>
- Read-only web terminal: <http://localhost:7682/>

Normal flow:

1. Create a card with a concrete objective and acceptance criteria.
2. Boss receives the event automatically.
3. Open the card and inspect its comments for the plan, response, or blocker.
4. Boss creates Luna workers when delegation is useful and retains integration authority.
5. Require a comment, evidence, and verification before treating work as complete.

Recommended minimal test card:

```text
Health check. Do not delegate or modify files. Comment with the visible model and confirm: queue, mp, verify.
```

The expected model is `gpt-5.6-sol`.

## Checking Boss and Nightwatch

From PowerShell:

```powershell
docker exec mypeople /home/mp/mypeople/bin/mp status
docker exec mypeople /home/mp/mypeople/bin/mp peek main:Boss
docker exec mypeople /home/mp/mypeople/bin/mp peek nightwatch:Nightwatch
docker exec mypeople pgrep -af gpt-5.6
```

Attach to tmux:

```powershell
docker exec -it mypeople tmux attach -t mc-main
docker exec -it mypeople tmux attach -t mc-nightwatch
```

Detach without stopping the session with `Ctrl+B`, then `D`.

## Switching models

Boss to Sol:

```powershell
docker exec mypeople /home/mp/mypeople/bin/mp switch main:Boss --backend codex --model gpt-5.6-sol
```

Boss to Luna:

```powershell
docker exec mypeople /home/mp/mypeople/bin/mp switch main:Boss --backend codex --model gpt-5.6-luna
```

Nightwatch:

```powershell
docker exec mypeople /home/mp/mypeople/bin/mp switch nightwatch:Nightwatch --backend codex --model gpt-5.6-luna
```

`mp switch` saves the requested configuration before closing and reviving the tmux window. Future supervisor revival preserves the selected backend and model.

## Switching provider accounts

Provider profiles keep authentication separate from role and model selection. Credentials remain in the protected local Windows store under `%LOCALAPPDATA%\MyPeople\credentials`; they are copied into isolated runtime homes and are never committed to Git.

Save the current Windows Codex login once:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\Save-MyPeopleProviderProfile.ps1 -Provider codex -Profile codex-primary -FromCurrentWindowsLogin
```

Switch every agent that inherits the global profile:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\Switch-MyPeopleProviderProfile.ps1 -Profile codex-primary
```

Assign a profile only to Boss:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\Switch-MyPeopleProviderProfile.ps1 -Profile codex-primary -Agent node-1/main:Boss
```

Remove that override and make Boss inherit the global profile again:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\Switch-MyPeopleProviderProfile.ps1 -InheritGlobal -Agent node-1/main:Boss
```

Inspect non-secret status without making a paid provider request:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\Get-MyPeopleProviderStatus.ps1
```

A switch is transactional: it records bounded handoffs, stops only the selected active roles, installs and validates the target profile, writes bindings atomically, revives Boss before Nightwatch and workers, verifies the roster, and commits. A failed phase restores the previous binding and revives the prior roster. Startup rehydrates the configured global profile before services launch.

Profile switching currently uses PowerShell. HUD controls for global and per-agent account selection are a future interface layer over this same transaction contract.

## Creating a worker manually

Boss normally creates workers. For an advanced owner-task test:

```powershell
docker exec mypeople /home/mp/mypeople/bin/mp spawn main:Worker-1 --backend codex --model gpt-5.6-luna --boss main:Boss --owner-task CARD_ID --cwd /home/mp/mypeople/run/eng/Worker-1
```

Keep the explicit Codex backend and model while Claude is disabled.

## One-click Windows startup

Install the desktop shortcut once:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\Install-MyPeopleShortcut.ps1
```

The shortcut starts Docker Desktop when required, starts the existing container, launches MyPeople services idempotently, checks Priorities, queue/HUD, and terminal readiness, then opens Priorities. It never deletes or recreates the container.

Manual startup remains available:

```powershell
docker start mypeople
docker exec mypeople /home/mp/mypeople/bin/mypeople up --detach
docker exec mypeople /home/mp/mypeople/bin/mp status
```

The container currently uses `restart policy: no` and `sleep infinity` as its primary command, so MyPeople services may need to be started after Docker or Windows restarts.

## Current persistence

Persisted in the writable container layer:

- Board: `/home/mp/mypeople/todos/board.v2.json`, with atomic backups.
- Agent/backend/model roster: `/home/mp/mypeople/run/roster.json`.
- Agent snapshot: `/home/mp/mypeople/run/agents.json`.
- Boss and Nightwatch doctrine files.
- Terminal recordings: `/home/mp/recordings/*.cast`.
- Native Codex sessions: `/home/mp/.codex/sessions/`.

Process memory only:

- transient queue task registry;
- connected queue clients and temporary queue-server records.

`mp revive` currently opens a new Codex conversation. MyPeople stores explicit handoffs, but it does not yet depend on `codex resume` or invisible session history for project recovery.

## Backup and restore boundary

The current container does not yet use external volumes for `/home/mp/mypeople`, `/home/mp/.codex`, or `/home/mp/recordings`.

- `docker stop` followed by `docker start` preserves the writable layer.
- deleting or recreating the container can lose the board, roster, sessions, recordings, and runtime changes.

Do not delete or recreate the container before external volumes and a tested backup/restore procedure exist.

Provisional local backup:

```powershell
$backupRoot = Join-Path $env:LOCALAPPDATA 'MyPeople\backups\manual'
New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
docker cp mypeople:/home/mp/mypeople (Join-Path $backupRoot 'mypeople-runtime')
docker cp mypeople:/home/mp/.codex (Join-Path $backupRoot 'codex-runtime')
docker cp mypeople:/home/mp/recordings (Join-Path $backupRoot 'recordings')
```

## Known limitations

- External volumes and full restore are not yet proven.
- The transient queue is lost when its process restarts.
- Codex conversations are not resumed automatically.
- ProjectProfile and TaskSpec are available, but external memory remains disabled until the Phase B security and deployment gate.
- PID 1 is `sleep infinity` and does not reap child processes; zombie processes have been observed.
- Ports are currently published on `0.0.0.0`; port 7681 allows terminal writes.
- The complete verifier creates temporary cards; run it without active work or in an isolated environment.
- The board Git exporter may quarantine small snapshots during heavy test churn; review them before treating the exporter as backup.

## Technical verification

Focused contracts:

```powershell
docker exec -e PYTHONPATH=/home/mp/mypeople/bin mypeople python3 /home/mp/mypeople/verify/test_codex_boss_switch.py
docker exec -e PYTHONPATH=/home/mp/mypeople/bin mypeople python3 /home/mp/mypeople/verify/test_codex_boss_doctrine.py
docker exec mypeople python3 /home/mp/mypeople/verify/test_boss_supervisor_backend.py
docker exec mypeople python3 /home/mp/mypeople/verify/test_codex_message_submit.py
```

Complete suite:

```powershell
docker exec mypeople bash /home/mp/mypeople/verify/verify.sh
```

The release process records fresh results before publication; do not rely on an older chat statement as verification.

## Applied runtime repairs

- Priorities owner links use a native local route instead of creating an empty popup or publishing a private network address.
- Terminal routes redirect to the local wrapper with the exact tmux target.
- Terminal Graph uses the same native link path.
- Heartbeats replace each host's agent set, and Wall/Graph discard nonexistent local tmux windows.
- Owner-task Codex workers pass the trust gate and receive their handoff contract.
- `mp complete` requires a summary and proof, comments on the card, moves it to review with `verified=false`, and notifies Boss.
- Workers cannot close their own cards; Boss or CEO verifies and integrates.

Worker completion example:

```bash
mp complete "Fixed the terminal popup" --proof "python verify/test_priorities_terminal_popup.py: 3 passed"
```

## Memory architecture

MyPeople is the execution plane, not another memory system. Each task receives one compiled `TaskSpec`. External durable knowledge and targeted recall may contribute to that packet, but they are not queried automatically alongside complete Codex history. See [Minimal Architecture](MINIMAL-ARCHITECTURE.md).

## Voice dictation

MyPeople exposes a compact microphone on operational surfaces without requiring an API key or paid transcription model.

1. Focus a text field or open the intended terminal.
2. Click the microphone or press `Ctrl + Windows`.
3. Animated bars indicate listening.
4. Speak; final text is inserted directly.
5. Trigger the control again to stop.

Terminal dictation pastes text but never sends Enter. If Windows intercepts the shortcut or the browser denies microphone access, click the control or use `Win + H`. See [Voice Dock](VOICE-DOCK.md) for privacy and offline limitations.

## Recommended next stage

1. External volumes for runtime, Codex, and recordings.
2. Tested backup and restore before container recreation.
3. One `ProjectProfile` per project with repository, context, verification, limits, and secret references.
4. One bounded context packet at task startup.
5. Explicit session handoff or resume without depending on invisible history.
6. Atomic leases, evidence, and approval gates for parallel work.

## Bounded external memory pilot

Phase A gives every owner task one explicit project contract without turning MyPeople into another memory system.

1. Copy `examples/project-profile.example.json` to `run/project-profiles/<project-slug>.json`.
2. Set the repository, working directory, context files, verification commands, allowed actions, forbidden actions, and limits in that local ProjectProfile.
3. In Priorities, set **Project** to the matching slug. Add a **Context question** only when the task needs targeted durable recall.
4. When Boss starts an owner worker, MyPeople compiles a mode-0600 TaskSpec under `run/taskspecs/` before creating the process. The worker reads `$MYPEOPLE_TASKSPEC_PATH` first.

No Context question means no memory process or network call. A profile with `memory.enabled=false` also makes no memory call. When recall is requested, timeout, authorization, project-isolation, response-shape, or budget failures stop worker creation and return only a typed error.

The read-only MCP pilot permits only `recall`, with top K at most 3 and graph hops fixed at 0. The credential remains an environment reference such as `env://MYPEOPLE_MEMORY_TOKEN`; never write the token value into a profile, Git, TaskSpec, event, URL, or comment.

Verification commands must be single, reviewable commands and cannot contain shell metacharacters, substitutions, redirections, pipes, or line breaks. MCP server URLs cannot contain user information, a query string, or a fragment. The gateway child receives only essential runtime variables plus the referenced memory credential; unrelated provider and application secrets do not cross that boundary.

If an owner terminal target already exists, MyPeople rejects the spawn before compiling context or calling MCP. This avoids paid recall, TaskSpec overwrite, and false-success handoffs.

Inspect compiled contracts locally:

```bash
jq . run/taskspecs/<task-id>.json
tail -n 20 run/taskspec-events.jsonl | jq .
```

The event log contains metadata only: task/project identifiers, profile revision, memory status, requested, returned, and embedded claim counts, timing, response characters, and `aiUsage` as measured or `not_measured`. It does not contain questions, claims, tokens, or server URLs.

Phase A does not deploy Cloudflare, write external memory, enable a live profile, import real data, or expose MCP tools directly to Boss/engineers. Those actions require the separate Phase B approval and security gate.
