# Provider Session Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add secure global and per-agent provider profiles, transactional Codex account switching, explicit context handoffs, ordered role revival, and automatic rollback.

**Architecture:** Provider-neutral profile metadata and bindings live outside Git on the Windows host and are mirrored into runtime state. Codex processes receive a profile-specific `CODEX_HOME`; a host-side PowerShell orchestrator coordinates secure credential copying while a Python runtime helper owns locks, handoffs, roster snapshots, stopping, revival, and rollback.

**Tech Stack:** Python 3 standard library, PowerShell 5.1+, Docker CLI, tmux, Codex CLI, JSON, Python `unittest`

---

## File map

- Create `bin/provider_profiles.py`: validation, profile resolution, model resolution, and safe runtime paths.
- Create `bin/provider-session`: runtime transaction state machine, handoff capture, stopping, revival, verification, and rollback.
- Modify `bin/mp`: resolve effective profile and set `CODEX_HOME` for Codex processes.
- Modify `bin/boss-supervisor.sh`: respect the provider-switch lock.
- Create `windows/MyPeople.ProviderProfiles.psm1`: protected host profile store and Docker transport helpers.
- Create `windows/Save-MyPeopleProviderProfile.ps1`: import a current provider login.
- Create `windows/Switch-MyPeopleProviderProfile.ps1`: global or per-agent transactional switch.
- Create `windows/Get-MyPeopleProviderStatus.ps1`: non-secret profile and binding status.
- Modify `windows/Start-MyPeople.ps1`: rehydrate and validate the active profile before agent revival.
- Create `verify/test_provider_profiles.py`: profile and binding unit contracts.
- Create `verify/test_provider_session.py`: transaction, handoff, ordering, and rollback contracts.
- Create `verify/test_windows_provider_profiles.py`: static PowerShell security and command contracts.
- Modify `verify/test_codex_boss_switch.py`: assert `CODEX_HOME` propagation.
- Modify `verify/verify.sh`: include provider-session tests.
- Modify `docs/USER-MANUAL.md`: English operator commands and recovery steps.

### Task 1: Implement provider profile and binding resolution

**Files:**
- Create: `bin/provider_profiles.py`
- Create: `verify/test_provider_profiles.py`

- [ ] **Step 1: Write the failing unit contract**

Create `verify/test_provider_profiles.py`:

```python
#!/usr/bin/env python3
from pathlib import Path
import importlib.util
import json
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("provider_profiles", ROOT / "bin" / "provider_profiles.py")
provider_profiles = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(provider_profiles)

class ProviderProfileContract(unittest.TestCase):
    def test_profile_id_rejects_path_and_shell_characters(self):
        for value in ("../bad", "bad/name", "bad name", "bad;name", ""):
            with self.assertRaises(ValueError):
                provider_profiles.validate_profile_id(value)
        self.assertEqual(provider_profiles.validate_profile_id("codex-primary"), "codex-primary")

    def test_agent_override_precedes_global_binding(self):
        bindings = {
            "globalProfile": "codex-primary",
            "agentProfiles": {"node-1/main:Engineer-1": "codex-secondary"},
        }
        self.assertEqual(provider_profiles.resolve_profile(bindings, "node-1/main:Boss"), "codex-primary")
        self.assertEqual(provider_profiles.resolve_profile(bindings, "node-1/main:Engineer-1"), "codex-secondary")

    def test_role_model_resolution_is_deterministic(self):
        profile = {
            "defaultModel": "gpt-5.6-luna",
            "roleModels": {"boss": "gpt-5.6-sol"},
        }
        self.assertEqual(provider_profiles.resolve_model(profile, "boss"), "gpt-5.6-sol")
        self.assertEqual(provider_profiles.resolve_model(profile, "engineer"), "gpt-5.6-luna")

    def test_codex_home_stays_inside_runtime_root(self):
        path = provider_profiles.codex_home("/runtime/provider-homes", "codex-primary")
        self.assertEqual(path, "/runtime/provider-homes/codex/codex-primary")

if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run the test and observe the expected failure**

```powershell
docker cp verify/test_provider_profiles.py mypeople:/home/mp/mypeople/verify/test_provider_profiles.py
docker exec mypeople python3 /home/mp/mypeople/verify/test_provider_profiles.py
```

Expected: ERROR because `bin/provider_profiles.py` does not exist.

- [ ] **Step 3: Implement the minimal resolver**

Create `bin/provider_profiles.py` with these public functions:

```python
#!/usr/bin/env python3
from __future__ import annotations
import json
import os
import re

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

