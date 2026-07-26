# Automatic Memory and Bounded Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make bounded, read-only hybrid memory automatic for eligible Project Factory owner tasks while preserving manual canary diagnosis, typed fail-open execution, and instant rollback.

**Architecture:** A deterministic compiler derives one bounded query from the card, then a single recovery coordinator attempts fast, deep, exhaustive, and local-emergency adapters in order under one deadline. TaskSpec embeds at most three provenance-bearing claims and 300 estimated tokens; runtime control, receipts, API, and HUD expose only bounded metadata and never make memory a prerequisite for task execution.

**Tech Stack:** Python 3 standard library, SQLite FTS5, Node.js memory gateway, Bash/Docker Compose sidecar, PowerShell launcher, vanilla HTML/CSS/JavaScript, `unittest`.

---

## File Map

- Create `bin/automatic_memory.py`: deterministic query, eligibility, mode control, token estimate, and typed public outcomes.
- Create `bin/memory_recovery.py`: ordered four-level coordinator and shared budgets.
- Create `bin/local_memory_emergency.py`: read-only emergency adapter with private temporary-view lifecycle.
- Create `experiments/memory-gate-b/src/memory_bench/exhaustive.py`: bounded exploration over the existing event collection.
- Modify `experiments/memory-gate-b/src/memory_bench/taskspec_memory.py`: expose fast, deep, and exhaustive adapters without creating another store.
- Modify `experiments/memory-gate-b/docker/live-canary-entrypoint.sh`: serve the richer bounded recovery response.
- Modify `bin/project_context.py`: validate typed recovery responses and embed bounded claims without blocking TaskSpec.
- Modify `bin/mp`: choose `off`, `automatic`, or `manual_canary`; record safe receipts.
- Modify `bin/memory_canary.py`: migrate the boolean control record to an explicit mode while preserving old files.
- Modify `bin/todo-server.py`, `bin/dashboard.html`, and `bin/todos.html`: expose mode, health, and last bounded outcome.
- Modify `windows/Start-MyPeopleMemoryCanary.ps1`: support automatic activation and reversible shutdown.
- Add focused tests under `verify/` and `experiments/memory-gate-b/tests/`; register them in `verify/run-suite.sh`.
- Update `experiments/memory-gate-b/README.md` and the English user manual with operation, budgets, rollback, and non-goals.

### Task 1: Deterministic Query and Eligibility Contract

**Files:**
- Create: `bin/automatic_memory.py`
- Create: `verify/test_automatic_memory_query.py`
- Modify: `verify/run-suite.sh`

- [ ] **Step 1: Write the failing query tests**

```python
import pathlib, sys, unittest
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
from automatic_memory import derive_memory_query, memory_eligibility

class AutomaticMemoryQueryTests(unittest.TestCase):
    def test_query_is_deterministic_deduplicated_and_bounded(self):
        task = {
            "id": "task-1", "projectSlug": "project-factory",
            "text": "Repair exact session recovery",
            "doneCondition": "Repair exact session recovery\nPreserve task ownership",
            "contextQuestion": "Why did recovery reject stale tmux windows?",
        }
        self.assertEqual(
            derive_memory_query(task),
            "Repair exact session recovery | Preserve task ownership | "
            "Why did recovery reject stale tmux windows?",
        )
        self.assertLessEqual(len(derive_memory_query(task)), 800)

    def test_private_and_noisy_fields_never_enter_query(self):
        task = {
            "projectSlug": "project-factory", "text": "Inspect publisher",
            "comments": [{"text": "secret-comment"}],
            "proofs": [{"url": "file:///secret"}],
            "providerTranscript": "hidden",
        }
        query = derive_memory_query(task)
        self.assertEqual(query, "Inspect publisher")
        self.assertNotIn("secret", query)

    def test_eligibility_excludes_other_projects_and_baselines(self):
        self.assertEqual(memory_eligibility({"projectSlug": "other"}), "project_denied")
        baseline = {"projectSlug": "project-factory", "test": True,
                    "experiment": {"memory_comparison": {"arm": "baseline"}}}
        self.assertEqual(memory_eligibility(baseline), "comparison_baseline")
```

