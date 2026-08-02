# MyPeople Graph Command Canvas

Date: 2026-08-02  
Status: visual direction selected; implementation plan ready

## Outcome

Evolve `/terminal-graph` into a dense Command Canvas that preserves the current MyPeople execution model while making ownership, live terminal state, task flow, evidence, and review status readable from one spatial surface.

The selected visual direction is the first generated concept: Boss remains the dominant command node, Nightwatch is an oversight node above it, workers and embedded terminal previews form the execution tier, and task/evidence/review cards form a downstream proof tier.

## Product boundaries

- MyPeople remains a local execution and coordination plane.
- The existing roster, board, TaskSpec fields, comments, proofs, terminal routes, and receipt history remain the sources of truth.
- The Graph is a read/write controller over those existing endpoints, not a second database or collaboration runtime.
- No rooms, invitations, external collaborators, presence indicators, chat, social controls, marketplace, or external-agent integrations.
- No Colmeia branding, logo, Portuguese copy, or macOS chrome is introduced.

## Visual system

Use the existing Scorpion/tactical-industrial tokens from `bin/mypeople-ui.css`:

- soot `#080807`
- charcoal `#12110e`
- armor `#1c1a14`
- gold `#f2c230`
- ember `#ff8a1f`
- bone `#f4f0df`
- ash `#9d9788`
- crimson `#dc493f`
- jade `#67b279`

Use clipped corners, thin technical borders, a subtle gold grid, compact Cascadia Mono telemetry, the gold mission rail, and restrained active-state glow. Do not add large gradients, glassmorphism, or ornamental imagery.

## Screen composition

1. Fixed top rail: MyPeople wordmark, active `Graph` view, view controls `Mission`, `Fleet`, `Attention`, and `Execution`, plus compact runtime/health indicators.
2. Canvas: dark infinite grid with pan and wheel zoom. Boss is the largest node in the command tier. Nightwatch sits above it. Live workers appear to the right with compact terminal previews and capability/status metadata. Tasks appear downstream as colored evidence-aware cards.
3. Left layer rail: toggles for `Agents`, `Tasks`, `Evidence`, `Decisions`, and `Terminals`. The rail filters the projection only; it never deletes board or roster data.
4. Right inspector: selected agent/task details, owner, state, acceptance condition, evidence count, and a link to the existing full task modal or owner terminal.
5. Bottom toolbar: select, connect (visual selection mode only), create task, frame, fit, and center Boss. Existing task creation uses `/todo/update`; no new graph persistence is introduced.
6. Bottom-right minimap: a compact projection of current node bounds with a viewport rectangle. Clicking the minimap recenters the canvas.

## Semantic projection

The graph endpoint may enrich its existing response with derived fields, but it must remain backward-compatible:

- Agent `role`: `boss`, `nightwatch`, or `worker`, inferred from existing `is_master` and Nightwatch identity rules.
- Agent `summary`, `backend`, and `status` for compact node telemetry.
- Hierarchy edges retain `parent` and `child` and add derived `kind`: `ASSIGNS` for command ownership or `OBSERVES` for Nightwatch oversight.
- Tasks retain `id`, `title`, `state`, `assignee`, `owner_live`, `updated`, `href`, and add derived `card_kind`, `proof_count`, `evidence_policy`, `done_condition`, and `project_slug`.

Derived `card_kind` values are `PRIORITY`, `EVIDENCE`, `REVIEW`, `BLOCKED`, and `DELIVERED`. They are presentation categories mapped from the existing task state and proof fields; they are not new persisted task states.

## Interaction rules

- Agent terminal previews remain read-only iframes; clicking a preview opens the existing same-origin writable terminal wrapper in the full-screen surface.
- Dragging an agent or task changes only the local canvas layout stored in versioned `localStorage`; it does not mutate roster or board data.
- Selecting an agent or task opens the inspector without opening a second browser window.
- Selecting a task can open the existing modal for editing, commenting, proof upload, and state changes.
- The `Connect` tool can select source and target and show a proposed typed relationship, but it does not write a graph edge because canonical relation mutation is not yet part of the MyPeople API.
- Filters and layers are reversible and persist locally.
- Polling continues at the existing cadence and must not resize terminal iframes when geometry changes.

## Acceptance criteria

- At a glance, an operator can identify Boss, Nightwatch, every live worker, task owner, blocked work, review work, and proof-bearing work.
- Graph data still comes from `/todo/terminal-graph` and `/todo/board`; no new server-side graph store exists.
- Existing owner-terminal links, task modal editing, task creation, comments, evidence uploads, fit, Boss centering, pan, zoom, and live polling continue to work.
- The selected task inspector shows owner, status, done condition, project, proof count, and a link to the full task view.
- The canvas works with zero workers, one worker, and many workers without the main hierarchy becoming unreadable.
- The interface contains no multi-user or external-agent concepts.
- Static contracts and Playwright coverage protect the semantic labels, projection fields, interaction surfaces, and stable terminal geometry.