def validate_profile_id(value: str) -> str:
    value = str(value or "")
    if not SAFE_ID.fullmatch(value):
        raise ValueError("invalid provider profile id")
    return value

def load_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default

def resolve_profile(bindings: dict, agent_id: str) -> str:
    selected = (bindings.get("agentProfiles") or {}).get(agent_id) or bindings.get("globalProfile")
    return validate_profile_id(selected)

def resolve_model(profile: dict, role: str) -> str:
    model = (profile.get("roleModels") or {}).get(role) or profile.get("defaultModel")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("provider profile has no model for role")
    return model.strip()

def codex_home(runtime_root: str, profile_id: str) -> str:
    root = os.path.realpath(runtime_root)
    path = os.path.realpath(os.path.join(root, "codex", validate_profile_id(profile_id)))
    if not path.startswith(root + os.sep):
        raise ValueError("provider home escapes runtime root")
    return path
```

- [ ] **Step 4: Run the unit contract**

Run the Step 2 command again.

Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```powershell
git add bin/provider_profiles.py verify/test_provider_profiles.py
git commit -m "Add provider profile resolution"
```

### Task 2: Propagate effective profiles into agent launches

**Files:**
- Modify: `bin/mp`
- Modify: `verify/test_codex_boss_switch.py`

- [ ] **Step 1: Add a failing launch-environment test**

Extend `verify/test_codex_boss_switch.py` so a Codex launch with
`PROVIDER_BINDINGS_PATH`, `PROVIDER_PROFILES_PATH`, and
`PROVIDER_HOMES_DIR` resolves `codex-primary` and asserts:

```python
self.assertEqual(launch_env["CODEX_HOME"], "/runtime/provider-homes/codex/codex-primary")
self.assertEqual(record["provider_profile"], "codex-primary")
```

- [ ] **Step 2: Run the focused test and observe failure**

```powershell
docker cp verify/test_codex_boss_switch.py mypeople:/home/mp/mypeople/verify/test_codex_boss_switch.py
docker exec -e PYTHONPATH=/home/mp/mypeople/bin mypeople python3 /home/mp/mypeople/verify/test_codex_boss_switch.py
```

Expected: FAIL because `CODEX_HOME` and `provider_profile` are absent.

- [ ] **Step 3: Resolve the profile in `mp spawn`**

Import `load_json`, `resolve_profile`, `resolve_model`, and `codex_home`.
For Codex only:

```python
bindings = load_json(os.environ.get("PROVIDER_BINDINGS_PATH", os.path.join(ROOT, "run", "provider-bindings.json")), {})
profiles = load_json(os.environ.get("PROVIDER_PROFILES_PATH", os.path.join(ROOT, "run", "provider-profiles.json")), {})
profile_id = resolve_profile(bindings, aid) if bindings.get("globalProfile") else ""
profile = profiles.get(profile_id, {}) if isinstance(profiles, dict) else {}
if profile_id:
    launch_env["CODEX_HOME"] = codex_home(
        os.environ.get("PROVIDER_HOMES_DIR", os.path.join(ROOT, "run", "provider-homes")),
        profile_id,
    )
    rec["provider_profile"] = profile_id
    if not ns.model:
        args_role = "boss" if ns.master else "nightwatch" if tab == "Nightwatch" else "engineer"
        rec["model"] = resolve_model(profile, args_role)
```

Create the resolved `CODEX_HOME` directory with mode `0700` before launch.

- [ ] **Step 4: Run Codex switch, doctrine, and worker tests**

```powershell
docker exec -e PYTHONPATH=/home/mp/mypeople/bin mypeople python3 /home/mp/mypeople/verify/test_codex_boss_switch.py
docker exec -e PYTHONPATH=/home/mp/mypeople/bin mypeople python3 /home/mp/mypeople/verify/test_codex_boss_doctrine.py
docker exec -e PYTHONPATH=/home/mp/mypeople/bin mypeople python3 /home/mp/mypeople/verify/test_worker_handoff.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add bin/mp verify/test_codex_boss_switch.py
git commit -m "Launch Codex agents with provider profiles"
```

### Task 3: Add switch locks, roster snapshots, and bounded handoffs

**Files:**
- Create: `bin/provider-session`
- Create: `verify/test_provider_session.py`
- Modify: `bin/boss-supervisor.sh`

- [ ] **Step 1: Write failing transaction contracts**

Create `verify/test_provider_session.py` with temporary runtime paths and tests
for these public functions:

```python
def test_handoff_is_bounded_and_redacts_secrets(self):
    handoff = module.build_handoff(
        {"agent_id": "node-1/main:Boss", "summary": "working"},
        "token " + "tskey" + "-auth-example\n" + ("x" * 20000),
        limit=4000,
    )
    self.assertNotIn("tskey" + "-auth-example", json.dumps(handoff))
    self.assertLessEqual(len(handoff["terminalTail"]), 4000)