- [ ] **Step 2: Run the test and confirm the missing module failure**

Run: `python verify/test_automatic_memory_query.py`

Expected: `ModuleNotFoundError: No module named 'automatic_memory'`.

- [ ] **Step 3: Implement the minimal pure contract**

```python
QUERY_MAX_CHARS = 800

def _clean(value):
    return " ".join(str(value or "").split())

def derive_memory_query(task, max_chars=QUERY_MAX_CHARS):
    fragments = []
    for value in (task.get("text"), task.get("doneCondition"),
                  task.get("contextQuestion")):
        clean = _clean(value)
        if clean and clean.casefold() not in {
            prior.casefold() for prior in fragments
        }:
            fragments.append(clean)
    return " | ".join(fragments)[:max_chars].rstrip(" |")

def memory_eligibility(task):
    if task.get("projectSlug") != "project-factory":
        return "project_denied"
    marker = (task.get("experiment") or {}).get("memory_comparison") or {}
    if task.get("test") is True and marker.get("arm") == "baseline":
        return "comparison_baseline"
    if not derive_memory_query(task):
        return "empty_query"
    return "eligible"
```

- [ ] **Step 4: Run and register the focused test**

Run: `python verify/test_automatic_memory_query.py`

Expected: all tests pass. Add the same command to `verify/run-suite.sh`.

- [ ] **Step 5: Commit**

```bash
git add bin/automatic_memory.py verify/test_automatic_memory_query.py verify/run-suite.sh
git commit -m "feat: derive bounded automatic memory queries"
```

### Task 2: Explicit Runtime Modes and Atomic Rollback

**Files:**
- Modify: `bin/memory_canary.py`
- Modify: `bin/mp`
- Create: `verify/test_automatic_memory_control.py`
- Modify: `verify/test_memory_canary_control.py`
- Modify: `verify/run-suite.sh`

- [ ] **Step 1: Write failing migration and rollback tests**

```python
def test_legacy_enabled_control_migrates_to_manual_canary(self):
    self.write({"schemaVersion": 1, "enabled": True,
                "allowedProjects": ["project-factory"],
                "revision": 7, "updatedAt": 10})
    control = load_control(self.root)
    self.assertEqual(control["mode"], "manual_canary")
    self.assertEqual(control["revision"], 7)

def test_automatic_to_off_is_atomic_and_revisioned(self):
    automatic = set_control(self.root, mode="automatic", now=lambda: 20)
    disabled = set_control(self.root, mode="off", now=lambda: 21)
    self.assertEqual((automatic["mode"], disabled["mode"]), ("automatic", "off"))
    self.assertEqual(disabled["revision"], automatic["revision"] + 1)
    self.assertEqual((self.root / CONTROL_NAME).stat().st_mode & 0o777, 0o600)
```

- [ ] **Step 2: Verify the old boolean API fails these tests**

Run: `python verify/test_automatic_memory_control.py`

Expected: FAIL because `set_control()` does not accept `mode`.

- [ ] **Step 3: Replace the boolean public contract with a compatible mode record**

```python
ALLOWED_MODES = {"off", "automatic", "manual_canary"}
DEFAULT_CONTROL = {
    "schemaVersion": 2, "mode": "off",
    "allowedProjects": [ALLOWED_PROJECT], "revision": 1, "updatedAt": 0,
}

def _upgrade_control(value):
    if value.get("schemaVersion") == 1 and isinstance(value.get("enabled"), bool):
        return {
            "schemaVersion": 2,
            "mode": "manual_canary" if value["enabled"] else "off",
            "allowedProjects": value["allowedProjects"],
            "revision": value["revision"],
            "updatedAt": value["updatedAt"],
        }
    return value

def set_control(runtime_dir, *, mode, project=ALLOWED_PROJECT, now=time.time):
    if mode not in ALLOWED_MODES:
        raise MemoryCanaryError("memory_mode_invalid")
    current = load_control(runtime_dir)
    if current["mode"] == mode:
        return current
    return _atomic_write_control(runtime_dir, {
        **current, "mode": mode, "revision": current["revision"] + 1,
        "updatedAt": now(),
    })
```

