# Impeccable Graph Canvas polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing MyPeople Graph Canvas more legible and premium while preserving its current data, controls, and runtime behavior.

**Architecture:** Keep `terminal-graph.html` as the behavioral surface and `graph-canvas.css` as the Graph-specific visual layer. Reuse `mypeople-ui.css` tokens and add only scoped presentation rules; do not introduce a second component system or runtime.

**Tech Stack:** Existing HTML/CSS/vanilla JavaScript, Impeccable detector, Python focused tests, Docker verifier.

---

### Task 1: Record the visual contract

**Files:**
- Create: `PRODUCT.md`
- Create: `docs/superpowers/specs/2026-08-08-impeccable-graph-polish-design.md`

- [x] Capture product facts, brand commitments, constraints, and acceptance criteria.
- [x] Run a self-review for placeholders and contradictions.

### Task 2: Refine Graph presentation

**Files:**
- Modify: `bin/graph-canvas.css`
- Modify: `bin/terminal-graph.html` only if the direction contract comment is required by the visual workflow.

- [x] Add scoped typography and spacing tokens for readable functional labels.
- [x] Reduce repeated heavy rail borders and replace them with 1px rules plus soft offset shadows.
- [x] Increase node title/summary readability while keeping terminal code density unchanged.
- [x] Add clear focus, hover, disabled, empty, and degraded-health states.
- [x] Preserve the canvas grid as a subdued map surface and respect reduced motion.

### Task 3: Verify the isolated build

**Files:**
- Test: existing `verify/test_command_canvas*.py` and `verify/verify.sh`

- [x] Run Impeccable detector on changed Graph targets; the remaining grid advisory is intentional because this is an actual canvas/map surface.
- [x] Run focused Graph/Command Canvas tests and JavaScript syntax checks.
- [x] Build a disposable Docker image and run the focused verifier.
- [x] Capture `/terminal-graph` at desktop and narrow widths for visual review.
- [x] Keep live MyPeople on its current image until explicit deployment approval.

### Task 4: Commit the isolated result

**Files:**
- Commit only the visual contract, plan, and scoped Graph changes.

- [x] Review `git diff --check` and `git status`.
- [ ] Commit with `feat(ui): polish command canvas with impeccable direction`.
