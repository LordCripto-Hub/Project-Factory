# HUD Core Agent Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe Kill, Revive, Apply model, and Relaunch controls to the Boss and Nightwatch HUD cards only.

**Architecture:** A focused `core_agent_controls.py` module owns allowlists, validation, per-agent locking, fixed `mp` invocation, sanitization, and roster-confirmed success. The queue server exposes authenticated capabilities and action endpoints; the existing todo proxy forwards them. The dashboard renders a compact Scorpion `COMMAND` strip from server capabilities and never accepts free-form commands or models.

**Tech Stack:** Python 3 standard library, ThreadingHTTPServer, existing `mp` CLI, vanilla HTML/CSS/JavaScript, unittest, Playwright, Docker.

---

### Task 1: Define the closed core-control domain

**Files:**
- Create: `bin/core_agent_controls.py`
- Create: `verify/test_core_agent_controls.py`
- Modify: `verify/run-suite.sh`

- [ ] **Step 1: Write failing domain tests**

Create tests that import the module and assert the exact public contract:

```python
def test_capabilities_are_closed_and_ordered(self):
    self.assertEqual(
        controls.capabilities(),
        {
            "agents": [
                "node-1/main:Boss",
                "node-1/nightwatch:Nightwatch",
            ],
            "models": ["gpt-5.6-sol", "gpt-5.6-luna"],
        },
    )

def test_rejects_engineer_and_free_form_model(self):
    with self.assertRaisesRegex(controls.ControlError, "unsupported_agent"):
        controls.build_command("kill", {"agent_id": "node-1/main:eng-1"}, self.roster)
    with self.assertRaisesRegex(controls.ControlError, "unsupported_model"):
        controls.build_command(
            "switch",
            {"agent_id": "node-1/main:Boss", "model": "custom-model"},
            self.roster,
        )

def test_commands_are_fixed_argument_vectors(self):
    self.assertEqual(
        controls.build_command(
            "switch",
            {"agent_id": "node-1/main:Boss", "model": "gpt-5.6-luna"},
            self.roster,
        ),
        ["/home/mp/mypeople/bin/mp", "switch", "node-1/main:Boss",
         "--backend", "codex", "--model", "gpt-5.6-luna"],
    )
```

Also cover duplicate/missing roster rows, backend mismatch, alive/dead compatibility, bounded model strings, and an unsupported action.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
python verify/test_core_agent_controls.py
```

Expected: FAIL because `core_agent_controls` does not exist.

- [ ] **Step 3: Implement validation and command construction**

Create constants and typed errors:

```python
CORE_AGENT_IDS = (
    "node-1/main:Boss",
    "node-1/nightwatch:Nightwatch",
)
MODEL_ALLOWLIST = ("gpt-5.6-sol", "gpt-5.6-luna")
MP_PATH = os.path.join(ROOT, "bin", "mp")

class ControlError(Exception):
    def __init__(self, code, status=400):
        super().__init__(code)
        self.code = code
        self.status = status
```

Implement `capabilities()`, exact one-row lookup, backend/state validation, and `build_command()`. Return argument arrays only. Never use `shell=True`.

- [ ] **Step 4: Implement locked execution and roster confirmation**

Implement `execute(action, body, roster_path, runner=subprocess.run)` with:

```python
with agent_operation(agent_id):
    before = load_exact_roster_record(roster_path, agent_id)
    command = build_command(action, body, [before])
    completed = runner(
        command,
        capture_output=True,
        text=True,
        timeout=90,
        shell=False,
    )
    if completed.returncode:
        raise ControlError("control_failed", 409)
    after = load_exact_roster_record(roster_path, agent_id)
    confirm_result(action, body, after)
    return {
        "ok": True,
        "agent_id": agent_id,
        "state": after.get("state", "unknown"),
        "model": after.get("model", ""),
    }
