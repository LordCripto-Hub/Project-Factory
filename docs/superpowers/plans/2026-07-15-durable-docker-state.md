# Durable Docker State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the live MyPeople container from a disposable writable layer to named Docker volumes with Docker init, a foreground supervisor, tested portable backup/restore, launcher recovery, and automatic rollback.

**Architecture:** Keep application code in a pinned local image while mounting seven explicit state volumes. A PowerShell transaction preserves the old container, creates a verified candidate image in an isolated container, seeds volumes from the immutable snapshot, launches the new Compose deployment, verifies state and processes, drills restore in disposable volumes, and restores the untouched old container on failure.

**Tech Stack:** Docker Desktop/Compose, PowerShell 5.1+, Bash, Python 3 standard library, JSON, tmux, existing MyPeople verification harness.

---

## File map

- Create `docker/state-volumes.json`: canonical volume-to-container-path contract.
- Create `docker/compose.volume-backed.yml`: pinned volume-backed runtime definition.
- Modify `bin/runtime-supervisor.sh`: foreground owner for every long-running service.
- Modify `bin/mypeople`: idempotent compatibility entry point without a second Boss owner.
- Create `windows/MyPeople.DockerMigration.psm1`: allowlists, redaction, hashing, Docker invocation, transaction persistence, and rollback helpers.
- Create `windows/Migrate-MyPeopleDockerState.ps1`: dry-run-first migration transaction.
- Create `windows/Test-MyPeopleDockerRestore.ps1`: isolated restore drill with providers and Boss notifications disabled.
- Modify `windows/Start-MyPeople.ps1`: recreate/start the pinned Compose deployment safely.
- Modify `windows/Install-MyPeopleShortcut.ps1`: install launcher artifacts without overwriting deployment secrets.
- Create `verify/test_docker_persistence.py`: Compose and volume contract tests.
- Create `verify/test_runtime_supervisor.py`: process ownership and signal contract tests.
- Create `verify/Test-WindowsDockerMigration.ps1`: PowerShell migration unit/static tests.
- Modify `verify/test_windows_launcher.py`: launcher recovery contract.
- Modify `verify/verify.sh`: register focused Linux-side contracts.
- Modify `README.md` and `docs/USER-MANUAL.md`: operator procedure, evidence, rollback, and recovery.

## Fixed deployment contract

The implementation uses exactly these state boundaries:

```json
{
  "mypeople-todos": "/home/mp/mypeople/todos",
  "mypeople-run": "/home/mp/mypeople/run",
  "mypeople-status": "/home/mp/mypeople/status",
  "mypeople-config": "/home/mp/.config/mypeople",
  "mypeople-codex": "/home/mp/.codex",
  "mypeople-claude": "/home/mp/.claude",
  "mypeople-recordings": "/home/mp/recordings"
}
```

The migration never deletes those volumes, never deletes the preserved container, never runs `docker compose down -v`, and never enables Cloudflare memory.

### Task 1: Define the exact volume-backed deployment contract

**Files:**
- Create: `verify/test_docker_persistence.py`
- Create: `docker/state-volumes.json`
- Create: `docker/compose.volume-backed.yml`
- Modify: `verify/verify.sh`

- [ ] **Step 1: Write the failing persistence contract test**

Create `verify/test_docker_persistence.py`:

```python
#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "mypeople-todos": "/home/mp/mypeople/todos",
    "mypeople-run": "/home/mp/mypeople/run",
    "mypeople-status": "/home/mp/mypeople/status",
    "mypeople-config": "/home/mp/.config/mypeople",
    "mypeople-codex": "/home/mp/.codex",
    "mypeople-claude": "/home/mp/.claude",
    "mypeople-recordings": "/home/mp/recordings",
}

contract = json.loads((ROOT / "docker/state-volumes.json").read_text(encoding="utf-8"))
compose = (ROOT / "docker/compose.volume-backed.yml").read_text(encoding="utf-8")
assert contract == EXPECTED
assert "container_name: mypeople" in compose
assert "init: true" in compose
assert "restart: unless-stopped" in compose
assert 'command: ["/home/mp/mypeople/bin/runtime-supervisor.sh"]' in compose
assert "sleep infinity" not in compose
assert "down -v" not in compose
for volume, target in EXPECTED.items():
    assert f"{volume}:{target}" in compose
    assert f"name: {volume}" in compose
print("PASS volume-backed Docker deployment contract")
```

- [ ] **Step 2: Run the test and confirm the expected failure**

Run:

```powershell
python verify\test_docker_persistence.py
```

Expected: `FileNotFoundError` for `docker/state-volumes.json`.

- [ ] **Step 3: Add the manifest and Compose file**

Create `docker/state-volumes.json` with the exact JSON in **Fixed deployment contract**.

Create `docker/compose.volume-backed.yml`:

```yaml
services:
  mypeople:
    image: ${MYPEOPLE_IMAGE:?set MYPEOPLE_IMAGE}
    container_name: mypeople
    hostname: node-1
    user: mp
    init: true
    restart: unless-stopped
    command: ["/home/mp/mypeople/bin/runtime-supervisor.sh"]
    devices:
      - /dev/net/tun:/dev/net/tun
    cap_add:
      - NET_ADMIN
    ports:
      - "9900:9900"
      - "9933:9933"
      - "7681:7681"
      - "7682:7682"
      - "7699:7699"
    volumes:
      - type: bind
        source: ${MYPEOPLE_SEED_PATH:?set MYPEOPLE_SEED_PATH}
        target: /home/mp/mypeople.seed.md
        read_only: true
      - mypeople-todos:/home/mp/mypeople/todos
      - mypeople-run:/home/mp/mypeople/run
      - mypeople-status:/home/mp/mypeople/status
      - mypeople-config:/home/mp/.config/mypeople
      - mypeople-codex:/home/mp/.codex
      - mypeople-claude:/home/mp/.claude
      - mypeople-recordings:/home/mp/recordings

volumes:
  mypeople-todos:
    name: mypeople-todos
  mypeople-run:
    name: mypeople-run
  mypeople-status:
    name: mypeople-status
  mypeople-config:
    name: mypeople-config
  mypeople-codex:
    name: mypeople-codex
  mypeople-claude:
    name: mypeople-claude
  mypeople-recordings:
    name: mypeople-recordings
```

- [ ] **Step 4: Register and run the focused test**

Add this line before `core_verify.py` in `verify/verify.sh`:

```bash
python3 "$VERIFY/test_docker_persistence.py"
```

Run:

```powershell
python verify\test_docker_persistence.py
git diff --check
```

Expected: `PASS volume-backed Docker deployment contract` and no diff errors.

- [ ] **Step 5: Commit the deployment contract**

```powershell
git add docker verify/test_docker_persistence.py verify/verify.sh
git commit -m "Define volume-backed Docker deployment"
```