Keep `set_memory_canary_control(..., enabled=...)` as a CLI compatibility shim mapping `True` to `manual_canary` and `False` to `off`. Add `mp memory mode {status,off,automatic,manual-canary}`; never restart Docker in this command.

- [ ] **Step 4: Run old and new control contracts**

Run: `python verify/test_automatic_memory_control.py && python verify/test_memory_canary_control.py`

Expected: both suites pass, including legacy migration.

- [ ] **Step 5: Commit**

```bash
git add bin/memory_canary.py bin/mp verify/test_automatic_memory_control.py verify/test_memory_canary_control.py verify/run-suite.sh
git commit -m "feat: add reversible memory runtime modes"
```

### Task 3: Four-Level Recovery Coordinator

**Files:**
- Create: `bin/memory_recovery.py`
- Create: `verify/test_memory_recovery.py`
- Modify: `verify/run-suite.sh`

- [ ] **Step 1: Write failing ordering, early-stop, timeout, and status tests**

```python
from memory_recovery import RecoveryLimits, recover

def claim(name):
    return {"id": name, "projectSlug": "project-factory", "content": name,
            "sourceUri": f"git://{name}", "sourceType": "commit"}

class MemoryRecoveryTests(unittest.TestCase):
    def test_fast_success_has_zero_later_cost(self):
        calls = []
        result = recover("query", {
            "fast": lambda q, n: calls.append("fast") or [claim("a")],
            "deep": lambda q, n: calls.append("deep") or [],
            "exhaustive": lambda q, n: calls.append("exhaustive") or [],
            "emergency": lambda q, n: calls.append("emergency") or [],
        }, sufficient=lambda rows: bool(rows))
        self.assertEqual(calls, ["fast"])
        self.assertEqual(result["selectedLevel"], "fast")
        self.assertEqual(result["status"], "memory_applied")

    def test_all_insufficient_returns_typed_empty_result(self):
        result = recover("query", {name: lambda q, n: []
            for name in ("fast", "deep", "exhaustive", "emergency")})
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertEqual(result["claims"], [])
        self.assertEqual(result["levelsAttempted"],
                         ["fast", "deep", "exhaustive", "emergency"])
```

- [ ] **Step 2: Run and confirm the coordinator is missing**

Run: `python verify/test_memory_recovery.py`

Expected: import failure for `memory_recovery`.

- [ ] **Step 3: Implement shared budgets and ordered recovery**

```python
@dataclass(frozen=True)
class RecoveryLimits:
    deadline_seconds: float = 2.0
    max_claims: int = 3
    max_estimated_tokens: int = 300
    exhaustive_examined: int = 100

def estimate_tokens(value):
    return (len(value.encode("utf-8")) + 3) // 4

def recover(query, adapters, *, limits=RecoveryLimits(),
            sufficient=lambda rows: bool(rows), clock=time.monotonic):
    started = clock()
    attempted = []
    for level in ("fast", "deep", "exhaustive", "emergency"):
        if clock() - started >= limits.deadline_seconds:
            return _outcome("memory_unavailable", attempted, [], started, clock,
                            reason="deadline_exceeded")
        attempted.append(level)
        try:
            rows = adapters[level](query, limits.max_claims)
        except (OSError, TimeoutError, ValueError):
            continue
        if sufficient(rows):
            claims = list(rows[:limits.max_claims])
            if estimate_tokens(json.dumps(claims, ensure_ascii=False)) > limits.max_estimated_tokens:
                return _outcome("memory_budget_exceeded", attempted, [], started, clock)
            return _outcome("memory_applied", attempted, claims, started, clock,
                            selected=level)
    return _outcome("insufficient_evidence", attempted, [], started, clock)
```

