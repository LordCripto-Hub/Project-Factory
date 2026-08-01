# Operator Reliability and Surface Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make MyPeople polling, mobile modals, build identity, recording, local memory health, and Board/Graph/HUD navigation reliable without changing live state.

**Architecture:** Extend the existing Python control plane and shared vanilla JavaScript/CSS presentation boundary. Keep one source of truth for runtime identity and existing stores for roster, board, recordings, and hybrid memory; add no dependency or parallel service.

**Tech Stack:** Python 3, vanilla JavaScript, CSS, tmux, asciinema, Docker Compose, unittest, Node test runner, Playwright.

---

### Task 1: Prove the isolated baseline and diagnose local memory availability

**Files:**
- Modify: `docs/superpowers/specs/2026-08-01-operator-reliability-and-surface-consolidation-design.md`
- Test: `verify/test_memory_activation_e2e.py`
- Test: `verify/test_automatic_memory_e2e.py`
- Test: `verify/test_windows_launcher.py`

- [ ] **Step 1: Run the existing focused baseline**

Run:

```powershell
python verify/test_automatic_memory_e2e.py
python verify/test_memory_activation_e2e.py
python verify/test_windows_launcher.py
python verify/test_scorpion_premium_visuals.py
python verify/test_windows_dictation_only.py
```

Expected: all tests pass from commit `8f73311`; record exact counts.

- [ ] **Step 2: Trace the local memory activation boundary without changing live**

Inspect the launcher, deployment compose, gateway client, and HUD projection. Record the confirmed root cause in the design document as a short `Implementation diagnosis` subsection. The diagnosis must distinguish adapter readiness from last-retrieval status.

- [ ] **Step 3: Commit the diagnosis**

```bash
git add docs/superpowers/specs/2026-08-01-operator-reliability-and-surface-consolidation-design.md
git commit -m "docs: diagnose local memory availability"
```

### Task 2: Add bounded local-memory readiness

**Files:**
- Modify: `bin/memory_observability.py`
- Modify: `bin/todo-server.py`
- Modify: `bin/dashboard.html`
- Modify: `windows/Start-MyPeople.ps1`
- Modify: `docker/compose.volume-backed.yml`
- Test: `verify/test_automatic_memory_observability.py`
- Test: `verify/test_windows_launcher.py`
- Test: `verify/test_memory_activation_e2e.py`

- [ ] **Step 1: Write failing readiness tests**

Add tests requiring a sanitized readiness projection shaped like:

```python
{
    "configured": True,
    "adapter": "local_hybrid",
    "readiness": "ready",
    "reason": "ok",
}
```

The tests must also require `disabled` to start no adapter and an absent adapter to remain typed `memory_unavailable` without blocking TaskSpec.

- [ ] **Step 2: Run tests and observe RED**

```powershell
python verify/test_automatic_memory_observability.py
python verify/test_windows_launcher.py
python verify/test_memory_activation_e2e.py
```

Expected: failure because readiness and launcher reconciliation do not exist.

- [ ] **Step 3: Implement the minimum readiness contract**

Add an allow-listed projection helper equivalent to:

```python
def project_memory_readiness(configured, reachable, reason=""):
    if not configured:
        return {"configured": False, "adapter": "local_hybrid", "readiness": "disabled", "reason": "disabled"}
    if reachable:
        return {"configured": True, "adapter": "local_hybrid", "readiness": "ready", "reason": "ok"}
    return {"configured": True, "adapter": "local_hybrid", "readiness": "unavailable", "reason": sanitize_reason(reason)}
```

The Windows launcher may reconcile only the existing approved local sidecar/profile when local automatic mode is configured. It must not activate Cloudflare or `codex_apps`.

- [ ] **Step 4: Run focused regressions and commit**

```powershell
python verify/test_automatic_memory_observability.py
python verify/test_automatic_memory_e2e.py
python verify/test_windows_launcher.py
python verify/test_memory_activation_e2e.py
git add bin/memory_observability.py bin/todo-server.py bin/dashboard.html windows/Start-MyPeople.ps1 docker/compose.volume-backed.yml verify
git commit -m "fix: reconcile local memory readiness"
```

### Task 3: Make Board polling monotonic and single-flight

**Files:**
- Modify: `bin/todos.html`
- Create: `verify/test_board_polling_contract.py`
- Modify: `verify/browser_journeys.js`

- [ ] **Step 1: Write a failing polling contract**

The fixture must resolve request 2 before request 1 and assert that request 1 cannot replace the newer snapshot. It must also assert that repeated refresh calls during one slow request produce one coalesced follow-up, not unbounded requests.

- [ ] **Step 2: Observe RED**

```powershell
python verify/test_board_polling_contract.py
```

Expected: the current direct `refresh()` assignments allow stale replacement and overlap.

- [ ] **Step 3: Implement the coordinator**

Use state equivalent to:

```javascript
const boardPoll = {inFlight: false, pending: false, issued: 0, applied: 0};
async function requestBoardRefresh() {
  if (boardPoll.inFlight) { boardPoll.pending = true; return; }
  boardPoll.inFlight = true;
  const requestId = ++boardPoll.issued;
  try {
    const next = await api('/todo/board');
    if (requestId > boardPoll.applied) {
      boardPoll.applied = requestId;
      applyBoardSnapshot(next);
    }
  } finally {
    boardPoll.inFlight = false;
    if (boardPoll.pending) { boardPoll.pending = false; queueMicrotask(requestBoardRefresh); }
  }
}
```

`applyBoardSnapshot` preserves modal identity, filters, thread scroll, sticky-bottom state, comments, and proofs.

- [ ] **Step 4: Verify and commit**

```powershell
python verify/test_board_polling_contract.py
python verify/test_scorpion_theme.py
git add bin/todos.html verify/test_board_polling_contract.py verify/browser_journeys.js
git commit -m "fix: make board polling monotonic"
```

### Task 4: Make Board and Graph modals keyboard-safe on mobile

**Files:**
- Modify: `bin/mypeople-ui.css`
- Modify: `bin/todos.html`
- Modify: `bin/terminal-graph.html`
- Create: `bin/visual-viewport.js`
- Create: `verify/test_mobile_modal_viewport.py`
- Modify: `verify/capture_scorpion_visuals.js`

- [ ] **Step 1: Write failing viewport and touch-target tests**

Require the shared adapter to set `--mp-visible-height` and `--mp-visible-offset`, subscribe to both `resize` and `scroll`, fall back to `100dvh`, keep mobile input text at `16px`, and make visible controls at least 24-by-24 pixels.

- [ ] **Step 2: Observe RED**

```powershell
python verify/test_mobile_modal_viewport.py
python verify/test_scorpion_premium_visuals.py
```

- [ ] **Step 3: Implement the shared adapter and CSS**

Use a singleton equivalent to:

```javascript
(() => {
  const root = document.documentElement;
  let queued = false;
  const apply = () => {
    queued = false;
    const viewport = window.visualViewport;
    root.style.setProperty('--mp-visible-height', `${viewport ? viewport.height : window.innerHeight}px`);
    root.style.setProperty('--mp-visible-offset', `${viewport ? viewport.offsetTop : 0}px`);
  };
  const schedule = () => { if (!queued) { queued = true; requestAnimationFrame(apply); } };
  visualViewport?.addEventListener('resize', schedule);
  visualViewport?.addEventListener('scroll', schedule);
  addEventListener('resize', schedule);
  apply();
})();
```

Load it exactly once in Board and Graph. Scope modal geometry to the variables and keep Scorpion styling intact.

- [ ] **Step 4: Run mobile visual capture and commit**

```powershell
python verify/test_mobile_modal_viewport.py
python verify/test_windows_dictation_only.py
python verify/test_scorpion_premium_visuals.py
git add bin/mypeople-ui.css bin/visual-viewport.js bin/todos.html bin/terminal-graph.html verify
git commit -m "fix: keep mobile modals above virtual keyboards"
```

### Task 5: Expose authoritative runtime build identity

**Files:**
- Create: `bin/runtime_identity.py`
- Modify: `bin/todo-server.py`
- Modify: `bin/queue-server.py`
- Modify: `bin/todos.html`
- Modify: `bin/terminal-graph.html`
- Modify: `bin/dashboard.html`
- Modify: `docker/Dockerfile.runtime-image`
- Modify: `windows/Upgrade-MyPeopleDockerImage.ps1`
- Create: `verify/test_runtime_build_identity.py`

- [ ] **Step 1: Write failing identity tests**

Require one normalized payload:

```python
{"schema": 1, "sha": "81c7515", "build": "20260801T174621Z", "image": "mypeople-node:upgrade-…", "state": "live"}
```

Tests require identical Board/Graph/HUD output, `unknown` on absence, sanitization, no placeholders, and runtime-image rather than host-checkout provenance.

- [ ] **Step 2: Observe RED and implement**

```powershell
python verify/test_runtime_build_identity.py
```

Implement a reader that allow-lists schema, SHA, build, image, and state. Generate the manifest during image construction and allow the upgrade transaction to provide only the safe deployed image reference.

- [ ] **Step 3: Verify and commit**

```powershell
python verify/test_runtime_build_identity.py
python verify/test_runtime_image_contract.py
python verify/test_windows_docker_recovery.py
git add bin docker windows verify
git commit -m "feat: expose authoritative runtime build identity"
```

### Task 6: Make asciinema recording opt-in and lifecycle-safe

**Files:**
- Modify: `bin/mp`
- Modify: `bin/queue-client.py`
- Modify: `bin/dashboard.html`
- Create: `verify/test_recording_policy.py`
- Modify: `verify/core_verify.py`

- [ ] **Step 1: Write failing recording-policy tests**