### Task 2: Make one foreground supervisor own every service

**Files:**
- Create: `verify/test_runtime_supervisor.py`
- Modify: `bin/runtime-supervisor.sh`
- Modify: `bin/mypeople`
- Modify: `verify/verify.sh`

- [ ] **Step 1: Write the failing ownership test**

Create `verify/test_runtime_supervisor.py`:

```python
#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
supervisor = (ROOT / "bin/runtime-supervisor.sh").read_text(encoding="utf-8")
launcher = (ROOT / "bin/mypeople").read_text(encoding="utf-8")

assert "trap shutdown TERM INT EXIT" in supervisor
assert 'spawn boss-supervisor bash "$ROOT/bin/boss-supervisor.sh"' in supervisor
assert 'wait "$pid"' in supervisor
assert 'kill -KILL "$pid"' in supervisor
assert 'printf \'%s\\n\' "$$" >"$ROOT/run/runtime-supervisor.pid"' in supervisor
assert "sudo -n setsid" not in supervisor
assert "runtime-supervisor.pid" in launcher
assert "boss-supervisor.pid" not in launcher
print("PASS single foreground runtime supervisor contract")
```

- [ ] **Step 2: Run the test and verify it fails on the current two-owner model**

```powershell
python verify\test_runtime_supervisor.py
```

Expected: assertion failure because `runtime-supervisor.sh` has no signal trap and `bin/mypeople` starts Boss separately.

- [ ] **Step 3: Replace the detached loop with a signal-aware foreground supervisor**

Implement `bin/runtime-supervisor.sh` with this structure:

```bash
#!/bin/bash
set -u
ROOT=${INSTALL_DIR:-$HOME/mypeople}
export INSTALL_DIR="$ROOT" PATH="$HOME/.local/bin:$ROOT/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" LANG=C.UTF-8 LC_ALL=C.UTF-8
. "$HOME/.config/mypeople/queue.env"
mkdir -p "$ROOT/run" "$ROOT/run/tailscale-state"
printf '%s\n' "$$" >"$ROOT/run/runtime-supervisor.pid"
declare -A children=()
stopping=0

alive() {
  local pid=${children[$1]:-} stat=""
  [[ -n "$pid" ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  stat=$(ps -o stat= -p "$pid" 2>/dev/null)
  [[ "$stat" != Z* ]]
}

spawn() {
  local name=$1 pid=""; shift
  alive "$name" && return 0
  pid=${children[$name]:-}
  [[ -z "$pid" ]] || wait "$pid" 2>/dev/null || true
  "$@" </dev/null >>"$ROOT/run/$name.log" 2>&1 &
  pid=$!
  children[$name]=$pid
  printf '%s\n' "$pid" >"$ROOT/run/$name.pid"
}

shutdown() {
  (( stopping )) && return 0
  stopping=1
  trap - TERM INT EXIT
  local pid deadline=$((SECONDS + 20))
  for pid in "${children[@]}"; do kill -TERM "$pid" 2>/dev/null || true; done
  while (( SECONDS < deadline )); do
    local any=0
    for pid in "${children[@]}"; do kill -0 "$pid" 2>/dev/null && any=1; done
    (( any )) || break
    sleep 1
  done
  for pid in "${children[@]}"; do kill -KILL "$pid" 2>/dev/null || true; done
  for pid in "${children[@]}"; do wait "$pid" 2>/dev/null || true; done
  [[ $(cat "$ROOT/run/runtime-supervisor.pid" 2>/dev/null) == "$$" ]] && rm -f "$ROOT/run/runtime-supervisor.pid"
}
trap shutdown TERM INT EXIT

while (( ! stopping )); do
  spawn queue-server python3 "$ROOT/bin/queue-server.py"
  spawn todo-server env PATH="$HOME/.local/bin:$ROOT/bin:$PATH" python3 "$ROOT/bin/todo-server.py"
  spawn queue-client python3 "$ROOT/bin/queue-client.py"
  spawn board-export python3 "$ROOT/bin/board-export.py"
  spawn ttyd-write ttyd -i 0.0.0.0 -W -a -p "$TTYD_PORT" -t disableLeaveAlert=true "$ROOT/bin/attach-helper.sh"
  spawn ttyd-read ttyd -i 0.0.0.0 -a -p "$TTYD_RO_PORT" -t disableLeaveAlert=true "$ROOT/bin/attach-ro-helper.sh"
  spawn boss-supervisor bash "$ROOT/bin/boss-supervisor.sh"
  if ! sudo -n tailscale --socket="$ROOT/run/tailscale-state/tailscaled.sock" status >/dev/null 2>&1; then
    spawn tailscaled sudo -n /usr/sbin/tailscaled \
      --state="$ROOT/run/tailscale-state/tailscaled.state" \
      --socket="$ROOT/run/tailscale-state/tailscaled.sock" \
      --tun=tailscale0
  fi
  if [[ -S "$ROOT/run/tailscale-state/tailscaled.sock" ]]; then
    sudo -n ln -sf "$ROOT/run/tailscale-state/tailscaled.sock" /var/run/tailscale/tailscaled.sock || true
  fi
  sleep 2 & pid=$!; wait "$pid" || true
done
```

Replace `bin/mypeople` with the single-owner compatibility wrapper:

```bash
#!/bin/bash
set -euo pipefail
ROOT=${INSTALL_DIR:-$HOME/mypeople}; cmd=${1:-status}
case "$cmd" in
  up)
    mkdir -p "$ROOT/run"
    if [[ -f "$ROOT/run/runtime-supervisor.pid" ]] \
      && kill -0 "$(cat "$ROOT/run/runtime-supervisor.pid")" 2>/dev/null \
      && [[ $(ps -o stat= -p "$(cat "$ROOT/run/runtime-supervisor.pid")") != Z* ]]; then
      :
    else
      setsid "$ROOT/bin/runtime-supervisor.sh" </dev/null >>"$ROOT/run/runtime-supervisor.log" 2>&1 &
      echo $! >"$ROOT/run/runtime-supervisor.pid"
    fi
    ;;
  status) "$ROOT/bin/mp" status ;;
  *) echo "usage: mypeople up [--detach]|status" >&2; exit 2 ;;
esac
```

The compatibility wrapper may use `setsid` for manual legacy startup; the foreground Compose supervisor itself must not detach or create a second Boss owner.

- [ ] **Step 4: Run focused supervisor tests**

```powershell
python verify\test_runtime_supervisor.py
python verify\test_boss_supervisor_backend.py
```

Expected: both tests pass. Add `python3 "$VERIFY/test_runtime_supervisor.py"` to `verify/verify.sh`.

- [ ] **Step 5: Commit the process model**