Define `_outcome()` with only `status`, `selectedLevel`, `levelsAttempted`, `claims`, `elapsedMilliseconds`, `examinedCount`, `returnedCount`, `estimatedTokens`, `provenanceComplete`, and `reasonCode`. Reject unknown adapter keys and malformed claims as `memory_invalid_response`.

- [ ] **Step 4: Run coordinator tests**

Run: `python verify/test_memory_recovery.py`

Expected: ordering, early-stop, deadline, budget, malformed response, and exception tests pass.

- [ ] **Step 5: Commit**

```bash
git add bin/memory_recovery.py verify/test_memory_recovery.py verify/run-suite.sh
git commit -m "feat: coordinate bounded memory recovery levels"
```

### Task 4: Exhaustive Search Over the Existing Store

**Files:**
- Create: `experiments/memory-gate-b/src/memory_bench/exhaustive.py`
- Modify: `experiments/memory-gate-b/src/memory_bench/taskspec_memory.py`
- Create: `experiments/memory-gate-b/tests/test_exhaustive_fallback.py`

- [ ] **Step 1: Write failing same-store and bounded-search tests**

```python
def test_refinements_search_same_events_and_preserve_provenance(fixture):
    search = BoundedExhaustiveSearch(fixture.events, fixture.aliases)
    outcome = search.retrieve(
        "exact recovery stale tmux",
        filters={"event_type": {"commit"}, "file": "bin/mp"},
        max_examined=100, limit=3,
    )
    self.assertLessEqual(outcome.examined_count, 100)
    self.assertLessEqual(len(outcome.results), 3)
    self.assertTrue(all(row.event.source_uri for row in outcome.results))

def test_no_persistent_corpus_or_second_index_is_created(fixture, tmp_path):
    before = set(tmp_path.iterdir())
    BoundedExhaustiveSearch(fixture.events, fixture.aliases).retrieve(
        "publisher approval", max_examined=20, limit=3)
    self.assertEqual(set(tmp_path.iterdir()), before)
```

- [ ] **Step 2: Run and verify the new search type is absent**

Run: `python experiments/memory-gate-b/tests/test_exhaustive_fallback.py`

Expected: FAIL importing `BoundedExhaustiveSearch`.

- [ ] **Step 3: Implement bounded successive refinements**

```python
@dataclass(frozen=True)
class ExhaustiveOutcome:
    results: tuple[RetrievalResult, ...]
    examined_count: int
    queries: tuple[str, ...]

class BoundedExhaustiveSearch:
    def __init__(self, events, aliases):
        self.events = tuple(events)
        self.aliases = dict(aliases)

    def retrieve(self, query, *, filters=None, max_examined=100, limit=3):
        refinements = _refinements(query, self.aliases)
        examined, ranked = 0, {}
        for refinement in refinements:
            for event in self.events:
                if examined >= max_examined:
                    break
                examined += 1
                if _matches(event, refinement, filters or {}):
                    ranked[event.event_id] = _result(event, refinement)
            if len(ranked) >= limit:
                break
        rows = tuple(sorted(ranked.values(),
                            key=lambda row: (-row.score, row.event.event_id))[:limit])
        return ExhaustiveOutcome(rows, examined, tuple(refinements))
```

Implement `_matches` for text/alias/regex plus temporal range, file, commit, task, agent, and event type fields already present on `MemoryEvent`. Regex must compile with a 256-character ceiling and invalid regex must produce no result, not an exception. Do not create a corpus file or SQLite database.

- [ ] **Step 4: Run focused retrieval and Gate A regressions**