Test default `off`, explicit `on`, one owned recorder, idempotent respawn, kill/retires cleanup, retained casts, and sanitized HUD values `recording`, `off`, `unknown`.

- [ ] **Step 2: Observe RED**

```powershell
python verify/test_recording_policy.py
```

- [ ] **Step 3: Implement deterministic policy and ownership**

Resolve policy with a helper equivalent to:

```python
def recording_mode(agent, profile, env):
    value = agent.get("recording") or profile.get("recording") or env.get("MYPEOPLE_RECORDING_DEFAULT", "off")
    return value if value in {"on", "off"} else "off"
```

Store recorder PID/agent ownership in private runtime metadata. Never delete cast files. Recorder failure updates health without killing the agent.

- [ ] **Step 4: Verify and commit**

```powershell
python verify/test_recording_policy.py
python verify/test_runtime_supervisor.py
python verify/test_provider_session.py
git add bin/mp bin/queue-client.py bin/dashboard.html verify
git commit -m "feat: make terminal recording opt in"
```

### Task 7: Retire Wall and unify Board / Graph / HUD navigation

**Files:**
- Modify: `bin/todo-server.py`
- Modify: `bin/queue-server.py`
- Modify: `bin/todos.html`
- Modify: `bin/terminal-graph.html`
- Modify: `bin/dashboard.html`
- Modify: `bin/mypeople-ui.css`
- Delete: `bin/wall.html`
- Create: `verify/test_operator_navigation.py`
- Modify: `verify/browser_journeys.js`
- Modify: `verify/browser-smoke.js`
- Modify: `verify/capture_scorpion_visuals.js`
- Modify: `verify/test_terminal_views.js`

- [ ] **Step 1: Write failing navigation tests**

Require exactly Board `/`, Graph `/terminal-graph`, and HUD `/dashboard` on all three surfaces; `/wall` must return a safe redirect to `/`; visible Wall/TODO/Dashboard navigation labels must be absent.

- [ ] **Step 2: Inventory Wall-only behavior before deletion**

Assert Graph/HUD retain attach, read-only terminals, agent state/filtering, ownership, and status. The test must fail if any Wall-only behavior lacks a destination.

- [ ] **Step 3: Observe RED and implement**

```powershell
python verify/test_operator_navigation.py
node verify/test_terminal_views.js
```

Replace navigation, return `302 Location: /` for `/wall`, remove Wall page/polling and obsolete test fixtures, then remove only CSS selectors no longer used by Graph/HUD.

- [ ] **Step 4: Verify and commit**

```powershell
python verify/test_operator_navigation.py
node verify/test_terminal_views.js
python verify/test_scorpion_premium_visuals.py
python verify/test_public_repository.py
git add -A bin verify
git commit -m "feat: consolidate operator navigation"
```

### Task 8: Integrated disposable-Docker verification and handoff

**Files:**
- Modify: `docs/superpowers/specs/2026-08-01-operator-reliability-and-surface-consolidation-design.md`
- Create: `docs/verification/operator-reliability-2026-08-01.md`

- [ ] **Step 1: Run all focused tests from a clean tree**

```powershell
python verify/test_board_polling_contract.py
python verify/test_mobile_modal_viewport.py
python verify/test_runtime_build_identity.py
python verify/test_recording_policy.py
python verify/test_operator_navigation.py
python verify/test_automatic_memory_observability.py
python verify/test_memory_activation_e2e.py
```

- [ ] **Step 2: Build the candidate image and run isolated verification**

```powershell
$baseImage = docker inspect mypeople --format '{{.Config.Image}}'
docker build -f docker/Dockerfile.runtime-image --build-arg BASE_IMAGE=$baseImage -t mypeople-node:operator-reliability-candidate .
powershell -NoProfile -ExecutionPolicy Bypass -File verify/Invoke-IsolatedVerify.ps1 -Image mypeople-node:operator-reliability-candidate -TimeoutSeconds 1800 -UsePackagedSource
```

Expected: isolated verification passes without mounting live volumes, credentials, or sessions.

- [ ] **Step 3: Run desktop and mobile browser journeys**

Run the candidate only in the disposable verifier and capture Board, Board modal, Graph, Graph modal, and HUD at 1440×900 and 390×844. Expected: no console errors, external requests, horizontal overflow, unnamed controls, or sub-24px interactive targets.

- [ ] **Step 4: Prove live remained unchanged**

Compare the pre-recorded live image, start time, board SHA-256, and stable roster SHA-256 with their post-run values. Expected: exact match.

- [ ] **Step 5: Write evidence and commit**

```bash
git add docs/verification/operator-reliability-2026-08-01.md docs/superpowers/specs/2026-08-01-operator-reliability-and-surface-consolidation-design.md
git commit -m "docs: record operator reliability verification"
```

- [ ] **Step 6: Stop for approval**

Do not merge, push, or deploy. Present red/green evidence, commits, visual artifacts, residual risks, and the unchanged-live proof to the user.