def test_lock_rejects_concurrent_switches(self):
    module.acquire_lock(self.lock, "tx-one")
    with self.assertRaises(module.SwitchBusy):
        module.acquire_lock(self.lock, "tx-two")

def test_revival_order_is_boss_nightwatch_then_workers(self):
    roster = [
        {"agent_id": "node-1/main:Engineer-1", "lifecycle": "owner"},
        {"agent_id": "node-1/nightwatch:Nightwatch"},
        {"agent_id": "node-1/main:Boss", "is_master": True},
    ]
    self.assertEqual(
        [row["agent_id"] for row in module.revival_order(roster)],
        ["node-1/main:Boss", "node-1/nightwatch:Nightwatch", "node-1/main:Engineer-1"],
    )
```

- [ ] **Step 2: Run the test and observe failure**

```powershell
docker cp verify/test_provider_session.py mypeople:/home/mp/mypeople/verify/test_provider_session.py
docker exec -e PYTHONPATH=/home/mp/mypeople/bin mypeople python3 /home/mp/mypeople/verify/test_provider_session.py
```

Expected: ERROR because `bin/provider-session` does not exist.

- [ ] **Step 3: Implement the runtime transaction helper**

`bin/provider-session` must expose the following signatures. Implement them
with the concrete behaviors immediately below rather than stubs:

```python
class SwitchBusy(RuntimeError):
    pass

def acquire_lock(path: str, transaction_id: str) -> None:
    """Atomically create a mode-0600 JSON lock or raise SwitchBusy."""

def release_lock(path: str, transaction_id: str) -> None:
    """Remove only a lock owned by transaction_id."""

def redact(text: str) -> str:
    """Replace provider tokens, email addresses, auth headers, and private paths."""

def build_handoff(record: dict, terminal_tail: str, limit: int = 4000) -> dict:
    """Return public task state plus a redacted terminalTail bounded to limit."""

def revival_order(roster: list[dict]) -> list[dict]:
    """Return Boss first, Nightwatch second, then workers in original order."""

def snapshot(transaction_dir: str, roster: list[dict], bindings: dict) -> None:
    """Atomically persist the pre-switch roster and bindings with mode 0600."""

def stop_agents(roster: list[dict], selected_agent: str = "") -> None:
    """Stop all provider-backed agents or only selected_agent when provided."""

def revive_agents(roster: list[dict], selected_agent: str = "") -> None:
    """Revive the selected roster through mp spawn in revival_order."""

def verify_roles(roster: list[dict], selected_agent: str = "") -> None:
    """Raise RuntimeError unless expected agents are alive with matching roles."""

def rollback(transaction_dir: str) -> None:
    """Stop transaction-created agents, restore bindings, and revive the snapshot."""
```

Use atomic JSON writes with mode `0600`. Redact token prefixes, email
addresses, authorization headers, and private Windows user paths. Never include
`auth.json` content.

Provide CLI subcommands:

```text
prepare --transaction <id> [--agent <agent-id>]
stop --transaction <id>
revive --transaction <id>
verify --transaction <id>
commit --transaction <id>
rollback --transaction <id>
status
```

- [ ] **Step 4: Pause automatic revival while locked**

Add this guard at the top of the `boss-supervisor.sh` loop:

```bash
if [[ -f "$ROOT/run/provider-switch.lock" ]]; then
  sleep 1
  continue