Run: `python experiments/memory-gate-b/tests/test_exhaustive_fallback.py && python experiments/memory-gate-b/tests/test_taskspec_memory.py`

Expected: all tests pass and existing fast/deep results remain unchanged.

- [ ] **Step 5: Commit**

```bash
git add experiments/memory-gate-b/src/memory_bench/exhaustive.py experiments/memory-gate-b/src/memory_bench/taskspec_memory.py experiments/memory-gate-b/tests/test_exhaustive_fallback.py
git commit -m "feat: add bounded exhaustive memory fallback"
```

### Task 5: Read-Only Local Emergency Adapter

**Files:**
- Create: `bin/local_memory_emergency.py`
- Create: `verify/test_local_memory_emergency.py`
- Modify: `verify/run-suite.sh`

- [ ] **Step 1: Write failing lifecycle and safety tests**

```python
def test_temporary_view_is_private_bounded_and_removed(self):
    adapter = LocalEmergencyAdapter(self.dataset, self.runtime)
    rows = adapter.retrieve("publisher", limit=3, max_bytes=262144)
    self.assertLessEqual(len(rows), 3)
    self.assertEqual(list(self.runtime.glob("memory-view-*")), [])
    self.assertTrue(all(row["sourceUri"] for row in rows))

def test_dataset_is_never_mutated(self):
    before = sha256_tree(self.dataset)
    LocalEmergencyAdapter(self.dataset, self.runtime).retrieve("tmux", limit=3)
    self.assertEqual(sha256_tree(self.dataset), before)
```

- [ ] **Step 2: Verify the adapter is missing**

Run: `python verify/test_local_memory_emergency.py`

Expected: import failure for `local_memory_emergency`.

- [ ] **Step 3: Implement a locked, read-only adapter**

```python
class LocalEmergencyAdapter:
    def __init__(self, dataset_dir, runtime_dir):
        self.dataset = Path(dataset_dir).resolve()
        self.runtime = Path(runtime_dir).resolve()

    def retrieve(self, query, limit=3, max_bytes=262_144):
        _verify_dataset_lock(self.dataset)
        self.runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix="memory-view-", dir=self.runtime,
                                    text=True)
        path = Path(name)
        try:
            os.chmod(path, 0o600)
            rows = _bounded_event_scan(self.dataset / "events.jsonl",
                                       query, limit, max_bytes)
            os.write(fd, _diagnostic_metadata(rows).encode("utf-8"))
            return [_public_claim(row) for row in rows]
        finally:
            os.close(fd)
            path.unlink(missing_ok=True)
```

`_verify_dataset_lock()` must verify the committed manifest/dataset SHA before reading. `_bounded_event_scan()` stops at `max_bytes`; the temporary view contains only selected metadata, never the full event history.

- [ ] **Step 4: Run emergency and sanitation tests**

Run: `python verify/test_local_memory_emergency.py`

Expected: lifecycle, permissions, byte cap, SHA mismatch, malformed JSONL, and no-mutation tests pass.

- [ ] **Step 5: Commit**

```bash
git add bin/local_memory_emergency.py verify/test_local_memory_emergency.py verify/run-suite.sh
git commit -m "feat: add read-only local memory emergency access"
```

### Task 6: Automatic TaskSpec Integration and Typed Fail-Open

**Files:**
- Modify: `bin/project_context.py`
- Modify: `bin/mp`
- Create: `verify/test_automatic_memory_taskspec.py`
- Modify: `verify/test_task_project_fields.py`
- Modify: `verify/test_memory_canary_runtime.py`
- Modify: `verify/run-suite.sh`

- [ ] **Step 1: Write failing end-to-end compiler tests**

