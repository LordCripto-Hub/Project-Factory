# MyPeople Command Canvas — Status and Handoff

Date: 2026-08-02
Branch: `codex/graph-command-canvas`
Base: `main` at `18996bc`
Remote: `https://github.com/LordCripto-Hub/Project-Factory.git`

## Executive summary

The Command Canvas is an evolution of `/terminal-graph` within the current
MyPeople model. It introduces no external users, external agents, rooms, chat,
presence, graph database, or parallel runtime.

Current status: **ready for controlled review and integration; not yet a
production release**.

Existing sources of truth remain authoritative:

- MyPeople agent roster and runtime state;
- board tasks, comments, proofs, and TaskSpec;
- existing same-origin terminal routes and wrappers;
- browser-local preferences for camera, layers, and positions only.

## What was built

### Semantic projection

`bin/todo-server.py` enriches the graph response without breaking existing
fields:

- derived roles: `boss`, `nightwatch`, and `worker`;
- agent telemetry: `summary`, `backend`, and `status`;
- typed edges: `ASSIGNS` and `OBSERVES`;
- visual task categories: `PRIORITY`, `EVIDENCE`, `REVIEW`, `BLOCKED`, and
  `DELIVERED`;
- `proof_count`, `evidence_policy`, `done_condition`, and `project_slug`.

### Canvas

`bin/terminal-graph.html` now contains:

- a top rail with `Graph`, `Mission`, `Fleet`, `Attention`, and `Execution`
  views;
- a Boss → Nightwatch → workers → tasks/evidence hierarchy;
- semantic SVG connectors;
- an agent/task inspector;
- `Agents`, `Tasks`, `Evidence`, `Decisions`, and `Terminals` filters;
- a minimap;
- locally persistent camera and layout preferences;
- task creation and editing through existing canonical routes;
- terminal previews that preserve the previous links and wrappers.

`bin/graph-canvas.css` centralizes the canvas treatment and reuses the tokens
from `bin/mypeople-ui.css`.

## Verified evidence

Executed in the isolated worktree:

```text
python -m unittest verify.test_graph_projection verify.test_graph_command_canvas verify.test_priorities_terminal_popup verify.test_scorpion_theme -v
Ran 13 tests ... OK

node --check verify/test_terminal_views.js
node verify/test_terminal_views.js
Wall stable: 468x318x453.5999755859375x272.1600036621094
Graph stable: 267.357421875x249.4859619140625x262.49639892578125x157.497802734375

git diff --check
clean

powershell -NoProfile -ExecutionPolicy Bypass -File .\\verify\\Invoke-IsolatedVerify.ps1 -Image mypeople-node:command-canvas-228cc76
Isolated MyPeople verification passed.
```

The embedded graph script parses correctly, and the visual contract contains
Boss, Nightwatch, worker, task, inspector, layers, minimap, and toolbar.

## Known limits

1. The complete isolated verifier now passes against the reviewed candidate
   image `mypeople-node:command-canvas-228cc76`; it must never target the live
   container.
2. A live migration, backup, restore, and rollback cycle has not been performed
   for this branch.
3. `Connect` is a visual selection interaction; it does not persist new
   relationships because MyPeople has no canonical edge-mutation route.
4. Camera, layers, and positions are browser-local preferences, not operational
   state.
5. The browser test protects contracts and stable geometry, but a longer matrix
   with zero, one, and many workers under continuous polling remains required.
6. The canvas deliberately contains no multi-user collaboration concepts or
   external agents.

## Handoff for the `main` supervisor

### Git state

Commits on this branch:

- `21aece7 feat: build mypeople command canvas`
- `ca17b46 chore: clean canvas docs whitespace`

The worktree is clean. `main` has not been modified.

### Recommended integration order

1. Review this document, the Command Canvas design specification, and its
   implementation plan.
2. Run the focused tests and the Node test from this worktree.
3. Start an isolated verification instance with a reviewed image; do not test
   against the live `mypeople` container.
4. Manually review `/terminal-graph` with zero, one, and multiple workers.
5. Verify that the task modal, comments, proofs, status, and terminals still
   use existing routes.
6. Open a pull request from `codex/graph-command-canvas` to `main`.
7. Merge only after supervisor review and the isolated suite pass.

### Suggested commands

```bash
python -m unittest verify.test_graph_projection verify.test_graph_command_canvas verify.test_priorities_terminal_popup verify.test_scorpion_theme -v
node --check verify/test_terminal_views.js
node verify/test_terminal_views.js
git diff --check
```

For complete validation, follow `verify/Invoke-IsolatedVerify.ps1` or
`verify/verify.sh` with a reviewed local image. Do not run `docker compose down
-v` or point the verifier at live state.

## Integration acceptance criteria

The supervisor may integrate when:

- focused tests and the isolated suite pass;
- no console errors or regressions appear in Wall, Priorities, Dashboard, or
  Terminal;
- terminals preserve their geometry during polling;
- the selected task shows owner, status, done condition, project, and proofs;
- layers only filter the projection and do not mutate the board or roster;
- no second graph store or Colmeia runtime is introduced;
- visual review confirms legibility with zero, one, and many workers.

## Release decision

After isolated verification and the pull request, the Command Canvas may enter
a **private alpha**. It must not yet be presented as a multi-user capability or
as an independent Colmeia product: it is an advanced visual surface over the
local MyPeople runtime.
