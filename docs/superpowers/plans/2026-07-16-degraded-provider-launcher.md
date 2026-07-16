# Degraded Provider Launcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Windows one-click launcher keep Priorities, HUD, and the terminal available when the configured provider cannot be validated, while pausing new agent launches safely.

**Architecture:** Keep Docker, Compose, memory rehydration, and control-plane health as fatal gates. Establish a durable provider-launch pause before the runtime supervisor can start, convert only the provider phase into an explicit Ready/Ready-degraded decision, drive the existing `mp providers-resume` or `mp providers-pause` control, and condition the Boss/Nightwatch gate on provider readiness. No new dependency or credential mechanism is needed.

**Tech Stack:** Windows PowerShell 5.1, Docker Desktop/Compose v2, existing MyPeople `mp` provider pause/resume commands, Python static contracts.

---

### Task 1: Lock the degraded-startup contract

**Files:**
- Modify: `verify/test_windows_launcher.py`

- [ ] **Step 1: Add the failing launcher regression test**

Add this method to `WindowsLauncherContract`:

```python
def test_provider_failure_opens_control_plane_in_degraded_mode(self):
    text = (ROOT / "windows" / "Start-MyPeople.ps1").read_text(encoding="utf-8")
    required = [
        "$providerReady = $false",
        "$providerWarning",
        "providers-pause",
        "providers-resume",
        "READY DEGRADED",
        "if ($providerReady)",
        "Show-LauncherWarning",
    ]
    for value in required:
        self.assertIn(value, text)
    self.assertNotIn("Save-MyPeopleProviderProfile.ps1", text)
    self.assertNotIn("Save-MyPeopleCodexCredential", text)
    provider_gate = text.index("if ($providerReady)")
    agent_wait = text.index("'Boss and Nightwatch'")
    browser_open = text.index("Start-Process 'http://localhost:9933/'")
    self.assertLess(provider_gate, agent_wait)
    self.assertLess(agent_wait, browser_open)
```

- [ ] **Step 2: Run the contract and observe RED**

Run:

```powershell
python -B verify\test_windows_launcher.py
```

Expected: the new test fails because the current launcher has no explicit degraded branch or provider pause/resume calls.

- [ ] **Step 3: Commit the failing contract**

```powershell
git add verify/test_windows_launcher.py
git commit -m "test: require degraded provider startup"
```

### Task 2: Implement Ready and Ready-degraded startup

**Files:**
- Modify: `windows/Start-MyPeople.ps1`
- Test: `verify/test_windows_launcher.py`

- [ ] **Step 1: Add a warning surface and provider state**

After `Show-LauncherError`, add:

```powershell
function Show-LauncherWarning([string]$Message) {
    Write-LauncherLog "WARNING $Message"
    if ($NonInteractive) {
        Write-Output "WARNING $Message"
        return
    }
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show(
        $Message,
        'MyPeople started without agents',
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Warning
    ) | Out-Null
}

$providerReady = $false
$providerWarning = ''
```

- [ ] **Step 2: Replace the fatal provider phase with a bounded decision**

Replace the current bindings/profile block with:

```powershell
$bindings = Get-MyPeopleProviderBindings
$activeProfile = [string]$bindings.globalProfile
if ($activeProfile) {
    try {
        $profiles = Get-MyPeopleProviderProfiles
        $profileProperty = $profiles.PSObject.Properties[$activeProfile]
        if ($null -eq $profileProperty -or -not $profileProperty.Value.enabled) {
            throw 'The configured provider profile is missing or disabled.'
        }
        $adapter = Get-MyPeopleProviderAdapter -Provider ([string]$profileProperty.Value.provider)
        Write-LauncherLog "Rehydrate provider profile $activeProfile"
        & $adapter.ActivateProfile $activeProfile 'mypeople' | Out-Null
        & $adapter.ValidateRuntime $activeProfile 'mypeople' | Out-Null
        $providerReady = $true
    } catch {
        $providerWarning = 'The provider could not be validated. MyPeople is available, but new agents remain paused. Refresh the saved provider profile and run the shortcut again.'
    }
} else {
    $providerWarning = 'No global provider profile is configured. MyPeople is available, but new agents remain paused.'
}

if ($providerReady) {
    Write-LauncherLog 'Resume provider launches'
    & docker exec mypeople /home/mp/mypeople/bin/mp providers-resume | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Unable to resume provider launches.' }
} else {
    Write-LauncherLog 'Pause provider launches for degraded startup'
    & docker exec mypeople /home/mp/mypeople/bin/mp providers-pause --reason launcher_provider_unavailable | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Unable to pause provider launches safely.' }
}
```