```python
def test_automatic_mode_injects_bounded_claims_without_explicit_question(self):
    task = project_factory_task(text="Repair publisher", contextQuestion="")
    spec, event = compile_owner_fixture(task, mode="automatic",
        recall=lambda query: applied_result(query, level="fast"))
    self.assertTrue(spec["memoryQuestion"].startswith("Repair publisher"))
    self.assertEqual(spec["memoryStatus"], "memory_applied")
    self.assertLessEqual(len(spec["memoryClaims"]), 3)
    self.assertLessEqual(event["estimatedTokens"], 300)

def test_memory_transport_failure_does_not_block_taskspec(self):
    spec, event = compile_owner_fixture(project_factory_task(), mode="automatic",
        recall=lambda query: (_ for _ in ()).throw(OSError("down")))
    self.assertEqual(spec["memoryClaims"], [])
    self.assertEqual(spec["memoryStatus"], "memory_unavailable")
    self.assertEqual(event["memoryStatus"], "memory_unavailable")

def test_baseline_and_off_mode_never_call_recall(self):
    forbidden = lambda query: self.fail("recall must not run")
    self.assertEqual(compile_baseline(recall=forbidden)["memoryStatus"], "not_requested")
    self.assertEqual(compile_off(recall=forbidden)["memoryStatus"], "not_requested")
```

- [ ] **Step 2: Verify current compiler fails closed**

Run: `python verify/test_automatic_memory_taskspec.py`

Expected: FAIL because a gateway error raises `TaskSpecError` and cards without `contextQuestion` do not recall.

- [ ] **Step 3: Integrate query, mode, coordinator, and typed results**

```python
def compile_task_spec(task, profile, recall=None, now=None, *,
                      memory_query=None, memory_mode="off"):
    question = memory_query if memory_mode == "automatic" else _clean_question(task)
    result = TaskSpecDocument({...,
        "memoryQuestion": question,
        "memoryClaims": [],
        "memoryStatus": "not_requested",
    })
    if memory_mode == "off" or not question or not profile["memory"]["enabled"]:
        return result
    try:
        response = recall(question) if recall else call_memory_gateway(
            profile, question, max_chars=remaining)
        return _apply_memory_response(result, response, profile, limit)
    except (MemoryError, OSError, TimeoutError, ValueError) as error:
        result["memoryStatus"] = _public_failure_status(error)
        result.memory_metadata = _empty_memory_metadata(result["memoryStatus"])
        return result
```

In `compile_owner_task_spec`, load the mode once, call `memory_eligibility(task)`, derive the query only for `automatic`, preserve `compile_memory_canary_attempt()` only for `manual_canary`, and preserve the comparison baseline bypass. TaskSpec write failures remain fail-closed; only memory recovery failures become fail-open.

- [ ] **Step 4: Run compiler, canary, project, routing, and persistence regressions**

Run: `python verify/test_automatic_memory_taskspec.py && python verify/test_memory_canary_runtime.py && python verify/test_task_project_fields.py`

Expected: all pass; automatic mode performs one recall per compilation, manual canary remains explicit, and existing ownership/routing fields are unchanged.

- [ ] **Step 5: Commit**

```bash
git add bin/project_context.py bin/mp verify/test_automatic_memory_taskspec.py verify/test_task_project_fields.py verify/test_memory_canary_runtime.py verify/run-suite.sh
git commit -m "feat: apply automatic memory with typed fail-open"
```

### Task 7: Sidecar Protocol, Launcher, Receipts, and HUD

**Files:**
- Modify: `experiments/memory-gate-b/docker/live-canary-entrypoint.sh`
- Modify: `experiments/memory-gate-b/docker/compose.live-canary.yml`
- Modify: `windows/Start-MyPeopleMemoryCanary.ps1`
- Modify: `bin/todo-server.py`
- Modify: `bin/dashboard.html`
- Modify: `bin/todos.html`
- Create: `verify/test_automatic_memory_observability.py`
- Modify: `verify/test_memory_canary_sidecar.py`
- Modify: `verify/test_windows_memory_canary.py`
- Modify: `verify/test_memory_canary_telemetry.py`
- Modify: `verify/test_memory_canary_priorities.py`