fi
```

- [ ] **Step 5: Run provider-session and supervisor contracts**

```powershell
docker exec -e PYTHONPATH=/home/mp/mypeople/bin mypeople python3 /home/mp/mypeople/verify/test_provider_session.py
docker exec mypeople python3 /home/mp/mypeople/verify/test_boss_supervisor_backend.py
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add bin/provider-session bin/boss-supervisor.sh verify/test_provider_session.py
git commit -m "Add provider switch transaction runtime"
```

### Task 4: Implement the protected Windows profile store

**Files:**
- Create: `windows/MyPeople.ProviderProfiles.psm1`
- Create: `windows/Save-MyPeopleProviderProfile.ps1`
- Create: `windows/Get-MyPeopleProviderStatus.ps1`
- Create: `verify/test_windows_provider_profiles.py`

- [ ] **Step 1: Write the failing static security contract**

Create `verify/test_windows_provider_profiles.py`:

```python
#!/usr/bin/env python3
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class WindowsProviderProfileContract(unittest.TestCase):
    def test_module_uses_local_app_data_and_restricts_acl(self):
        text = (ROOT / "windows" / "MyPeople.ProviderProfiles.psm1").read_text(encoding="utf-8")
        self.assertIn("LOCALAPPDATA", text)
        self.assertIn("SetAccessRuleProtection", text)
        self.assertIn("FileSystemAccessRule", text)
        self.assertIn("Get-MyPeopleProviderAdapter", text)
        for operation in ("InspectSource", "SaveProfile", "ActivateProfile", "ValidateRuntime", "RuntimeEnvironment", "LaunchArguments", "RestorePrevious"):
            self.assertIn(operation, text)
        self.assertNotIn("Write-Host $credential", text)

    def test_save_script_validates_codex_without_printing_auth(self):
        text = (ROOT / "windows" / "Save-MyPeopleProviderProfile.ps1").read_text(encoding="utf-8")
        self.assertIn("codex login status", text)
        self.assertIn(".codex", text)
        self.assertNotIn("Get-Content", text)

if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run the test and observe failure**

```powershell
docker cp verify/test_windows_provider_profiles.py mypeople:/home/mp/mypeople/verify/test_windows_provider_profiles.py
docker exec mypeople python3 /home/mp/mypeople/verify/test_windows_provider_profiles.py
```

Expected: ERROR because the PowerShell files do not exist.

- [ ] **Step 3: Implement the PowerShell module**

Export these functions:

```powershell
Initialize-MyPeopleProfileStore
Test-MyPeopleProfileId
Get-MyPeopleProfilePath
Protect-MyPeopleDirectory
Read-MyPeopleJson
Write-MyPeopleJsonAtomic
Get-MyPeopleProviderAdapter
Save-MyPeopleCodexCredential
Install-MyPeopleCodexProfileInContainer
Test-MyPeopleCodexProfileInContainer
Get-MyPeopleProviderBindings
Set-MyPeopleProviderBindings
```

`Protect-MyPeopleDirectory` disables inherited ACLs and grants full control
only to the current Windows user and `SYSTEM`. JSON writes use a temporary
file plus `Move-Item -Force` within the same directory. Credential functions
copy bytes without printing or parsing the credential.

`Get-MyPeopleProviderAdapter -Provider codex` returns a hashtable containing
exactly these script-block operations: `InspectSource`, `SaveProfile`,
`ActivateProfile`, `ValidateRuntime`, `RuntimeEnvironment`, `LaunchArguments`,
and `RestorePrevious`. Each operation delegates to the Codex-specific helper;
an unknown provider throws before changing state. Save and switch commands call
this adapter rather than calling Codex helpers directly, leaving one explicit
extension point for a future Claude adapter.

- [ ] **Step 4: Implement save and status commands**

`Save-MyPeopleProviderProfile.ps1` accepts:

```powershell
param(
    [ValidateSet('codex')][string]$Provider,
    [Parameter(Mandatory)][string]$Profile,
    [switch]$FromCurrentWindowsLogin
)
```

It runs `codex login status`, verifies `$env:USERPROFILE\.codex\auth.json`,
copies it into the protected profile directory, and records non-secret metadata.

`Get-MyPeopleProviderStatus.ps1` prints only profile IDs, provider names,
effective bindings, and validation state.

- [ ] **Step 5: Run static tests and PowerShell parsing**

