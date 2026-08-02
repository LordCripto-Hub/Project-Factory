# MyPeople Graph Command Canvas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the selected Command Canvas direction into MyPeople's existing `/terminal-graph` surface without adding a new runtime, graph database, or collaboration model.

**Architecture:** Keep `todo-server.py` as the canonical projection endpoint and evolve `terminal-graph.html` as the controller/view. Derived roles, edge kinds, and task card categories are computed from the existing roster and board. Layout state, layer filters, and the selected viewport remain local browser preferences; task editing and evidence continue through the existing task APIs.

**Tech Stack:** Python standard library, existing same-origin HTTP endpoints, vanilla HTML/CSS/JavaScript, SVG paths for typed connectors, DOM-based minimap, existing Node/Playwright verification, and the shared `bin/mypeople-ui.css` token system.

---

### Task 1: Lock the graph projection contract

**Files:**
- Create: `verify/test_graph_projection.py`
- Modify: `bin/todo-server.py:162-177`

- [ ] **Step 1: Write failing projection tests**

Add a focused `unittest` that loads `todo-server.py` with a temporary board and patches `queue_get`, `roster_map`, and `geometry`. Assert that `wall_data(True)` returns:

```python
{
    "agents": [
        {"agent_id": "node-1/main:Boss", "role": "boss"},
        {"agent_id": "node-1/nightwatch:Nightwatch", "role": "nightwatch"},
        {"agent_id": "node-1/eng:Worker", "role": "worker"},
    ],
    "edges": [
        {"parent": "node-1/main:Boss", "child": "node-1/eng:Worker", "kind": "ASSIGNS"},
        {"parent": "node-1/main:Boss", "child": "node-1/nightwatch:Nightwatch", "kind": "OBSERVES"},
    ],
}
```

Also assert that a board task with `state="blocked"`, `proofs=[{"kind":"text"}]`, `evidencePolicy="required"`, and `projectSlug="graph"` exposes `card_kind="BLOCKED"`, `proof_count=1`, `evidence_policy="required"`, `project_slug="graph"`, and its existing `href`.

- [ ] **Step 2: Run the focused test and verify it fails**

Run `python -m unittest verify.test_graph_projection -v` from the repository root. It must fail because the current response has no `role`, `kind`, or derived task fields.

- [ ] **Step 3: Implement the backward-compatible projection**

In `wall_data(True)`, derive roles from current fields and the configured `NW_AGENT`:

```python
def graph_role(agent_id, row):
    if row.get("is_master"):
        return "boss"
    if agent_id == NW_AGENT or agent_id.endswith(":Nightwatch"):
        return "nightwatch"
    return "worker"
```

Add `role`, `summary`, `backend`, and `status` to each agent. Add `kind` to hierarchy edges, using `OBSERVES` when the child role is `nightwatch`, otherwise `ASSIGNS`. Derive `card_kind` with this exact precedence: `BLOCKED` for blocked tasks, `REVIEW` for review tasks, `DELIVERED` for done tasks, `EVIDENCE` when proofs are present, otherwise `PRIORITY`. Include only existing board fields plus the derived values; do not create a second persisted graph record.

- [ ] **Step 4: Run the focused test and the existing graph-related tests**

Run `python -m unittest verify.test_graph_projection verify.test_task_project_fields verify.test_priorities_terminal_popup -v`. Expected result: all tests pass and legacy fields remain available.

- [ ] **Step 5: Commit the projection contract**

Run `git add bin/todo-server.py verify/test_graph_projection.py && git commit -m "feat: enrich terminal graph projection"`.

### Task 2: Replace the graph shell with Command Canvas chrome

**Files:**
- Create: `verify/test_graph_command_canvas.py`
- Modify: `bin/terminal-graph.html:1-3`
- Modify: `bin/mypeople-ui.css:10`

- [ ] **Step 1: Write failing static contracts**

Assert that `terminal-graph.html` contains `MyPeople`, `Graph`, `Mission`, `Fleet`, `Attention`, `Execution`, `Boss`, `Nightwatch`, `Layers`, `Agents`, `Tasks`, `Evidence`, `Decisions`, `Terminals`, `Task inspector`, and `Minimap`. Assert that the page still contains `'/todo/terminal?agent='`, `target='_blank'`, `rel='noopener'`, and `/todo/update`. Assert that the page does not contain `room`, `invite`, `presence`, `chat`, `external agent`, or `Colmeia`.

Assert that the page includes `/assets/mypeople-ui.css` and that the CSS retains `--soot`, `--charcoal`, `--armor`, `--gold`, `--ember`, `--bone`, `--ash`, `--crimson`, and `--jade`.

- [ ] **Step 2: Run the focused test and verify it fails**

Run `python -m unittest verify.test_graph_command_canvas -v`. It must fail against the current `Terminal Graph` shell.

- [ ] **Step 3: Add the fixed chrome and structural regions**

Replace the current header/filter markup with fixed, accessible regions:

```html
<header class="graph-topbar">
  <a class="graph-brand" href="/">MyPeople</a>
  <nav class="graph-views" aria-label="Graph views">
    <button class="active" data-view="graph">Graph</button>
    <button data-view="mission">Mission</button>
    <button data-view="fleet">Fleet</button>
    <button data-view="attention">Attention</button>
    <button data-view="execution">Execution</button>
  </nav>
  <div class="graph-health"><span id="healthState">LOCAL</span><span id="offline">metadata offline</span></div>
</header>
<aside id="layerRail" class="layer-rail" aria-label="Graph layers">…</aside>
<aside id="inspector" class="graph-inspector" aria-live="polite"><h2>Task inspector</h2><div id="inspectorBody">Select an agent or task.</div></aside>
<div id="minimap" class="graph-minimap" aria-label="Minimap"><div id="minimapViewport"></div><div id="minimapNodes"></div></div>
<nav id="canvasToolbar" class="canvas-toolbar" aria-label="Canvas tools">…</nav>
```

Keep `#viewport`, `#world`, `#edges`, `#backlogZone`, `#full`, and `#taskModal` so existing behavior can be upgraded in place. Keep the existing Create, Fit, and Boss capabilities accessible through the new toolbar.

- [ ] **Step 4: Add the Command Canvas CSS**

Add scoped `.graph-*`, `.canvas-*`, `.layer-*`, `.inspector-*`, `.minimap-*`, `.agent-node`, and `.task-node` rules to `mypeople-ui.css`. Use the existing token variables, clipped corners, a gold mission rail on Boss, and responsive fallbacks that collapse the inspector and layer rail below 980px. Do not remove existing styles used by Priorities, Wall, Dashboard, or Terminal.

- [ ] **Step 5: Run static and existing theme tests**

Run `python -m unittest verify.test_graph_command_canvas verify.test_scorpion_theme verify.test_priorities_terminal_popup -v`. Expected result: PASS.

### Task 3: Render semantic agent and task cards

**Files:**
- Modify: `bin/terminal-graph.html:4-12`
- Modify: `bin/mypeople-ui.css:10`

- [ ] **Step 1: Add semantic card helpers before changing layout**

Implement `agentRole(a)`, `agentLabel(a)`, and `taskCardKind(t)` in the graph script. `agentLabel` must display `Boss`, `Nightwatch`, or a short worker label without hiding the full `agent_id` (the full id remains in inspector metadata). `taskCardKind` uses server `card_kind` when present and the same precedence fallback on older responses.

- [ ] **Step 2: Render agent nodes with the selected visual hierarchy**

Update `makeAgent` and `updateAgent` so every node includes a title, role/capability label, state badge, compact telemetry row, and embedded terminal preview. Boss receives `.node--boss` and a gold `MISSION RAIL`; Nightwatch receives `.node--nightwatch` and a dashed oversight treatment; workers receive `.node--worker`. Clicking the terminal preview still opens the existing full-screen terminal wrapper.

- [ ] **Step 3: Render task cards with evidence-aware categories**

Update `makeTask` and `updateTask` to include `.task-kind`, `.task-title`, `.task-owner`, `.task-proof`, and `.task-state`. Use `PRIORITY`, `EVIDENCE`, `REVIEW`, `BLOCKED`, and `DELIVERED` as compact labels. Keep the click handler calling `openCard(t.id, true)` so the canonical modal remains the editing surface.

- [ ] **Step 4: Add deterministic Command Canvas layout**

Replace the depth-row layout with stable zones: Boss at the command anchor, Nightwatch above, workers in the execution column, and task cards in the proof column. Preserve any existing saved x positions and add y positions under a versioned key `mp_graph_canvas_v1`. With zero workers, keep Boss and Nightwatch centered. With one worker, place its task cards beside it instead of creating an empty column.

- [ ] **Step 5: Verify live polling does not resize terminal previews**

Run `node verify/test_terminal_views.js` after the layout change. Expected result: Wall and Graph report stable terminal viewport dimensions while graph polling receives changing `cols` and `rows` fixtures.

### Task 4: Add typed edges, inspector, layers, and views

**Files:**
- Modify: `bin/terminal-graph.html:11-20`
- Modify: `bin/mypeople-ui.css:10`

- [ ] **Step 1: Write typed connector rendering**

Update `drawEdges()` to render SVG paths with `data-kind`, visible arrow markers, and short labels. Map `ASSIGNS` to gold solid, `OBSERVES` to ash dashed, task ownership to ember/gold, and blocked task emphasis to crimson. Keep the SVG pointer-transparent so canvas dragging remains available.

- [ ] **Step 2: Implement selected-object state and inspector rendering**

Add `selected={kind,id}` state and `selectAgent(id)`/`selectTask(id)` functions. The inspector must show for an agent: role, state, backend, full id, terminal link; for a task: title, card kind, owner, state, done condition, project, proof count, and an `Open full task` action. Selecting a task must not mutate the board. Keep `openCard` as the path for editing.

- [ ] **Step 3: Implement reversible layer filters**