- [ ] **Step 1: Write failing protocol, rollback, and redaction tests**

```python
def test_public_projection_has_bounded_metadata_only(self):
    projection = get_memory_projection("task-1")
    self.assertEqual(projection["mode"], "automatic")
    self.assertIn(projection["last"]["status"], PUBLIC_MEMORY_STATUSES)
    self.assertNotIn("query", json.dumps(projection))
    self.assertNotIn("claims", json.dumps(projection))
    self.assertNotIn("credential", json.dumps(projection).lower())

def test_hud_renders_mode_level_latency_and_token_state(self):
    page = pathlib.Path("bin/dashboard.html").read_text(encoding="utf-8")
    for label in ("Memory mode", "Recall level", "Latency", "Memory tokens"):
        self.assertIn(label, page)
```

Add PowerShell contract assertions that `-Action Enable -Mode Automatic` writes automatic mode, `-Action Disable` changes it to off before deleting ephemeral credentials, and neither action recreates the main container.

- [ ] **Step 2: Run UI, sidecar, and launcher tests**

Run: `python verify/test_automatic_memory_observability.py && python verify/test_memory_canary_sidecar.py && python verify/test_windows_memory_canary.py`

Expected: FAIL because the projection and automatic launcher mode do not exist.

- [ ] **Step 3: Extend the sidecar response and safe receipt schema**

```json
{
  "ok": true,
  "status": "memory_applied",
  "selectedLevel": "deep",
  "levelsAttempted": ["fast", "deep"],
  "claims": [],
  "elapsedMilliseconds": 7,
  "examinedCount": 12,
  "returnedCount": 3,
  "estimatedTokens": 236,
  "provenanceComplete": true,
  "aiUsage": "not_measured"
}
```

The sidecar imports the existing fixture once, builds the existing FTS/deep retrievers, adds `BoundedExhaustiveSearch`, and exposes the same-store adapters to `recover()`. The API receipt stores task ID, project, profile/control revisions, status, level, attempted levels, counts, latency, estimated tokens, provenance boolean, and reason code only.

- [ ] **Step 4: Add Scorpion-theme observability without a second control plane**

Render a compact Memory panel in `dashboard.html` from `/todo/memory-canary`: yellow mode badge, green/amber/red health dot, selected level, last latency, injected claim count, estimated memory tokens, and provider tokens as either measured values or `not measured`. In `todos.html`, show only the task-level status strip. Browser code must not infer health or expose raw query/claim text.

- [ ] **Step 5: Run all focused observability tests**

Run: `python verify/test_automatic_memory_observability.py && python verify/test_memory_canary_sidecar.py && python verify/test_windows_memory_canary.py && python verify/test_memory_canary_telemetry.py && python verify/test_memory_canary_priorities.py`

Expected: all pass, including redaction and no-restart rollback.

- [ ] **Step 6: Commit**

```bash
git add experiments/memory-gate-b/docker/live-canary-entrypoint.sh experiments/memory-gate-b/docker/compose.live-canary.yml windows/Start-MyPeopleMemoryCanary.ps1 bin/todo-server.py bin/dashboard.html bin/todos.html verify/test_automatic_memory_observability.py verify/test_memory_canary_sidecar.py verify/test_windows_memory_canary.py verify/test_memory_canary_telemetry.py verify/test_memory_canary_priorities.py
git commit -m "feat: expose automatic memory health and controls"
```

### Task 8: Documentation, Disposable Docker Gate, and Live-Deployment Decision

**Files:**
- Modify: `experiments/memory-gate-b/README.md`
- Modify: `docs/USER-MANUAL.md`
- Modify: `verify/run-suite.sh`
- Create: `verify/test_automatic_memory_e2e.py`

- [ ] **Step 1: Write the failing integrated acceptance test**

