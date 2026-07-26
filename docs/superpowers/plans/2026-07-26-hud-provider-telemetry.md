# HUD Provider Telemetry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a private, bounded operator telemetry projection and a compact Scorpion-themed Combat Status strip to the authenticated HUD.

**Architecture:** A focused Python module joins roster, provider-health receipts, and validated Codex usage without network calls. `todo-server.py` exposes the sanitized projection behind existing authentication. `dashboard.html` polls and renders it while retaining its last successful state on failures.

**Tech Stack:** Python 3 standard library, existing MyPeople runtime modules, vanilla HTML/CSS/JavaScript, `unittest`, disposable Docker verification.

---

### Task 1: Sanitized telemetry projection

**Files:**
- Create: `bin/operator_telemetry.py`
- Create: `verify/test_operator_telemetry.py`

- [ ] Write tests for role ordering, health precedence/staleness, safe session aliases, measured usage, unmeasured fallbacks, malformed input isolation, forbidden-field absence, and the 100-agent cap.
- [ ] Run `python -m unittest verify.test_operator_telemetry -v` and confirm it fails because `operator_telemetry` does not exist.
- [ ] Implement `build_operator_telemetry(roster, health, usage_reader, observed_at)` with no filesystem or network side effects.
- [ ] Re-run the focused test and confirm all cases pass.
- [ ] Commit `test: define operator telemetry projection`.

### Task 2: Authenticated server integration

**Files:**
- Modify: `bin/todo-server.py`
- Modify: `verify/test_operator_telemetry.py`

- [ ] Add a failing source-contract test proving authentication precedes `/todo/operator-telemetry`, the endpoint body is bounded, and no diagnostic or full session identifier is returned.
- [ ] Run the focused test and confirm the route assertion fails.
- [ ] Load the roster and health receipts, resolve only strict recorded Codex session files beneath the assigned profile home, and return the projection.
- [ ] Serialize at most 128 KiB; return a bounded `telemetry_unavailable` error when projection construction fails.
- [ ] Re-run telemetry, provider-health, and memory-canary telemetry tests.
- [ ] Commit `feat: expose authenticated operator telemetry`.

### Task 3: Scorpion Combat Status interface

**Files:**
- Modify: `bin/dashboard.html`
- Create: `verify/test_hud_provider_telemetry.py`

- [ ] Add failing DOM/source contracts for the Combat Status strip, semantic health states, model and health columns, session alias, measured/unmeasured token labels, safe `textContent`, row selection, empty state, and stale polling behavior.
- [ ] Run `python -m unittest verify.test_hud_provider_telemetry -v` and confirm the missing component fails.
- [ ] Implement compact horizontally scrolling telemetry cards using the existing charcoal, volt-yellow, semantic status colors, monospace data, restrained alive pulse, and selected-row highlight.
- [ ] Poll agents, roster, and telemetry together; retain the last successful telemetry after an error, label it `STALE`, and disable live animation.
- [ ] Re-run HUD, Scorpion theme, dictation-only, and browser journey contracts.
- [ ] Commit `feat: render provider telemetry in HUD`.

### Task 4: Integrated verification and deployment gate

**Files:**
- Modify only if verification exposes a defect in the new phase.

- [ ] Run focused Python tests for operator telemetry, provider health, memory telemetry, Scorpion theme, Windows dictation, and dashboard contracts.
- [ ] Build a candidate runtime image from the current live base.
- [ ] Run the complete isolated packaged-source verifier and browser journeys.
- [ ] Inspect the diff for secrets, private identifiers, Spanish public content, and unrelated changes.
- [ ] Present commits and evidence. Do not merge, push, or deploy until explicitly approved.