```

Use a module lock plus a set of active agent IDs. Concurrent operations for the same agent raise `operation_in_progress` with HTTP 409. Confirmation requires:

- kill: dead and retired;
- revive: alive with the prior model;
- switch/relaunch: alive with the requested model.

Do not include stdout, stderr, session IDs, profile paths, or command arguments in responses.

- [ ] **Step 5: Run focused tests and register the suite**

Run:

```powershell
python verify/test_core_agent_controls.py
```

Expected: all tests PASS.

Add exactly one `python3 "$ROOT/verify/test_core_agent_controls.py"` entry to `verify/run-suite.sh`.

- [ ] **Step 6: Commit**

```powershell
git add bin/core_agent_controls.py verify/test_core_agent_controls.py verify/run-suite.sh
git commit -m "feat: add closed core agent control domain"
```

### Task 2: Expose authenticated server operations

**Files:**
- Modify: `bin/queue-server.py`
- Modify: `bin/todo-server.py`
- Create: `verify/test_core_agent_control_routes.py`

- [ ] **Step 1: Write failing route tests**

Test source and handler behavior for:

```python
def test_capabilities_and_actions_require_existing_auth(self):
    self.assertIn('if path=="/control-capabilities"', self.queue_source)
    self.assertIn('if path in ("/kill","/revive","/switch")', self.queue_source)
    self.assertLess(
        self.queue_source.index("if not self.authed()"),
        self.queue_source.index('if path=="/control-capabilities"'),
    )

def test_todo_proxy_forwards_only_fixed_control_routes(self):
    for route in ('"/control-capabilities"', '"/kill"', '"/revive"', '"/switch"'):
        self.assertIn(route, self.todo_source)
    self.assertNotIn('"/command"', self.todo_source)
```

Exercise a handler fixture or extracted dispatcher and verify a crafted engineer request returns `unsupported_agent`, an invalid model returns `unsupported_model`, and no provider output reaches JSON.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
python verify/test_core_agent_control_routes.py
```

Expected: FAIL because the capabilities, kill, and switch routes do not exist.

- [ ] **Step 3: Add queue-server routes**

Import `core_agent_controls`. In authenticated GET handling, return:

```python
if path == "/control-capabilities":
    return self.json(core_agent_controls.capabilities(), head=head)
```

In authenticated POST handling, replace the ad-hoc revive subprocess with:

```python
if path in ("/kill", "/revive", "/switch"):
    action = path[1:]
    try:
        result = core_agent_controls.execute(
            action,
            body,
            os.path.join(ROOT, "run", "roster.json"),
        )
        return self.json(result)
    except core_agent_controls.ControlError as error:
        return self.json(
            {"ok": False, "error": error.code},
            error.status,
        )
```

The generic unexpected-exception response is `{"ok": false, "error": "control_unavailable"}` with HTTP 500 and no exception text.

- [ ] **Step 4: Extend the exact todo proxy allowlist**

Forward GET `/control-capabilities` and POST `/kill`, `/revive`, and `/switch` through the existing authenticated HUD proxy. Do not add wildcard control routing.

- [ ] **Step 5: Run route and regression tests**

Run:

```powershell
python verify/test_core_agent_control_routes.py
python verify/test_exact_session_recovery.py
python verify/test_provider_session.py
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```powershell
git add bin/queue-server.py bin/todo-server.py verify/test_core_agent_control_routes.py
git commit -m "feat: expose authenticated core agent controls"
```

### Task 3: Add the Scorpion COMMAND strip

**Files:**
- Modify: `bin/dashboard.html`
- Create: `verify/test_hud_core_agent_controls.py`
- Modify: `verify/browser_journeys.js`
- Modify: `verify/run-suite.sh`

- [ ] **Step 1: Write failing HUD contracts**

Assert the source contains:

```python
def test_only_core_agents_receive_command_strip(self):
    self.assertIn("function isCoreControlled(row)", self.source)
    self.assertIn("function addCommandStrip(card,row)", self.source)
    self.assertIn("controlCapabilities.agents", self.source)

def test_kill_is_armed_for_five_seconds(self):
    self.assertIn("Confirm kill", self.source)
    self.assertIn("5000", self.source)
    self.assertIn("event.stopPropagation()", self.source)

def test_model_input_is_closed(self):
    self.assertIn("controlCapabilities.models", self.source)
    self.assertNotIn('type="text"', self.command_block)
```

Also assert operation buttons use only `/kill`, `/revive`, and `/switch`; failures stay visible; no optimistic model assignment exists; and stale telemetry still renders controls from fresh roster state.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
python verify/test_hud_core_agent_controls.py
```

Expected: FAIL because the command strip is absent.

- [ ] **Step 3: Add focused Scorpion styles**

Add `.command-strip`, `.command-label`, `.command-model`, `.command-status`, and `.card-action.armed` using existing `--gold`, `--danger`, `--success`, and border tokens. Preserve current card dimensions and mobile grid.

- [ ] **Step 4: Fetch server capabilities and render core controls**

Initialize:

```javascript
let controlCapabilities={agents:[],models:[]};
const coreOperationState=new Map();

function isCoreControlled(row){
  return controlCapabilities.agents.includes(row.agent_id);
}
```

Fetch `/control-capabilities` with `/agents` and `/roster`. If capabilities fail, render no mutation controls and expose `controls unavailable`; do not use a client-side fallback allowlist.

Build a native `select` exclusively from `controlCapabilities.models`. Choose the roster model when present. Add the strip only when `isCoreControlled(row)` is true.

- [ ] **Step 5: Implement non-bubbling actions and honest status**

Implement a common JSON action helper. Kill arming changes only button text/class and expires after 5,000 ms. The second click calls `/kill`. Alive model changes call `/switch`; stopped model relaunch also calls `/switch`; current-model revive calls `/revive`.

Disable the strip during requests. After the request, call `poll()` and verify the fresh row before showing success. On failure, retain the server error code in bounded text and do not change displayed state/model.

- [ ] **Step 6: Add real browser assertions**

Extend the disposable HUD fixture to verify:

- engineer card has no `COMMAND` strip;
- Boss and Nightwatch each have one;
- first Kill click opens no popup and sends no request;
- Kill disarms after the synthetic timer boundary;
- selecting Luna/Sol and pressing Apply sends the exact structured body;
- nested controls do not trigger Attach;
- a synthetic server failure remains visible;
- stale telemetry preserves the strips.

Use route interception for mutation requests so browser verification never kills the disposable fixture's core agents.

- [ ] **Step 7: Run focused and browser tests**

Run:

```powershell
python verify/test_hud_provider_telemetry.py
python verify/test_hud_unified_agent_cards.py
python verify/test_hud_core_agent_controls.py
node --check verify/browser_journeys.js
```

Expected: all tests PASS.

Register `test_hud_core_agent_controls.py` exactly once in `verify/run-suite.sh`.

- [ ] **Step 8: Commit**

```powershell
git add bin/dashboard.html verify/test_hud_core_agent_controls.py verify/browser_journeys.js verify/run-suite.sh
git commit -m "feat: add HUD controls for core agents"
```

### Task 4: Documentation and complete verification

**Files:**
- Modify: `docs/USER-MANUAL.md`
- Modify: `verify/test_public_repository.py`

- [ ] **Step 1: Write failing documentation contract**

Require the public manual to state:

- controls exist only for Boss and Nightwatch;
- the model selector is server allowlisted;
- Kill requires two clicks within five seconds;
- Apply/Relaunch preserves the existing exact-session and fail-closed semantics;
- engineers remain Boss-controlled through CLI/terminal.

Run:

```powershell
python verify/test_public_repository.py
```

Expected: FAIL until the manual is updated.

- [ ] **Step 2: Update the English operator manual**

Add a `HUD core-agent controls` subsection near `Revive semantics`. Do not include personal names, credentials, private paths, or provider output.

- [ ] **Step 3: Run all focused contracts**

Run:

```powershell
python verify/test_core_agent_controls.py
python verify/test_core_agent_control_routes.py
python verify/test_hud_provider_telemetry.py
python verify/test_hud_unified_agent_cards.py
python verify/test_hud_core_agent_controls.py
python verify/test_public_repository.py
python verify/test_exact_session_recovery.py
python verify/test_provider_session.py
git diff --check
```

Expected: all tests PASS and no whitespace errors.

- [ ] **Step 4: Commit documentation**

```powershell
git add docs/USER-MANUAL.md verify/test_public_repository.py
git commit -m "docs: document HUD core agent controls"
```

- [ ] **Step 5: Build the candidate image**

Use the current live image as immutable base:

```powershell
$base = docker inspect mypeople --format '{{.Config.Image}}'
docker build -f docker/Dockerfile.runtime-image --build-arg BASE_IMAGE=$base -t mypeople-node:hud-core-agent-controls .
```

Expected: build succeeds and produces a new image ID.

- [ ] **Step 6: Run packaged-source disposable verification**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\verify\Invoke-IsolatedVerify.ps1 -Image mypeople-node:hud-core-agent-controls -TimeoutSeconds 1800 -UsePackagedSource
```

Expected: `Isolated MyPeople verification passed.`

- [ ] **Step 7: Present the deployment gate**

Report branch, commit, tree SHA, image ID, focused-test totals, browser result, and full Docker result. Do not merge, push, operate live controls, or deploy until the operator explicitly approves.