Do not include the provider exception text in `launcher.log` or the warning.

- [ ] **Step 3: Make agent readiness conditional and browser startup unconditional**

Keep `mypeople up --detach`, Priorities, HUD, and terminal gates unconditional. Wrap only the Boss/Nightwatch wait:

```powershell
if ($providerReady) {
    Wait-Until {
        try {
            $statusOutput = @(& docker exec mypeople /home/mp/mypeople/bin/mp status 2>$null)
            $statusExitCode = $LASTEXITCODE
            $statusText = $statusOutput -join "`n"
            return $statusExitCode -eq 0 `
                -and $statusText -match 'main:Boss \[alive\]' `
                -and $statusText -match 'nightwatch:Nightwatch \[alive\]'
        } catch { return $false }
    } $ServiceTimeoutSeconds 'Boss and Nightwatch'
    Write-LauncherLog 'READY http://localhost:9933/'
} else {
    Write-LauncherLog 'READY DEGRADED http://localhost:9933/'
}

if (-not $NoBrowser) { Start-Process 'http://localhost:9933/' }
if ($providerWarning) { Show-LauncherWarning $providerWarning }
```

- [ ] **Step 4: Run GREEN contracts and parser checks**

Run:

```powershell
python -B verify\test_windows_launcher.py
python -B verify\test_provider_launch_pause.py
python -B verify\test_windows_provider_profiles.py
$errors = $null
[void][Management.Automation.Language.Parser]::ParseFile(
    (Resolve-Path windows\Start-MyPeople.ps1),
    [ref]$null,
    [ref]$errors
)
if ($errors.Count) { $errors; exit 1 }
```

Expected: launcher `8/8`, provider pause/resume tests, provider-profile tests, and the PowerShell parser all pass.

- [ ] **Step 5: Commit the launcher behavior**

```powershell
git add windows/Start-MyPeople.ps1 verify/test_windows_launcher.py
git commit -m "fix: keep control plane available without provider"
```

### Task 3: Document the degraded operator path

**Files:**
- Modify: `README.md`
- Modify: `docs/USER-MANUAL.md`
- Test: `verify/test_public_repository.py`

- [ ] **Step 1: Add public documentation assertions**

In `verify/test_public_repository.py`, add assertions that both public documents contain `Ready degraded`, `providers-resume`, and an explicit statement that credentials are never imported automatically.

- [ ] **Step 2: Run the public contract and observe RED**

Run:

```powershell
python -B verify\test_public_repository.py
```

Expected: FAIL because the public documents do not describe degraded startup.

- [ ] **Step 3: Document normal and degraded startup**

Add concise English sections explaining:

```markdown
### Ready degraded

