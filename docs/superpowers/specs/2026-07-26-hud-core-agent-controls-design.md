# HUD Core Agent Controls Design

## Goal

Add bounded lifecycle and model controls to the existing Scorpion HUD cards for
Boss and Nightwatch only. Engineer lifecycle remains controlled by Boss through
the existing terminal and CLI workflows.

## Scope

The command surface supports exactly these core agents:

- `node-1/main:Boss`
- `node-1/nightwatch:Nightwatch`

The first model allowlist contains:

- `gpt-5.6-sol`
- `gpt-5.6-luna`

The allowlist is a server-owned configuration surface so future models can be
added without redesigning the card. This stage does not add provider switching,
provider-account switching, arbitrary agent controls, or free-form model input.

## User Experience

Each supported card contains a compact `COMMAND` strip within the existing
card hierarchy.

For an alive core agent:

- `Kill`
- a closed model selector
- `Apply model`

For a dead or deliberately stopped core agent:

- `Revive`
- the same closed model selector
- `Relaunch`

`Kill` uses an inline two-click confirmation. The first click changes the
button to `Confirm kill` and arms it for five seconds. The second click during
that interval executes the action. Expiration, focus loss, or another completed
operation disarms it.

Selecting a model and pressing `Apply model` or `Relaunch` is the explicit
confirmation for a model change. No browser modal is added.

Controls stop event propagation so they never trigger the card's terminal
Attach behavior. While an operation is running, the command strip is disabled
and exposes an honest local state such as `stopping`, `switching`, or
`recovering`. Success is shown only after a fresh roster read confirms the
requested state and model. Sanitized failures remain visible on the card and do
not optimistically change the displayed model.

The visual language extends the existing Scorpion system: gold denotes command,
red denotes an armed destructive action, and green denotes a verified recovery.
There is no global redesign in this stage.

## Server Contract

The HUD server exposes authenticated, purpose-specific JSON operations for:

- kill a supported core agent;
- revive a supported core agent with its persisted configuration;
- switch or relaunch a supported core agent on an allowlisted Codex model.

Requests contain structured fields only: `agent_id` and, for model operations,
`model`. They never contain a command line.

The server validates before process mutation:

1. the authenticated local HUD contract;
2. exact membership in the two-agent core allowlist;
3. the current roster record;
4. Codex as the persisted backend;
5. exact membership in the model allowlist;
6. action/state compatibility;
7. no concurrent lifecycle operation for the same agent.

The implementation invokes existing `mp kill`, `mp revive`, and `mp switch`
contracts with fixed arguments. It captures bounded output, applies a timeout,
redacts error detail, and returns typed JSON. It does not introduce shell
execution, silent Claude fallback, or a second lifecycle implementation.

Same-profile Codex model changes continue to use the existing exact-session
resume contract. A stopped agent may be relaunched on a selected allowlisted
model through the same switch transaction. Engineers, queue, board, memory, and
unrelated tmux sessions are outside the mutation scope.

## Failure Semantics

Operations fail closed for unsupported agents, unsupported models, missing or
ambiguous roster records, backend mismatch, invalid state, concurrent operation,
timeout, provider failure, or failed exact recovery.

The response exposes a stable error code and a short sanitized operator message.
It never returns provider output, session identifiers, credential paths, command
arguments, or raw stderr. A failed operation triggers a fresh poll but does not
claim that the requested model or lifecycle state was reached.

## Verification

TDD contracts must prove:

- only Boss and Nightwatch receive the command strip;
- engineers cannot invoke the server operations even with crafted requests;
- only the two configured models are accepted;
- Kill requires two clicks inside five seconds;
- nested controls never open Attach;
- alive/dead action visibility is correct;
- switch and relaunch call fixed `mp` arguments without a shell;
- concurrent operations for one agent fail closed;
- output and errors are bounded and sanitized;
- roster confirmation, not optimistic UI state, determines success;
- a same-profile model switch preserves the existing exact-session contract;
- Boss operations do not mutate Nightwatch or engineers, and vice versa;
- stale telemetry does not remove lifecycle controls backed by fresh roster
  state;
- disposable browser and Docker verification remain green.

## Deployment Gate

Implementation occurs on `feat/hud-core-agent-controls` in an isolated
worktree. No merge, GitHub publication, or live deployment occurs until focused
tests, browser verification, and the complete packaged-source disposable Docker
suite pass and the operator explicitly approves deployment.