```python
def test_automatic_recall_and_rollback_survive_restart(self):
    card = create_project_factory_card("Explain exact session recovery")
    first = compile_owner(card)
    self.assertEqual(first["memoryStatus"], "memory_applied")
    restart_todo_server_only()
    self.assertEqual(load_card(card)["id"], card)
    set_memory_mode("off")
    second = compile_owner(card)
    self.assertEqual(second["memoryStatus"], "not_requested")
    self.assertEqual(load_card(card)["id"], card)
```

The fixture must also force: fast success, deep success, exhaustive success, emergency success, insufficient evidence, timeout, invalid response, and budget exceeded. It must assert zero later-level calls after early success and complete provenance for every applied claim.

- [ ] **Step 2: Run the E2E test before wiring it into the suite**

Run: `python verify/test_automatic_memory_e2e.py`

Expected: FAIL until the disposable fixture exposes automatic mode and all four adapters.

- [ ] **Step 3: Document exact operations and boundaries**

Document these commands in English:

```powershell
.\windows\Start-MyPeopleMemoryCanary.ps1 -Action Enable -Mode Automatic
docker exec mypeople mp memory mode status
docker exec mypeople mp memory mode off
.\windows\Start-MyPeopleMemoryCanary.ps1 -Action Disable
```

State explicitly: Project Factory only; no automatic writes; no Cloudflare; no `memory-dump.py`; no board corpus; three claims; 300 estimated tokens; two-second total deadline; provider usage is `not measured` unless exposed; `off` applies to the next TaskSpec without restarting Docker.

- [ ] **Step 4: Run the complete local verification**

Run: `python verify/test_automatic_memory_e2e.py`

Run: `bash verify/run-suite.sh`

Expected: focused automatic-memory tests pass and the full J1–J52 contract suite is green.

- [ ] **Step 5: Build and verify a disposable Docker candidate**

Run:

```powershell
docker build -t mypeople-node:auto-memory-candidate .
powershell -NoProfile -ExecutionPolicy Bypass -File .\verify\Invoke-IsolatedVerify.ps1 -Image mypeople-node:auto-memory-candidate -TimeoutSeconds 1800 -UsePackagedSource
```

Expected: Priorities, HUD, browser journeys, provider-session recovery, routing, persistence, Gate B regressions, and J1–J52 pass in the isolated clone; the live `mypeople` container is unchanged.

- [ ] **Step 6: Perform final safety checks**

Run:

```bash
git diff --check
rg -n "memory-dump|board-corpus|token_invalidated|tskey-|sk-[A-Za-z0-9]" bin experiments windows docs verify
git status --short
```

Expected: no whitespace errors, no new corpus implementation, no credentials, and only intentional files changed.

- [ ] **Step 7: Commit the verified candidate**

```bash
git add experiments/memory-gate-b/README.md docs/USER-MANUAL.md verify/run-suite.sh verify/test_automatic_memory_e2e.py
git commit -m "docs: operationalize bounded automatic memory"
```

- [ ] **Step 8: Stop at the live gate**

Present commits, exact test counts, isolated image digest, measured recall latency/context size, and rollback evidence. Do not merge, push, deploy, or enable automatic mode in the live container until Rafa explicitly approves that transaction.

## Final Acceptance Matrix

- Query generation is deterministic and makes zero provider calls: Task 1.
- `off`, `automatic`, and `manual_canary` are atomic and reversible: Task 2.
- Fast/deep/exhaustive/emergency order, early stop, deadline, and typed outcomes: Task 3.
- Exhaustive search uses the existing events with no corpus or duplicate index: Task 4.
- Emergency access is read-only, SHA-locked, private, bounded, and self-cleaning: Task 5.
- Automatic TaskSpec recall is Project Factory-only and memory failures fail open: Task 6.
- Receipts/API/HUD contain bounded metadata and no sensitive payloads: Task 7.
- Full isolated Docker, browser, routing, persistence, provider-session, Gate B, and J1–J52 regression evidence: Task 8.