```powershell
git add bin/runtime-supervisor.sh bin/mypeople verify/test_runtime_supervisor.py verify/verify.sh
git commit -m "Run MyPeople under one foreground supervisor"
```

### Task 3: Add pure migration validation, redaction, and transaction helpers

**Files:**
- Create: `verify/Test-WindowsDockerMigration.ps1`
- Create: `windows/MyPeople.DockerMigration.psm1`

- [ ] **Step 1: Write failing PowerShell unit tests**

Create `verify/Test-WindowsDockerMigration.ps1`:

```powershell
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Import-Module (Join-Path $root 'windows\MyPeople.DockerMigration.psm1') -Force

$contract = Get-MyPeopleVolumeContract -Root $root
if ($contract.Count -ne 7) { throw "Expected seven volumes" }
if ($contract['mypeople-run'] -ne '/home/mp/mypeople/run') { throw 'Wrong run target' }
if (-not (Test-MyPeopleDockerName 'mypeople-pre-volumes-20260715T190000Z')) { throw 'Safe name rejected' }
if (Test-MyPeopleDockerName 'mypeople;rm') { throw 'Unsafe name accepted' }

$redacted = ConvertTo-MyPeopleRedactedConfig @'
QUEUE_SECRET=alpha
NIGHTWATCH_TOKEN=beta
HOST_ID=node-1
TODO_PORT=9933
'@
if ($redacted -match 'alpha|beta') { throw 'Secret value leaked' }
if ($redacted -notmatch 'QUEUE_SECRET=<redacted>') { throw 'Queue secret was not redacted' }
if ($redacted -notmatch 'HOST_ID=node-1') { throw 'Non-secret value was lost' }

$migration = Get-Content -Raw (Join-Path $root 'windows\Migrate-MyPeopleDockerState.ps1') -ErrorAction SilentlyContinue
if ($migration) {
    foreach ($required in @('Docker commit', 'Docker rename', 'Invoke-MyPeopleRollback', 'compose.volume-backed.yml', 'state-volumes.json')) {
        if ($migration -notmatch [regex]::Escape($required)) { throw "Missing migration token: $required" }
    }
    foreach ($forbidden in @('docker volume rm', 'docker compose down -v', 'docker system prune')) {
        if ($migration -match [regex]::Escape($forbidden)) { throw "Forbidden migration token: $forbidden" }
    }
}
Write-Output 'PASS Docker migration contract, names, and redaction'
```

- [ ] **Step 2: Run the tests and verify the module is missing**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File verify\Test-WindowsDockerMigration.ps1
```

Expected: import failure for `MyPeople.DockerMigration.psm1`.

- [ ] **Step 3: Implement the pure helpers**

Create `windows/MyPeople.DockerMigration.psm1`:

```powershell
$script:SecretPattern = '(?i)(secret|token|password|api[_-]?key|credential|auth)'

function Get-MyPeopleVolumeContract([string]$Root) {
    $path = Join-Path $Root 'docker\state-volumes.json'
    $object = Get-Content -Raw -LiteralPath $path | ConvertFrom-Json
    $result = [ordered]@{}
    foreach ($property in $object.PSObject.Properties) {
        $result[$property.Name] = [string]$property.Value
    }
    return $result
}

function Test-MyPeopleDockerName([string]$Name) {
    return $Name -match '^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$'
}

function ConvertTo-MyPeopleRedactedConfig([string]$Text) {
    $lines = foreach ($line in ($Text -split "`r?`n")) {
        if ($line -match '^\s*([^#=]+)=(.*)$' -and $matches[1] -match $script:SecretPattern) {
            '{0}=<redacted>' -f $matches[1].Trim()
        } else { $line }
    }
    return $lines -join "`n"
}

