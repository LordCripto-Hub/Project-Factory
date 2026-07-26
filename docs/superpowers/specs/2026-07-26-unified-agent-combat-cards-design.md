# Unified Agent Combat Cards Design

## Objective

Replace the duplicated Combat Status and Agents sections with one operational card grid. Each active agent card is the source for status, telemetry, compact lifecycle information, and terminal attachment.

## Scope

- Archive and remove the stale `node-1/main:eng-3` roster row from the live HUD without deleting task, comment, proof, TaskSpec, provider-session, or audit history.
- Remove the active Agents table from the HUD.
- Keep retired-agent history outside the active grid and collapsed by default.
- Preserve the current Scorpion visual language, authenticated telemetry endpoint, provider routing, Gate B, and lifecycle CLI contracts.

## Card Information Architecture

Each card shows only:

1. role/name, lifecycle state, work status, and provider health;
2. provider/model and profile;
3. bounded session alias and token measurement;
4. compact Boss relationship when applicable;
5. a one-line summary with a bounded expansion affordance when truncated;
6. compact lifecycle actions appropriate to the current state.

The raw spawn command is never rendered as a paragraph. A short `Copy spawn` action copies the complete existing command. Alive agents expose `Attach`; dead non-retired agents expose `Spawn` or `Revive` according to the existing roster contract. Actions retain existing authenticated endpoints and do not execute arbitrary browser-provided commands.

## Interaction Contract

- Clicking or pressing Enter/Space on an attachable card opens that agent's terminal using the same URL as the current Attach button.
- Buttons and expandable summary content stop propagation so they never trigger attachment.
- Cards expose keyboard focus, an accessible name, visible focus state, and explicit disabled/non-attachable treatment.
- Health, session, and usage remain honest: unavailable and not-measured states are displayed rather than inferred.

## Data Flow

The browser continues to fetch `/agents`, `/roster`, and `/todo/operator-telemetry`. A deterministic join keyed by `agent_id` creates one view model per non-retired roster/agent row. Telemetry enriches that view model but never creates a card by itself for a stale, dead artifact that has been archived from the roster.

The live `eng-3` cleanup is a separate operator transaction: write a private timestamped archive, verify its digest and row count, atomically remove only the exact stale roster row, and confirm Boss/Nightwatch remain unchanged.

## Error Handling

- If telemetry fails, cards remain usable from roster/agent state and show telemetry as stale.
- If attach URL is unavailable, the card remains non-interactive and explains that attachment is unavailable.
- Failed spawn/revive actions keep the card visible and surface the server error.
- Missing optional summary, Boss, session, or usage fields never remove an otherwise valid active card.

## Verification

TDD contracts must prove:

- the Agents table is absent and active information exists in the cards;
- one active card is produced per active agent without duplication;
- card click/keyboard activation uses the existing attach URL;
- nested actions do not trigger attach;
- spawn commands are compact and copied rather than rendered in full;
- summaries are bounded and expandable;
- retired/stale test artifacts do not appear in the active grid;
- telemetry failure leaves lifecycle controls usable;
- Scorpion theme, Windows dictation-only behavior, Gate B, and provider contracts remain green;
- the packaged-source Docker suite and browser journeys pass before live deployment.

## Deployment Gate

Implementation occurs in `feat/hud-unified-agent-cards`. No merge, GitHub push, or live deployment occurs until focused tests and the complete packaged-source isolated Docker verifier pass and the operator approves deployment.
