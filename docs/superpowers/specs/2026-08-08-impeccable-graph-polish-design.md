# Impeccable Graph Canvas polish

## Scope

Apply a focused visual refinement to the existing MyPeople Command Canvas in
the isolated `codex/graph-command-canvas` worktree. This is not a product
redesign: the existing Scorpion dark/gold identity, Graph data projection,
terminal previews, controls, routes, and runtime contracts remain unchanged.

## Direction contract

- **Thesis:** a live command canvas where operational truth is visible before
  decoration; avoid generic dashboard cards and unreadable micro-labels.
- **Own world:** obsidian and charcoal surfaces, brass/gold actions, jade
  health, amber work, ember risk, crisp mono for telemetry, and a restrained
  display face for hierarchy. Depth comes from offset soft shadows and
  material contrast, not glow-only borders.
- **Story:** Rafa can identify Boss, Nightwatch, workers, task ownership,
  terminals, and health in one glance, then open the correct terminal or task.
- **First viewport:** the top bar establishes identity and health; the canvas
  gives Boss/Nightwatch priority; terminal previews remain the main evidence;
  the layer rail and inspector stay available without obscuring the graph.
- **Form:** established-world refinement, ranked first for safety over a full
  redesign; no new runtime, store, route, or dependency.

## Changes

1. Normalize Graph-specific tokens against the shared MyPeople palette.
2. Improve hierarchy and readability for labels, health, layer controls,
   inspector rows, toolbar controls, and terminal captions.
3. Replace repeated heavy side rails and glow-only states with 1px structural
   rules, soft offset depth, and state-specific accents.
4. Preserve the graph grid because this is an actual canvas/map surface, while
   reducing its visual dominance.
5. Add responsive and reduced-motion safeguards without changing behavior.

## Acceptance

- Existing focused Command Canvas tests remain green.
- Static detector findings for changed Graph markup/CSS are reduced or have a
  documented canvas/terminal-context exception.
- `/terminal-graph` remains functional and renders 0, 1, and many workers.
- No live container, data store, provider profile, or memory service changes.
