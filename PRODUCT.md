# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

The primary user is Rafa, operating a local Windows workstation to plan,
delegate, supervise, review, and publish software work through MyPeople.

## Product Purpose

MyPeople is a local command center for a Boss, Nightwatch, and delegated
workers. It keeps tasks, project context, comments, evidence, terminal access,
provider state, and handoffs visible while model processes can be replaced
without losing the task. Success means Rafa can understand system health,
assign work, inspect evidence, and act from one coherent surface.

## Positioning

The task and its evidence belong to the project control plane, not to an
individual model process. A worker can be stopped or replaced while the task,
handoff, verification state, and project context remain durable.

## Operating Context

- Local Windows workstation with Docker Desktop, tmux, and a browser.
- Operator surfaces are Priorities, Wall, Dashboard/HUD, Terminal, and
  Terminal Graph.
- Boss and Nightwatch run locally; workers are launched only through explicit
  task/provider decisions.
- The default network is loopback-only. Tailscale and remote memory remain
  explicit opt-in profiles.
- Windows Win+H is the supported dictation path; MyPeople does not provide a
  second floating microphone runtime.

## Capabilities and Constraints

- Preserve the existing board, roster, queue, TaskSpec, proof, comments,
  terminal, provider-profile, and hybrid-memory sources of truth.
- Graph, Board, and HUD are views over the same runtime; they must not create a
  second store or parallel agent runtime.
- Cloudflare memory is disabled by default; the local bounded hybrid memory is
  the operational memory.
- The Command Canvas projects Boss, Nightwatch, workers, tasks, evidence, and
  terminal previews through existing routes.
- Visual changes must preserve functional routes, keyboard operation, responsive
  behavior, reduced-motion support, and the Scorpion dark/gold identity.
- Public repository documentation and UI strings remain English.

## Brand Commitments

- Product name: MyPeople.
- Visual direction: Scorpion / tactical command room, with obsidian, charcoal,
  brass-gold, amber, jade health, and ember risk signals.
- Preserve the Black Dossier-inspired mark and display character where already
  established.
- Board direction: Pit Wall density and operational scanability.
- HUD direction: retain the current information model while improving its
  typography, color hierarchy, and state clarity.
- Graph direction: real terminal cards inside agent nodes, with Boss and
  Nightwatch visually dominant over workers and evidence.

## Evidence on Hand

- Current routes: `/`, `/wall`, `/dashboard`, and `/terminal-graph`.
- Shared tokens: `bin/mypeople-ui.css`.
- Graph surface: `bin/terminal-graph.html` and `bin/graph-canvas.css`.
- Operator screenshot supplied by Rafa on 2026-08-08.
- Durable product and UI notes in the ObsidianBrain MyPeople roadmap, including
  `MYPEOPLE-UI-0001` and the upstream pattern adoption report.

## Product Principles

1. Operational truth comes before decoration.
2. One visual language spans every operator surface.
3. State, health, ownership, and evidence must be scannable at a glance.
4. Model replacement must never erase task continuity.
5. Motion, color, and density must communicate meaning rather than add noise.

## Accessibility & Inclusion

- Keep visible keyboard focus and semantic controls.
- Meet WCAG AA contrast for text and status states.
- Keep functional labels readable at desktop and narrow widths; terminal code
  may use a separate monospace scale.
- Respect `prefers-reduced-motion`.
- Provide loading, empty, error, blocked, and provider-unavailable states.