Create the five layer toggles. `Agents` hides agent nodes and their related edges; `Tasks` hides task cards; `Evidence` hides only cards with proof; `Decisions` maps to review cards; `Terminals` hides iframe previews while leaving agent identity cards visible. Persist the toggle set under `mp_graph_layers_v1` and expose a reset action.

- [ ] **Step 4: Implement view buttons as local projections**

Make `Graph` the default. `Mission` fits the entire active graph, `Fleet` shows agent nodes and hides task cards, `Attention` shows blocked/review cards, and `Execution` shows working/recurring cards. The buttons only change local filters and camera state; they do not add server routes or data.

- [ ] **Step 5: Run browser journeys with a semantic fixture**

Extend `verify/test_terminal_views.js` with Boss, Nightwatch, two workers, and priority/evidence/blocked tasks. Assert `.graph-topbar`, `.layer-rail`, `.graph-inspector`, `.graph-minimap`, `.canvas-toolbar`, at least one `path[data-kind="ASSIGNS"]`, one `path[data-kind="OBSERVES"]`, task-card selection, and a changed inspector body after clicking a task. Run `node verify/test_terminal_views.js` and expect PASS.

### Task 5: Add minimap, camera persistence, and accessibility checks

**Files:**
- Modify: `bin/terminal-graph.html:13-21`
- Modify: `bin/mypeople-ui.css:10`
- Modify: `verify/test_graph_command_canvas.py`

- [ ] **Step 1: Implement minimap projection**

Add `renderMinimap()` after every layout, drag, layer change, and poll. Compute the bounds from visible agents/tasks, draw compact DOM rectangles with the same state colors, and position `#minimapViewport` from the current camera. Clicking the minimap converts the click point to world coordinates and recenters without changing zoom.

- [ ] **Step 2: Persist camera and drag positions safely**

Persist `{x,y,z}` under `mp_graph_camera_v1` and node positions under `mp_graph_canvas_v1`. Parse both values defensively; invalid JSON falls back to the deterministic layout. Never persist task content, agent metadata, evidence, or secrets.

- [ ] **Step 3: Add keyboard and reduced-motion behavior**

Keep `Escape` closing the terminal/task surface. Add `g` to fit the Graph, `b` to center Boss, and `0` to reset layers only when focus is not in an input/textarea/select. Add `prefers-reduced-motion` rules so active glows and minimap transitions become static.

- [ ] **Step 4: Run the static contracts and browser suite**

Run `python -m unittest verify.test_graph_command_canvas verify.test_scorpion_theme verify.test_priorities_terminal_popup -v` and `node verify/test_terminal_views.js`. Expected result: PASS with no console errors.

### Task 6: Documentation, full verification, and handoff

**Files:**
- Modify: `README.md`
- Modify: `docs/USER-MANUAL.md`
- Modify: `docs/MINIMAL-ARCHITECTURE.md`
- Modify: `verify/verify.sh` only if the new focused test needs suite registration

- [ ] **Step 1: Document the Graph entry point and boundaries**

Add the Command Canvas to the UI route list and explain that it is a projection/controller over the existing roster and board. Document layer filters, view buttons, minimap, inspector, and the fact that Connect is visual-only until canonical relation mutation exists.

- [ ] **Step 2: Run focused verification**

Run `python -m unittest verify.test_graph_projection verify.test_graph_command_canvas verify.test_scorpion_theme verify.test_priorities_terminal_popup -v` and `node verify/test_terminal_views.js`.

- [ ] **Step 3: Run the repository's standard verification entry point**

Run the repository's documented isolated verifier (`verify/Invoke-IsolatedVerify.ps1` with a reviewed local image, or `verify/verify.sh` inside the verifier container). Do not mutate the live `mypeople` container during verification.

- [ ] **Step 4: Review the final diff and commit**

Run `git diff --check`, `git status --short`, and `git diff --stat`. Confirm that no Colmeia runtime, external-agent integration, secret, or new graph store was introduced. Commit with `git add bin/todo-server.py bin/terminal-graph.html bin/mypeople-ui.css verify/test_graph_projection.py verify/test_graph_command_canvas.py verify/test_terminal_views.js README.md docs/USER-MANUAL.md docs/MINIMAL-ARCHITECTURE.md && git commit -m "feat: build mypeople command canvas"`.

## Self-review

- **Spec coverage:** projection fields are covered by Task 1; shell and token preservation by Task 2; hierarchy/card layout by Task 3; typed edges/inspector/layers/views by Task 4; minimap/camera/accessibility by Task 5; docs and verification by Task 6.
- **Placeholder scan:** the plan contains no `TBD`, empty TODO, or unspecified edge-case step; each task names exact files, commands, and expected outcomes.
- **Type consistency:** the projection uses `role`, `kind`, `card_kind`, `proof_count`, `evidence_policy`, `done_condition`, and `project_slug`; the UI reads those names and falls back to current fields for compatibility. Local keys are `mp_graph_canvas_v1`, `mp_graph_layers_v1`, and `mp_graph_camera_v1`.