function Get-MyPeopleSha256([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Write-MyPeopleTransaction([string]$Path, [System.Collections.IDictionary]$State) {
    $directory = Split-Path $Path -Parent
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    $temporary = "$Path.tmp"
    $State | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function Invoke-MyPeopleDocker {
    param([Parameter(Mandatory)][string[]]$Arguments, [switch]$Capture)
    $output = @(& docker @Arguments 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "docker $($Arguments -join ' ') failed: $($output -join "`n")" }
    if ($Capture) { return $output -join "`n" }
}

function Invoke-MyPeopleRollback {
    param([string]$PreservedName, [string]$NewName = 'mypeople')
    $oldExists = (& docker inspect $PreservedName *> $null; $LASTEXITCODE -eq 0)
    $newExists = (& docker inspect $NewName *> $null; $LASTEXITCODE -eq 0)
    if (-not $oldExists) {
        if (-not $newExists) { throw "Neither preserved nor original container exists" }
        Invoke-MyPeopleDocker -Arguments @('start', $NewName)
        return
    }
    if ($newExists) { Invoke-MyPeopleDocker -Arguments @('rm', '-f', $NewName) }
    Invoke-MyPeopleDocker -Arguments @('rename', $PreservedName, $NewName)
    Invoke-MyPeopleDocker -Arguments @('start', $NewName)
}

Export-ModuleMember -Function Get-MyPeopleVolumeContract, Test-MyPeopleDockerName, ConvertTo-MyPeopleRedactedConfig, Get-MyPeopleSha256, Write-MyPeopleTransaction, Invoke-MyPeopleDocker, Invoke-MyPeopleRollback
```

- [ ] **Step 4: Run the pure tests**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File verify\Test-WindowsDockerMigration.ps1
```

Expected: `PASS Docker migration contract, names, and redaction`.

- [ ] **Step 5: Commit the safety helpers**

```powershell
git add windows/MyPeople.DockerMigration.psm1 verify/Test-WindowsDockerMigration.ps1
git commit -m "Add Docker migration safety helpers"
```

### Task 4: Implement the dry-run-first migration and automatic rollback

**Files:**
- Modify: `verify/Test-WindowsDockerMigration.ps1`
- Create: `windows/Migrate-MyPeopleDockerState.ps1`

- [ ] **Step 1: Extend the failing static safety test**

After loading `$migration`, add:

```powershell
foreach ($required in @(
    '[switch]$Execute',
    'mypeople-pre-volumes-',
    'mypeople-node:pre-volumes-',
    'mypeople-node:volume-backed-',
    'portable-state.tar.gz',
    'Remove-StaleRuntimePidFiles',
    'Test-MyPeopleDockerRestore.ps1'
)) {
    if ($migration -notmatch [regex]::Escape($required)) { throw "Missing guarded migration behavior: $required" }
}
```

- [ ] **Step 2: Run the test and verify the migration script is absent**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File verify\Test-WindowsDockerMigration.ps1
```

Expected: failure on the first missing migration behavior.

- [ ] **Step 3: Implement preflight and dry-run as the default**

Create `windows/Migrate-MyPeopleDockerState.ps1` with this entry contract:

```powershell
param(
    [switch]$Execute,
    [ValidatePattern('^mypeople$')][string]$Container = 'mypeople',
    [string]$SeedPath = $env:MYPEOPLE_SEED_PATH,
    [int]$MinimumFreeGiB = 16
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Import-Module (Join-Path $PSScriptRoot 'MyPeople.DockerMigration.psm1') -Force
if (-not $SeedPath) {
    $mounts = (& docker inspect -f '{{json .Mounts}}' $Container | ConvertFrom-Json)
    $seedMount = @($mounts | Where-Object Destination -eq '/home/mp/mypeople.seed.md') | Select-Object -First 1
    $SeedPath = [string]$seedMount.Source
}
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$stateRoot = Join-Path $env:LOCALAPPDATA 'MyPeople'
$transactionRoot = Join-Path $stateRoot "backups\docker-migration\$stamp"
$transactionPath = Join-Path $transactionRoot 'transaction.json'
$lockPath = Join-Path $stateRoot 'docker-migration.lock'
$preservedName = "mypeople-pre-volumes-$stamp"
$snapshotImage = "mypeople-node:pre-volumes-$stamp"
$gitSha = (& git -C $root rev-parse --short=12 HEAD).Trim()
$candidateImage = "mypeople-node:volume-backed-$gitSha"
$contract = Get-MyPeopleVolumeContract -Root $root
$state = [ordered]@{
    id=$stamp; stage='preflight'; execute=[bool]$Execute; container=$Container
    preservedContainer=$preservedName; snapshotImage=$snapshotImage; candidateImage=$candidateImage
    volumes=@($contract.Keys); backup=$transactionRoot; rollbackAttempted=$false
}
$deploymentWritten = $false

function Set-Stage([string]$Name) {
    $script:state.stage = $Name
    Write-MyPeopleTransaction -Path $transactionPath -State $script:state
}
function Docker([Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments) {
    Invoke-MyPeopleDocker -Arguments $Arguments
}
function Assert-Preflight {
    if (Test-Path -LiteralPath $lockPath) { throw "Migration lock already exists: $lockPath" }
    if (-not (Test-Path -LiteralPath $SeedPath)) { throw "Seed file not found: $SeedPath" }
    if ($Execute -and (& git -C $root status --porcelain)) { throw 'Source repository must be clean before building the candidate image' }
    & docker inspect $Container *> $null
    if ($LASTEXITCODE -ne 0) { throw "Expected container not found: $Container" }
    $running = (& docker inspect -f '{{.State.Running}}' $Container).Trim()
    if ($running -ne 'true') { throw 'The live container must be running for preflight' }
    $driveName = ([IO.Path]::GetPathRoot($stateRoot).TrimEnd(':\'))
    $drive = Get-PSDrive -Name $driveName
    if (($drive.Free / 1GB) -lt $MinimumFreeGiB) { throw "Need at least $MinimumFreeGiB GiB free" }
    Invoke-WebRequest -UseBasicParsing http://localhost:9933/health -TimeoutSec 5 | Out-Null
    Invoke-WebRequest -UseBasicParsing http://localhost:9900/health -TimeoutSec 5 | Out-Null
}
function Remove-StaleRuntimePidFiles([string]$StagingContainer) {
    Docker exec $StagingContainer sh -lc "find /mnt/mypeople-run -maxdepth 1 -type f -name '*.pid' -delete"
}

Assert-Preflight
New-Item -ItemType Directory -Path $transactionRoot -Force | Out-Null
& icacls $transactionRoot /inheritance:r /grant:r "${env:USERNAME}:(OI)(CI)F" | Out-Null
Set-Content -LiteralPath $lockPath -Value $stamp -Encoding ASCII
Set-Stage 'planned'
if (-not $Execute) {
    Write-Output "DRY RUN PASS: plan recorded at $transactionPath"
    Remove-Item -LiteralPath $lockPath -Force
    exit 0
}
```

The dry run performs only health/preflight reads plus writing its local plan and lock lifecycle. It must not stop, rename, commit, create, or remove Docker objects.

- [ ] **Step 4: Implement snapshot, isolated candidate image, and volume seeding**

Continue the script inside `try`. The original stopped container is committed first. The new repository code is copied into a separate candidate container, tested there, and committed to a different image; the preserved live container itself is never modified.

```powershell
try {
    Set-Stage 'quiesce'
    $before = Invoke-MyPeopleDocker -Arguments @(
        'exec',$Container,'sh','-lc',
        'sha256sum /home/mp/mypeople/todos/board.v2.json /home/mp/mypeople/run/roster.json'
    ) -Capture
    $before | Set-Content -LiteralPath (Join-Path $transactionRoot 'before-state.sha256') -Encoding ASCII
    Docker stop --time 30 $Container

    Set-Stage 'snapshot'
    Docker commit $Container $snapshotImage

    Set-Stage 'candidate-image'
    $candidateContainer = "mypeople-candidate-$stamp"
    Docker create --name $candidateContainer $snapshotImage sleep infinity
    try {
        Docker start $candidateContainer
        foreach ($path in @('bin','verify','memory-gateway','plugins','docs','docker')) {
            Docker cp (Join-Path $root $path) "${candidateContainer}:/home/mp/mypeople/"
        }
        foreach ($path in @('install.sh','README.md')) {
            Docker cp (Join-Path $root $path) "${candidateContainer}:/home/mp/mypeople/$path"
        }
        Docker exec -u root $candidateContainer chown -R mp:mp /home/mp/mypeople
        Docker exec -u root $candidateContainer sh -lc "find /home/mp/mypeople/bin -maxdepth 1 -type f -exec chmod 0755 {} +; chmod 0755 /home/mp/mypeople/install.sh"
        Docker exec $candidateContainer bash -lc 'cd /home/mp/mypeople && python3 verify/test_docker_persistence.py && python3 verify/test_runtime_supervisor.py && python3 verify/test_boss_supervisor_backend.py'
        Docker commit $candidateContainer $candidateImage
    } finally {
        & docker rm -f $candidateContainer *> $null
    }

    Set-Stage 'create-volumes'
    foreach ($volume in $contract.Keys) {
        & docker volume inspect $volume *> $null
        if ($LASTEXITCODE -ne 0) { Docker volume create $volume }
    }

    Set-Stage 'seed-volumes'
    $staging = "mypeople-seed-$stamp"
    $createArgs = @('create','--name',$staging,'--user','root')
    foreach ($volume in $contract.Keys) {
        $createArgs += @('--mount', "type=volume,src=$volume,dst=/mnt/$volume")
    }
    $createArgs += @($snapshotImage,'sleep','infinity')
    Invoke-MyPeopleDocker -Arguments $createArgs
    Docker start $staging
    try {
        foreach ($entry in $contract.GetEnumerator()) {
            $source = $entry.Value
            $target = "/mnt/$($entry.Key)"
            $count = Invoke-MyPeopleDocker -Arguments @('exec',$staging,'sh','-lc',"find '$target' -mindepth 1 -maxdepth 1 -print -quit") -Capture
            if ($count.Trim()) { throw "Refusing to seed non-empty volume: $($entry.Key)" }
            Docker exec $staging sh -lc "mkdir -p '$target' && if [ -d '$source' ]; then cp -a '$source'/.' '$target'/; fi"
        }
        Remove-StaleRuntimePidFiles $staging
    } finally {
        & docker rm -f $staging *> $null
    }
```

- [ ] **Step 5: Create the ACL-protected portable archive without provider credentials**

Continue in the same `try` block:

```powershell
    Set-Stage 'portable-backup'
    $archiveContainer = "mypeople-archive-$stamp"
    Docker create --name $archiveContainer --user root $snapshotImage sleep infinity
    try {
        Docker start $archiveContainer
        $archiveCommand = @'
set -eu
mkdir -p /tmp/portable/home/mp/mypeople/run /tmp/portable/home/mp/.codex /tmp/portable/home/mp/.claude
copy_if_present() { [ ! -e "$1" ] || cp -a "$1" "$2"; }
copy_if_present /home/mp/mypeople/todos /tmp/portable/home/mp/mypeople/
copy_if_present /home/mp/mypeople/status /tmp/portable/home/mp/mypeople/
copy_if_present /home/mp/mypeople/run/roster.json /tmp/portable/home/mp/mypeople/run/
copy_if_present /home/mp/mypeople/run/taskspecs /tmp/portable/home/mp/mypeople/run/
copy_if_present /home/mp/mypeople/run/proofs /tmp/portable/home/mp/mypeople/run/
copy_if_present /home/mp/recordings /tmp/portable/home/mp/
copy_if_present /home/mp/.codex/sessions /tmp/portable/home/mp/.codex/
copy_if_present /home/mp/.claude/projects /tmp/portable/home/mp/.claude/
find /tmp/portable -type f \( -iname '*auth*' -o -iname '*credential*' -o -iname '*token*' -o -iname '*.key' \) -delete
tar -C /tmp/portable -czf /tmp/portable-state.tar.gz .
'@
        Invoke-MyPeopleDocker -Arguments @('exec',$archiveContainer,'sh','-lc',$archiveCommand)
        Docker cp "${archiveContainer}:/tmp/portable-state.tar.gz" (Join-Path $transactionRoot 'portable-state.tar.gz')
        $config = Invoke-MyPeopleDocker -Arguments @('exec',$archiveContainer,'sh','-lc','cat /home/mp/.config/mypeople/queue.env') -Capture
        ConvertTo-MyPeopleRedactedConfig $config |
            Set-Content -LiteralPath (Join-Path $transactionRoot 'queue.env.redacted') -Encoding UTF8
    } finally {
        & docker rm -f $archiveContainer *> $null
    }
```

Provider homes are copied snapshot-to-volume, but only the allowlisted session directories enter the portable archive. The filename scrub and redacted configuration are defense in depth; no secret value is printed.

- [ ] **Step 6: Implement deployment, verification, restore drill, and rollback**

Finish the transaction:

```powershell
    Set-Stage 'preserve-old'
    Docker rename $Container $preservedName

    Set-Stage 'deploy'
    $deployment = Join-Path $stateRoot 'deployment'
    New-Item -ItemType Directory -Path $deployment -Force | Out-Null
    Copy-Item (Join-Path $root 'docker\compose.volume-backed.yml') (Join-Path $deployment 'compose.volume-backed.yml') -Force
    Copy-Item (Join-Path $root 'docker\state-volumes.json') (Join-Path $deployment 'state-volumes.json') -Force
    @("MYPEOPLE_IMAGE=$candidateImage", "MYPEOPLE_SEED_PATH=$SeedPath") |
        Set-Content -LiteralPath (Join-Path $deployment '.env') -Encoding UTF8
    $deploymentWritten = $true
    & docker compose --env-file (Join-Path $deployment '.env') -f (Join-Path $deployment 'compose.volume-backed.yml') up -d
    if ($LASTEXITCODE -ne 0) { throw 'docker compose up failed' }

    Set-Stage 'verify'
    & (Join-Path $root 'windows\Start-MyPeople.ps1') -NoBrowser
    if ($LASTEXITCODE -ne 0) { throw 'Launcher verification failed' }
    $pidOne = (& docker exec mypeople ps -o comm= -p 1).Trim()
    if ($pidOne -eq 'sleep') { throw 'PID 1 still uses sleep infinity' }
    $after = Invoke-MyPeopleDocker -Arguments @(
        'exec','mypeople','sh','-lc',
        'sha256sum /home/mp/mypeople/todos/board.v2.json /home/mp/mypeople/run/roster.json'
    ) -Capture
    $after | Set-Content -LiteralPath (Join-Path $transactionRoot 'after-state.sha256') -Encoding ASCII
    if ($before.Trim() -ne $after.Trim()) { throw 'Board or roster hash changed during migration' }

    $state.archiveSha256 = Get-MyPeopleSha256 (Join-Path $transactionRoot 'portable-state.tar.gz')
    $state.beforeState = $before
    $state.afterState = $after
    $state.excludedAuthPatterns = @('*auth*','*credential*','*token*','*.key')
    Set-Stage 'restore-drill'
    & (Join-Path $root 'windows\Test-MyPeopleDockerRestore.ps1') -Image $candidateImage -Manifest $transactionPath
    if ($LASTEXITCODE -ne 0) { throw 'Restore drill failed' }
    Set-Stage 'complete'
    Write-Output "MIGRATION PASS: $transactionPath"
} catch {
    $state.rollbackAttempted = $true
    $state.failure = $_.Exception.Message
    Write-MyPeopleTransaction -Path $transactionPath -State $state
    if ($deploymentWritten) {
        $activeEnvironment = Join-Path $stateRoot 'deployment\.env'
        if (Test-Path -LiteralPath $activeEnvironment) {
            Move-Item -LiteralPath $activeEnvironment -Destination "$activeEnvironment.failed-$stamp" -Force
        }
    }
    Invoke-MyPeopleRollback -PreservedName $preservedName
    throw
} finally {
    if (Test-Path -LiteralPath $lockPath) { Remove-Item -LiteralPath $lockPath -Force }
}
```

- [ ] **Step 7: Run the static tests and the no-mutation dry run**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File verify\Test-WindowsDockerMigration.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File windows\Migrate-MyPeopleDockerState.ps1
git diff --check
```

Expected: contract test passes; dry run prints `DRY RUN PASS`; live container name, mounts, and running state remain unchanged.

- [ ] **Step 8: Commit the guarded migration**

```powershell
git add windows/Migrate-MyPeopleDockerState.ps1 verify/Test-WindowsDockerMigration.ps1
git commit -m "Add guarded Docker state migration"
```

### Task 5: Prove the portable backup in isolated restore volumes

**Files:**
- Modify: `verify/Test-WindowsDockerMigration.ps1`
- Create: `windows/Test-MyPeopleDockerRestore.ps1`

- [ ] **Step 1: Add the failing restore-drill contract**

Append to `verify/Test-WindowsDockerMigration.ps1`:

```powershell
$restore = Get-Content -Raw (Join-Path $root 'windows\Test-MyPeopleDockerRestore.ps1') -ErrorAction SilentlyContinue
foreach ($required in @(
    'mypeople-restore-',
    'MYPEOPLE_SUPPRESS_BOSS_NOTIFY=1',
    'MYPEOPLE_DISABLE_PROVIDER_LAUNCH=1',
    'board.v2.json',
    'roster.json',
    'portable-state.tar.gz'
)) {
    if ($restore -notmatch [regex]::Escape($required)) { throw "Missing restore behavior: $required" }
}
if ($restore -match [regex]::Escape('docker volume rm')) { throw 'Restore drill must retain evidence volumes' }
```

- [ ] **Step 2: Run the test and verify the restore script is missing**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File verify\Test-WindowsDockerMigration.ps1
```

Expected: failure on `mypeople-restore-`.

- [ ] **Step 3: Implement the isolated restore drill**

Create `windows/Test-MyPeopleDockerRestore.ps1`:

```powershell
param(
    [Parameter(Mandatory)][string]$Image,
    [Parameter(Mandatory)][string]$Manifest
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Import-Module (Join-Path $PSScriptRoot 'MyPeople.DockerMigration.psm1') -Force
$record = Get-Content -Raw -LiteralPath $Manifest | ConvertFrom-Json
$backupRoot = Split-Path $Manifest -Parent
$archive = Join-Path $backupRoot 'portable-state.tar.gz'
if (-not (Test-Path -LiteralPath $archive)) { throw "Portable archive missing: $archive" }
if ((Get-MyPeopleSha256 $archive) -ne $record.archiveSha256) { throw 'Portable archive hash mismatch' }

$contract = Get-MyPeopleVolumeContract -Root $root
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$container = "mypeople-restore-$stamp"
$restoreVolumes = [ordered]@{}
foreach ($volume in $contract.Keys) {
    $name = "mypeople-restore-$stamp-$volume"
    Invoke-MyPeopleDocker -Arguments @('volume','create',$name)
    $restoreVolumes[$volume] = $name
}

$args = @(
    'create','--name',$container,
    '--user','root',
    '--env','MYPEOPLE_SUPPRESS_BOSS_NOTIFY=1',
    '--env','MYPEOPLE_DISABLE_PROVIDER_LAUNCH=1'
)
foreach ($volume in $contract.Keys) {
    $args += @('--mount',"type=volume,src=$($restoreVolumes[$volume]),dst=/mnt/$volume")
}
$args += @($Image,'sleep','infinity')
Invoke-MyPeopleDocker -Arguments $args

try {
    Invoke-MyPeopleDocker -Arguments @('start',$container)
    Invoke-MyPeopleDocker -Arguments @('cp',$archive,"${container}:/tmp/portable-state.tar.gz")
    $restoreCommand = @'
set -eu
mkdir -p /restore
tar -C /restore -xzf /tmp/portable-state.tar.gz
copy_tree() { [ ! -e "$1" ] || cp -a "$1"/. "$2"/; }
copy_tree /restore/home/mp/mypeople/todos /mnt/mypeople-todos
copy_tree /restore/home/mp/mypeople/run /mnt/mypeople-run
copy_tree /restore/home/mp/mypeople/status /mnt/mypeople-status
copy_tree /restore/home/mp/recordings /mnt/mypeople-recordings
copy_tree /restore/home/mp/.codex /mnt/mypeople-codex
copy_tree /restore/home/mp/.claude /mnt/mypeople-claude
python3 -m json.tool /mnt/mypeople-todos/board.v2.json >/dev/null
python3 -m json.tool /mnt/mypeople-run/roster.json >/dev/null
'@
    Invoke-MyPeopleDocker -Arguments @('exec',$container,'sh','-lc',$restoreCommand)
    $actual = Invoke-MyPeopleDocker -Arguments @(
        'exec',$container,'sh','-lc',
        'sha256sum /mnt/mypeople-todos/board.v2.json /mnt/mypeople-run/roster.json'
    ) -Capture
    $expectedHashes = @($record.beforeState -split "`r?`n" | ForEach-Object { ($_ -split '\s+')[0] })
    $actualHashes = @($actual -split "`r?`n" | ForEach-Object { ($_ -split '\s+')[0] })
    if (($expectedHashes -join ',') -ne ($actualHashes -join ',')) { throw 'Restored board or roster hash mismatch' }
    $evidence = [ordered]@{ container=$container; image=$Image; volumes=$restoreVolumes; hashes=$actualHashes; status='pass' }
    $evidence | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $backupRoot 'restore-drill.json') -Encoding UTF8
    Write-Output "PASS isolated Docker restore drill; evidence volumes retained: $($restoreVolumes.Values -join ', ')"
} finally {
    & docker rm -f $container *> $null
}
```

The drill removes only its disposable container. It intentionally retains the timestamped restore volumes as evidence until a separate, human-approved cleanup.

- [ ] **Step 4: Run the static restore contract**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File verify\Test-WindowsDockerMigration.ps1
git diff --check
```

Expected: PASS Docker migration contract, names, and redaction.

- [ ] **Step 5: Commit the restore drill**

```powershell
git add windows/Test-MyPeopleDockerRestore.ps1 verify/Test-WindowsDockerMigration.ps1
git commit -m "Add isolated Docker restore drill"
```

### Task 6: Make the one-click launcher recover the pinned deployment

**Files:**
- Modify: `verify/test_windows_launcher.py`
- Modify: `windows/Start-MyPeople.ps1`
- Modify: `windows/Install-MyPeopleShortcut.ps1`

- [ ] **Step 1: Extend the launcher contract before implementation**

Add a new test to `verify/test_windows_launcher.py`:

```python
def test_launcher_recovers_the_pinned_volume_backed_deployment(self):
    text = (ROOT / "windows" / "Start-MyPeople.ps1").read_text(encoding="utf-8")
    self.assertIn("MyPeople\\deployment", text)
    self.assertIn("compose.volume-backed.yml", text)
    self.assertIn("--env-file", text)
    self.assertIn("docker compose", text)
    self.assertNotIn("compose down", text)
    self.assertNotIn("volume rm", text)
```

Update the existing assertions so the volume-backed path expects Compose before provider rehydration, while the legacy fallback still contains `docker start mypeople`. Keep the checks that provider validation happens before `mypeople up --detach`.

- [ ] **Step 2: Run the test and verify it fails**

```powershell
python verify\test_windows_launcher.py
```

Expected: failure because the current launcher does not reference the deployment directory or Compose.

- [ ] **Step 3: Add pinned Compose recovery before container inspection**

In `windows/Start-MyPeople.ps1`, after Docker Desktop is ready and before `docker inspect mypeople`, add:

```powershell
$deploymentDirectory = Join-Path $env:LOCALAPPDATA 'MyPeople\deployment'
$composePath = Join-Path $deploymentDirectory 'compose.volume-backed.yml'
$environmentPath = Join-Path $deploymentDirectory '.env'
$hasDeployment = (Test-Path -LiteralPath $composePath) -and (Test-Path -LiteralPath $environmentPath)

if ($hasDeployment) {
    Write-LauncherLog "docker compose pinned deployment up"
    & docker compose --env-file $environmentPath -f $composePath up -d
    if ($LASTEXITCODE -ne 0) { throw 'Pinned docker compose up failed.' }
} else {
    & docker inspect mypeople *> $null
    if ($LASTEXITCODE -ne 0) {
        throw 'The mypeople container and pinned deployment manifest are both missing.'
    }
    $running = (& docker inspect -f '{{.State.Running}}' mypeople 2>$null).Trim()
    if ($running -ne 'true') {
        Write-LauncherLog 'docker start mypeople'
        & docker start mypeople | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'docker start mypeople failed.' }
    }
}
```

Leave provider-profile activation, `mypeople up --detach`, health gates, and browser opening in their existing order. The compatibility call is harmless because `bin/mypeople` now sees the foreground supervisor already alive.

- [ ] **Step 4: Install deployment artifacts without overwriting the environment**

In `windows/Install-MyPeopleShortcut.ps1`, after copying launcher files, add:

```powershell
$deploymentDirectory = Join-Path $env:LOCALAPPDATA 'MyPeople\deployment'
$environmentPath = Join-Path $deploymentDirectory '.env'
if (Test-Path -LiteralPath $environmentPath) {
    New-Item -ItemType Directory -Path $deploymentDirectory -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path (Split-Path $PSScriptRoot -Parent) 'docker\compose.volume-backed.yml') -Destination $deploymentDirectory -Force
    Copy-Item -LiteralPath (Join-Path (Split-Path $PSScriptRoot -Parent) 'docker\state-volumes.json') -Destination $deploymentDirectory -Force
}
```

The installer must never create, replace, print, or copy `.env`; only the migration/upgrade transaction owns it.

- [ ] **Step 5: Run focused launcher tests**

```powershell
python verify\test_windows_launcher.py
powershell -NoProfile -ExecutionPolicy Bypass -File verify\Test-WindowsDockerMigration.ps1
git diff --check
```

Expected: all launcher and migration contract tests pass.

- [ ] **Step 6: Commit launcher recovery**

```powershell
git add windows/Start-MyPeople.ps1 windows/Install-MyPeopleShortcut.ps1 verify/test_windows_launcher.py
git commit -m "Start the pinned volume-backed deployment"
```

### Task 7: Document and verify the operator contract before live mutation

**Files:**
- Modify: `README.md`
- Modify: `docs/USER-MANUAL.md`
- Modify: `verify/verify.sh`

- [ ] **Step 1: Document the exact dry-run and execution commands**

Add an English section named `Durable Docker state` to both documents:

```powershell
# Read-only Docker preflight plus local transaction plan
powershell -NoProfile -ExecutionPolicy Bypass -File windows\Migrate-MyPeopleDockerState.ps1

# Explicit live migration after reviewing the dry-run record
powershell -NoProfile -ExecutionPolicy Bypass -File windows\Migrate-MyPeopleDockerState.ps1 -Execute
```

Document all seven volume names, the preserved `mypeople-pre-volumes-<timestamp>` container, snapshot and candidate images, `%LOCALAPPDATA%\MyPeople\backups\docker-migration\<timestamp>`, `%LOCALAPPDATA%\MyPeople\deployment`, restore evidence volumes, automatic rollback, and the desktop shortcut. State prominently:

```text
Never run docker compose down -v or delete MyPeople volumes as a startup or recovery step.
Cloudflare memory remains disabled until a separate post-migration activation cycle passes.
```

- [ ] **Step 2: Ensure the focused tests are registered exactly once**

Verify `verify/verify.sh` contains one invocation each:

```bash
python3 "$VERIFY/test_docker_persistence.py"
python3 "$VERIFY/test_runtime_supervisor.py"
```

- [ ] **Step 3: Run all pre-live contracts**

```powershell
python verify\test_docker_persistence.py
python verify\test_runtime_supervisor.py
python verify\test_boss_supervisor_backend.py
python verify\test_windows_launcher.py
powershell -NoProfile -ExecutionPolicy Bypass -File verify\Test-WindowsDockerMigration.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File windows\Migrate-MyPeopleDockerState.ps1
git diff --check
```

Expected: every contract passes; the migration reports `DRY RUN PASS`; `docker inspect mypeople` still shows the original container and only the seed bind.

- [ ] **Step 4: Review the dry-run transaction**

Open the newest `%LOCALAPPDATA%\MyPeople\backups\docker-migration\<timestamp>\transaction.json` and verify:

```text
stage = planned
execute = false
container = mypeople
volumes = exactly seven approved names
rollbackAttempted = false
```

Confirm no secret values appear in the record.

- [ ] **Step 5: Commit documentation and pre-live registration**

```powershell
git add README.md docs/USER-MANUAL.md verify/verify.sh
git commit -m "Document durable Docker recovery"
```

### Task 8: Execute the live migration and rehearse rollback without deleting evidence

**Files:**
- Runtime evidence only under `%LOCALAPPDATA%\MyPeople\backups\docker-migration\<timestamp>`
- No source edits unless verification exposes a defect; defects return to the relevant TDD task.

- [ ] **Step 1: Confirm an idle board and capture the immutable baseline**

Do not run the full verifier while Boss or workers are changing cards. When the board is idle, run:

```powershell
docker inspect mypeople > "$env:LOCALAPPDATA\MyPeople\pre-volume-container-inspect.json"
docker exec mypeople sh -lc "sha256sum /home/mp/mypeople/todos/board.v2.json /home/mp/mypeople/run/roster.json"
docker exec mypeople sh -lc "find /home/mp/mypeople/todos -type f | wc -l; find /home/mp/recordings -type f | wc -l; find /home/mp/.codex/sessions -type f 2>/dev/null | wc -l; find /home/mp/.claude/projects -type f 2>/dev/null | wc -l"
docker exec mypeople python3 -c "import json; r=json.load(open('/home/mp/mypeople/run/roster.json')); print([(x.get('agent_id'),x.get('backend'),x.get('model'),x.get('provider_profile'),x.get('session_id')) for x in r])"
docker exec mypeople /home/mp/mypeople/bin/mp status
docker inspect -f "{{json .Mounts}}" mypeople
```

Expected: Boss and Nightwatch are alive; the only mount is the read-only seed bind; the two hashes are recorded.

- [ ] **Step 2: Execute the explicit migration transaction**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File windows\Migrate-MyPeopleDockerState.ps1 -Execute
```

Expected: `MIGRATION PASS` with a transaction path. If any stage fails, the script automatically starts the untouched original container and reports the failure record.

- [ ] **Step 3: Verify mounts, init, service ownership, state, and UI**

```powershell
docker inspect -f "{{json .Mounts}}" mypeople
docker exec mypeople ps -o pid,ppid,stat,comm,args -p 1
docker exec mypeople /home/mp/mypeople/bin/mp status
docker exec mypeople sh -lc "sha256sum /home/mp/mypeople/todos/board.v2.json /home/mp/mypeople/run/roster.json"
docker exec mypeople sh -lc "find /home/mp/mypeople/todos -type f | wc -l; find /home/mp/recordings -type f | wc -l; find /home/mp/.codex/sessions -type f 2>/dev/null | wc -l; find /home/mp/.claude/projects -type f 2>/dev/null | wc -l"
docker exec mypeople python3 -c "import json; r=json.load(open('/home/mp/mypeople/run/roster.json')); print([(x.get('agent_id'),x.get('backend'),x.get('model'),x.get('provider_profile'),x.get('session_id')) for x in r])"
powershell -NoProfile -ExecutionPolicy Bypass -File windows\Start-MyPeople.ps1 -NoBrowser
```

Expected:

```text
seven named state volumes plus the read-only seed bind
PID 1 is Docker init, not sleep
one runtime supervisor and one Boss supervisor
Boss and Nightwatch alive with their prior identity/model/profile fields
board and roster hashes equal the baseline
HTTP 200 from Priorities and HUD; terminal port reachable
```

Open `%LOCALAPPDATA%\MyPeople\backups\docker-migration\<timestamp>\restore-drill.json` and confirm `status: pass` and seven timestamped evidence volumes.

- [ ] **Step 4: Rehearse rollback by renaming, never by deleting**

Read `preservedContainer` from the successful transaction, then run:

```powershell
$record = Get-Content -Raw "$env:LOCALAPPDATA\MyPeople\backups\docker-migration\<timestamp>\transaction.json" | ConvertFrom-Json
$preserved = [string]$record.preservedContainer
$candidate = "mypeople-volume-backed-rehearsal-$($record.id)"
docker stop mypeople
docker rename mypeople $candidate
docker rename $preserved mypeople
docker start mypeople
docker exec mypeople /home/mp/mypeople/bin/mypeople up --detach
Invoke-WebRequest -UseBasicParsing http://localhost:9933/health -TimeoutSec 10
Invoke-WebRequest -UseBasicParsing http://localhost:9900/health -TimeoutSec 10
docker exec mypeople /home/mp/mypeople/bin/mp status
```

Expected: the old container serves the same board and health endpoints. Restore the new deployment:

```powershell
docker stop mypeople
docker rename mypeople $preserved
docker rename $candidate mypeople
powershell -NoProfile -ExecutionPolicy Bypass -File windows\Start-MyPeople.ps1 -NoBrowser
```

Expected: volume-backed MyPeople returns healthy. Keep both containers, all live volumes, restore evidence volumes, snapshot image, and backup.

- [ ] **Step 5: Run focused tests and the complete verifier**

```powershell
python verify\test_docker_persistence.py
python verify\test_runtime_supervisor.py
python verify\test_windows_launcher.py
powershell -NoProfile -ExecutionPolicy Bypass -File verify\Test-WindowsDockerMigration.ps1
docker exec mypeople bash /home/mp/mypeople/verify/verify.sh
git diff --check
git status --short --branch
```

Expected: focused tests pass; the full verifier completes successfully; no unexpected source edits or runtime evidence are staged.

- [ ] **Step 6: Push the verified public source**

```powershell
git log --oneline --decorate -10
git push --dry-run origin HEAD:main
git push origin main
```

Expected: `origin/main` contains the English, sanitized Docker implementation and documentation. Local backups, transaction logs, provider sessions, recordings, and deployment `.env` remain outside Git.

### Task 9: Close the Docker cycle and open the bounded Cloudflare-memory cycle

**Files:**
- Canonical Roadmap OS evidence under `%USERPROFILE%\Documents\ObsidianBrain\roadmap\`
- A separate Cloudflare activation spec and plan; no memory activation edits belong in this Docker branch.

- [ ] **Step 1: Record only non-secret Docker evidence in the canonical project record**

Create an agent-run/cycle record containing:

```text
source commit and pushed commit
transaction ID and protected local evidence path
snapshot and candidate image tags
preserved container name
seven live volume names
restore-drill status
rollback-rehearsal status
focused and full verification results
```

Do not copy backup content, hashes of secret files, provider homes, tokens, recordings, or `.env` into Obsidian or Git.

- [ ] **Step 2: Prove memory remained disabled throughout Docker migration**

Run:

```powershell
rg -n '"memory"\s*:|memory\.enabled|MYPEOPLE_MEMORY' examples bin windows
docker exec mypeople sh -lc "find /home/mp/mypeople -path '*project*profile*' -type f -maxdepth 6 -print"
```

Expected: every active ProjectProfile still resolves to `memory.enabled=false`, and no Cloudflare credential was added to Compose, named volumes, backups, transaction logs, or Git.

- [ ] **Step 3: Start the separate Cloudflare activation design**

Use brainstorming and then writing-plans for a new cycle with this fixed acceptance contract:

```text
project slug: project-factory
transport: external Cloudflare MCP
secret source: Windows DPAPI
container delivery: tmpfs only
operation: read-only recall
topK: at most 3
hops: 0
default: disabled
no-question test: zero network calls
provider output: provenance attached
isolation test: no cross-project recall
cost: measured when exposed, otherwise explicitly estimated
rollback: disable feature flag and remove tmpfs injection
```

Do not enable write-memory tools or global recall in the first real profile. The Cloudflare cycle begins only after the Docker transaction, restore drill, launcher recovery, and rollback rehearsal are all green.

- [ ] **Step 4: Mark the Docker work complete only with all evidence present**

Completion requires:

```text
volume-backed container healthy after a desktop-launcher restart
old container and snapshot retained
portable backup hash verified
isolated restore drill passed
rollback rehearsal passed
public Git pushed in English with no secrets
Cloudflare memory still disabled
separate bounded memory activation cycle created
```