```powershell
docker exec mypeople python3 /home/mp/mypeople/verify/test_windows_provider_profiles.py
[ScriptBlock]::Create((Get-Content -Raw windows/MyPeople.ProviderProfiles.psm1)) | Out-Null
[ScriptBlock]::Create((Get-Content -Raw windows/Save-MyPeopleProviderProfile.ps1)) | Out-Null
[ScriptBlock]::Create((Get-Content -Raw windows/Get-MyPeopleProviderStatus.ps1)) | Out-Null
```

Expected: all commands exit 0.

- [ ] **Step 6: Commit**

```powershell
git add windows verify/test_windows_provider_profiles.py
git commit -m "Add protected provider profile store"
```

### Task 5: Implement global and per-agent transactional switching

**Files:**
- Create: `windows/Switch-MyPeopleProviderProfile.ps1`
- Modify: `verify/test_windows_provider_profiles.py`

- [ ] **Step 1: Add failing transaction assertions**

Add assertions that the switch script contains this ordered command contract:

```python
prepare = text.index("provider-session prepare")
stop = text.index("provider-session stop")
validate = text.index("& $adapter.ValidateRuntime")
revive = text.index("provider-session revive")
verify = text.index("provider-session verify")
commit = text.index("provider-session commit")
self.assertLess(prepare, stop)
self.assertLess(stop, validate)
self.assertLess(validate, revive)
self.assertLess(revive, verify)
self.assertLess(verify, commit)
self.assertIn("provider-session rollback", text)
self.assertIn("[string]$Agent", text)
self.assertIn("$adapter = Get-MyPeopleProviderAdapter", text)
```

- [ ] **Step 2: Run the focused test and observe failure**

Run `test_windows_provider_profiles.py`.

Expected: FAIL because the switch script does not exist.

- [ ] **Step 3: Implement the switch script**

The script accepts:

```powershell
param(
    [Parameter(Mandatory)][string]$Profile,
    [string]$Agent = '',
    [int]$TimeoutSeconds = 120
)
```

It generates a transaction ID, resolves the profile's provider through
`Get-MyPeopleProviderAdapter`, invokes `prepare`, copies the transaction
handoffs to `%LOCALAPPDATA%\MyPeople\handoffs\<transaction-id>`, invokes
`stop`, activates and validates the profile through the adapter, updates global
or agent bindings,
invokes `revive`, `verify`, and `commit`. A `catch` block invokes
`rollback`, restores previous bindings and credential references, and exits 1.
The script logs phases and profile IDs only.

- [ ] **Step 4: Run the focused test and a forced-failure dry run**

```powershell
docker exec mypeople python3 /home/mp/mypeople/verify/test_windows_provider_profiles.py
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\Switch-MyPeopleProviderProfile.ps1 -Profile missing-profile
```

Expected: tests pass; the dry run exits 1 during preflight without stopping any
agent.

- [ ] **Step 5: Commit**

```powershell
git add windows/Switch-MyPeopleProviderProfile.ps1 verify/test_windows_provider_profiles.py
git commit -m "Add transactional provider switching"
```

### Task 6: Rehydrate the active profile during one-click startup

**Files:**
- Modify: `windows/Start-MyPeople.ps1`
- Modify: `verify/test_windows_launcher.py`

- [ ] **Step 1: Add a failing startup-order test**

Assert that the launcher contains:

```python
rehydrate = text.index("& $adapter.ActivateProfile")
start_agents = text.index("mypeople up --detach")
self.assertLess(rehydrate, start_agents)
self.assertIn("& $adapter.ValidateRuntime", text)
```

- [ ] **Step 2: Run the launcher test and observe failure**

```powershell
docker exec mypeople python3 /home/mp/mypeople/verify/test_windows_launcher.py
```

Expected: FAIL because startup does not rehydrate provider profiles.

- [ ] **Step 3: Add profile preflight to the launcher**

Import `MyPeople.ProviderProfiles.psm1`, read the active global binding, resolve
its provider adapter, activate the protected profile into its runtime home,
invoke the adapter's `ValidateRuntime` operation, then start MyPeople. The Codex
adapter validates with `codex login status`. If no binding exists, preserve the
current legacy startup and log `No provider binding configured`.

- [ ] **Step 4: Run tests and a no-browser startup smoke**

```powershell
docker exec mypeople python3 /home/mp/mypeople/verify/test_windows_launcher.py
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\Start-MyPeople.ps1 -NoBrowser
```

Expected: test passes and startup exits 0.

- [ ] **Step 5: Commit**