The desktop shortcut keeps Priorities, HUD, and the terminal available when the
configured provider cannot be validated. New provider launches remain paused,
and the launcher never imports another Windows login automatically. Refresh the
saved profile explicitly, then run the shortcut again; a successful validation
runs `mp providers-resume` and restores Boss and Nightwatch.
```

- [ ] **Step 4: Run the public and launcher contracts**

```powershell
python -B verify\test_public_repository.py
python -B verify\test_windows_launcher.py
git diff --check
```

Expected: all pass with no whitespace errors.

- [ ] **Step 5: Commit documentation**

```powershell
git add README.md docs/USER-MANUAL.md verify/test_public_repository.py
git commit -m "docs: explain degraded provider startup"
```

### Task 4: Install and verify the one-click launcher

**Files:**
- Runtime copy: `%LOCALAPPDATA%\MyPeople\launcher\Start-MyPeople.ps1`
- Desktop shortcut: `%USERPROFILE%\Desktop\MyPeople.lnk`

- [ ] **Step 1: Run focused verification before installation**

```powershell
python -B verify\test_windows_launcher.py
python -B verify\test_provider_launch_pause.py
python -B verify\test_windows_provider_profiles.py
python -B verify\test_public_repository.py
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 2: Reinstall the shortcut from the reviewed branch**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\Install-MyPeopleShortcut.ps1
```

Expected: `MyPeople shortcut installed` with the desktop shortcut path.

- [ ] **Step 3: Verify installed source identity**

```powershell
$repo = Get-FileHash .\windows\Start-MyPeople.ps1 -Algorithm SHA256
$installed = Get-FileHash "$env:LOCALAPPDATA\MyPeople\launcher\Start-MyPeople.ps1" -Algorithm SHA256
if ($repo.Hash -ne $installed.Hash) { throw 'Installed launcher differs from reviewed source.' }
```

Expected: no exception.

- [ ] **Step 4: Run the normal live launcher smoke**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\MyPeople\launcher\Start-MyPeople.ps1" -NoBrowser -NonInteractive
docker exec mypeople /home/mp/mypeople/bin/mp providers-status
docker exec mypeople tmux has-session -t mc-main:Boss
docker exec mypeople tmux has-session -t mc-nightwatch:Nightwatch
```

Expected: launcher exits 0, provider status reports `paused: false`, and both tmux sessions exist.

- [ ] **Step 5: Verify control-plane health**

```powershell
(Invoke-WebRequest -UseBasicParsing http://127.0.0.1:9933/health).StatusCode
(Invoke-WebRequest -UseBasicParsing http://127.0.0.1:9900/health).StatusCode
```

Expected: `200` and `200`.

### Task 5: Review, publish, and preserve evidence

**Files:**
- Review all branch changes
- Update the existing MyPeople Roadmap OS item or create a focused repair record

- [ ] **Step 1: Run final branch verification**

```powershell
python -B verify\test_windows_launcher.py
python -B verify\test_provider_launch_pause.py
python -B verify\test_windows_provider_profiles.py
python -B verify\test_public_repository.py
python -B verify\test_docker_persistence.py
git diff --check
git status --short
```

Expected: tests pass, diff check is clean, and only intended committed changes exist.

- [ ] **Step 2: Request independent code review**

Review the Ready/Ready-degraded state transition, secret-safe logging, pause/resume ordering, unconditional health gates, conditional agent gate, PowerShell 5.1 parsing, and shortcut installation.

- [ ] **Step 3: Push and open an English GitHub pull request**

```powershell
git push -u origin fix/launcher-provider-degraded
gh pr create --repo LordCripto-Hub/Project-Factory --base main --head fix/launcher-provider-degraded --title "Keep MyPeople available during provider outages" --body "Adds a safe Ready-degraded launcher path while preserving provider pause/resume and credential boundaries."
```

- [ ] **Step 4: Merge only after the PR is clean and mergeable**

```powershell
gh pr view --repo LordCripto-Hub/Project-Factory --json state,mergeable,mergeStateStatus,statusCheckRollup,url
```

Expected: `mergeable: MERGEABLE` and no failing required checks before merge.

### Review correction: close the pre-validation launch race

Independent review found that starting Compose before writing the durable pause
marker allowed `boss-supervisor.sh` to revive an agent during provider
validation. The corrected implementation must:

- add a profile-scoped `provider-launch-gate` helper to Compose;
- give the helper no network and only the `mypeople-run` volume;
- run the helper before the pinned deployment starts;
- copy an equivalent marker before `docker start` in the legacy fallback;
- prove ordering in `verify/test_windows_launcher.py`; and
- run a real pause/status/resume helper smoke before installation.