```powershell
git add windows/Start-MyPeople.ps1 verify/test_windows_launcher.py
git commit -m "Rehydrate provider profiles on startup"
```

### Task 7: Save the current Codex login and exercise rollback safely

**Files:**
- Local only: `%LOCALAPPDATA%\MyPeople\credentials\codex\codex-primary\auth.json`
- Runtime only: `/home/mp/mypeople/run/provider-homes/codex/codex-primary/`
- Modify: `docs/USER-MANUAL.md`

- [ ] **Step 1: Save the current Windows login**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\Save-MyPeopleProviderProfile.ps1 -Provider codex -Profile codex-primary -FromCurrentWindowsLogin
```

Expected: exit 0 and a non-secret confirmation naming `codex-primary`.

- [ ] **Step 2: Confirm no credential entered Git**

```powershell
git status --short
git ls-files | rg -i "auth\.json|credentials|provider-homes"
```

Expected: no credential or runtime profile file is tracked.

- [ ] **Step 3: Exercise forced validation rollback**

Create a local test profile directory containing an invalid credential fixture,
invoke the switch command for that profile, and confirm:

```text
switch exits 1
previous global binding remains codex-primary
Boss is alive
Nightwatch is alive
invalid credential content is absent from logs
```

Delete the local invalid fixture after the check without deleting
`codex-primary`.

- [ ] **Step 4: Perform the real global switch**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\Switch-MyPeopleProviderProfile.ps1 -Profile codex-primary
```

Expected: exit 0 after Boss, Nightwatch, and active workers revive.

- [ ] **Step 5: Verify runtime identity and roles**

```powershell
docker exec -e CODEX_HOME=/home/mp/mypeople/run/provider-homes/codex/codex-primary mypeople codex login status
docker exec mypeople /home/mp/mypeople/bin/mypeople status
(Invoke-WebRequest -UseBasicParsing http://localhost:9933/health).Content
(Invoke-WebRequest -UseBasicParsing http://localhost:9900/health).Content
```

Expected: Codex is logged in, both supervisors are alive, and both health
responses report `ok`.

- [ ] **Step 6: Document operator and recovery commands**

Add to `docs/USER-MANUAL.md`:

- saving a profile;
- switching globally;
- assigning and removing an agent override;
- listing non-secret status;
- startup rehydration;
- rollback behavior;
- the location of local protected state;
- the rule that HUD controls are not implemented yet.

- [ ] **Step 7: Commit documentation**

```powershell
git add docs/USER-MANUAL.md
git commit -m "Document provider profile operations"
```

### Task 8: Complete verification and public push

**Files:**
- Modify: `verify/verify.sh`
- Modify: `docs/superpowers/plans/2026-07-14-provider-session-orchestration.md`

- [ ] **Step 1: Add new tests to the verifier**

Place these commands before `core_verify.py`:

```bash
python3 "$VERIFY/test_provider_profiles.py"
python3 "$VERIFY/test_provider_session.py"
python3 "$VERIFY/test_windows_provider_profiles.py"
```

- [ ] **Step 2: Deploy the candidate files to the live container**

```powershell
docker cp bin/. mypeople:/home/mp/mypeople/bin/
docker cp verify/. mypeople:/home/mp/mypeople/verify/
docker cp docs/. mypeople:/home/mp/mypeople/docs/
docker cp windows/. mypeople:/home/mp/mypeople/windows/
```

- [ ] **Step 3: Run the full verifier**

```powershell
docker exec mypeople bash /home/mp/mypeople/verify/verify.sh
```

Expected: all focused contracts and J1-J52 exit 0.

- [ ] **Step 4: Run final security and public-content scans**

```powershell
python verify/audit_public_history.py
git grep -n -I -P "[^\x00-\x7F]" -- .
git diff --check
git status --short
```

Expected: no secret or personal match; language matches are limited to technical
locale identifiers or explicitly reviewed quoted data; diff check is clean.

- [ ] **Step 5: Mark this plan's completed checkboxes and commit**

```powershell
git add docs/superpowers/plans/2026-07-14-provider-session-orchestration.md verify/verify.sh
git commit -m "Complete provider session orchestration"
```

- [ ] **Step 6: Push and verify the remote head**

```powershell
git push origin main
git ls-remote origin refs/heads/main
git log -1 --oneline
```

Expected: the remote `main` hash equals the local `HEAD`.
