param(
    [switch]$Execute,
    [ValidatePattern('^mypeople$')][string]$Container = 'mypeople',
    [string]$SeedPath = $env:MYPEOPLE_SEED_PATH,
    [string]$ResumeManifest,
    [int]$MinimumFreeGiB = 16
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Import-Module (Join-Path $PSScriptRoot 'MyPeople.DockerMigration.psm1') -Force

$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$stateRoot = Join-Path $env:LOCALAPPDATA 'MyPeople'
$transactionRoot = Join-Path $stateRoot "backups\docker-migration\$stamp"
$transactionPath = Join-Path $transactionRoot 'transaction.json'
$lockPath = Join-Path $stateRoot 'docker-migration.lock'
$resolvedResumeManifest = $null
$resumeState = $null
if ($ResumeManifest) {
    $resolvedResumeManifest = (Resolve-Path -LiteralPath $ResumeManifest).Path
    $allowedResumeRoot = [IO.Path]::GetFullPath(
        (Join-Path $stateRoot 'backups\docker-migration')
    ).TrimEnd('\') + '\'
    $resolvedFullPath = [IO.Path]::GetFullPath($resolvedResumeManifest)
    if (-not $resolvedFullPath.StartsWith($allowedResumeRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Resume manifest must be inside the MyPeople Docker migration backup root'
    }
    $resumeState = Get-Content -Raw -LiteralPath $resolvedResumeManifest | ConvertFrom-Json
}
$preservedName = "mypeople-pre-volumes-$stamp"
$snapshotImage = if ($resumeState) {
    [string]$resumeState.snapshotImage
} else {
    "mypeople-node:pre-volumes-$stamp"
}
$gitSha = (& git -C $root rev-parse --short=12 HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or -not $gitSha) { throw 'Unable to resolve the source commit' }
$candidateImage = "mypeople-node:volume-backed-$gitSha"
$contract = Get-MyPeopleVolumeContract -Root $root

$script:state = [ordered]@{
    id = $stamp
    stage = 'preflight'
    execute = [bool]$Execute
    container = $Container
    preservedContainer = $preservedName
    snapshotImage = $snapshotImage
    candidateImage = $candidateImage
    sourceCommit = $gitSha
    volumes = @($contract.Keys)
    volumeState = [ordered]@{}
    backup = $transactionRoot
    resumedFrom = $resolvedResumeManifest
    rollbackAttempted = $false
}
$lockCreated = $false
$mutationStarted = $false
$deploymentWritten = $false

function Set-Stage {
    param([Parameter(Mandatory)][string]$Name)
    $script:state.stage = $Name
    Write-MyPeopleTransaction -Path $transactionPath -State $script:state
}

function Docker {
    param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments)
    Invoke-MyPeopleDocker -Arguments $Arguments
}

function Invoke-LauncherVerification {
    param([Parameter(Mandatory)][string]$FailureMessage)
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'windows\Start-MyPeople.ps1') -NoBrowser -NonInteractive
        $launcherExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($launcherExitCode -ne 0) { throw $FailureMessage }
}

function Test-ContainerExists {
    param([Parameter(Mandatory)][string]$Name)
    return Test-MyPeopleDockerObject -Type container -Name $Name
}

function Get-StableStateSignature {
    param([Parameter(Mandatory)][string]$Name)
    $boardLine = Invoke-MyPeopleDocker -Arguments @(
        'exec', $Name, 'sha256sum', '/home/mp/mypeople/todos/board.v2.json'
    ) -Capture
    $boardHash = ($boardLine.Trim() -split '\s+')[0]
    $rosterJson = Invoke-MyPeopleDocker -Arguments @(
        'exec', $Name, 'cat', '/home/mp/mypeople/run/roster.json'
    ) -Capture
    $rosterHash = Get-MyPeopleStableRosterHash -Json $rosterJson
    return '{0}:{1}' -f $boardHash, $rosterHash
}

function Assert-Preflight {
    if (Test-Path -LiteralPath $lockPath) {
        throw "Migration lock already exists: $lockPath"
    }
    if (-not (Test-ContainerExists $Container)) {
        throw "Expected container not found: $Container"
    }
    $running = (& docker.exe inspect -f '{{.State.Running}}' $Container).Trim()
    if ($running -ne 'true') { throw 'The live container must be running for preflight' }

    if (-not $script:SeedPath) {
        $mounts = (& docker.exe inspect -f '{{json .Mounts}}' $Container | ConvertFrom-Json)
        $seedMount = @($mounts | Where-Object Destination -eq '/home/mp/mypeople.seed.md') |
            Select-Object -First 1
        $script:SeedPath = [string]$seedMount.Source
    }
    if (-not $script:SeedPath -or -not (Test-Path -LiteralPath $script:SeedPath)) {
        throw "Seed file not found: $script:SeedPath"
    }
    if ($Execute -and (& git -C $root status --porcelain)) {
        throw 'Source repository must be clean before building the candidate image'
    }

    $driveName = [IO.Path]::GetPathRoot($stateRoot).Substring(0, 1)
    $drive = Get-PSDrive -Name $driveName
    if (($drive.Free / 1GB) -lt $MinimumFreeGiB) {
        throw "Need at least $MinimumFreeGiB GiB free"
    }
    Invoke-WebRequest -UseBasicParsing -Uri 'http://localhost:9933/health' -TimeoutSec 5 | Out-Null
    Invoke-WebRequest -UseBasicParsing -Uri 'http://localhost:9900/health' -TimeoutSec 5 | Out-Null
    $status = Invoke-MyPeopleDocker -Arguments @(
        'exec', $Container, '/home/mp/mypeople/bin/mp', 'status'
    ) -Capture
    if ($status -notmatch 'main:Boss \[alive\]' -or $status -notmatch 'nightwatch:Nightwatch \[alive\]') {
        throw 'Boss and Nightwatch must be alive before migration'
    }
}

function Remove-StaleRuntimePidFiles {
    param([Parameter(Mandatory)][string]$StagingContainer)
    Docker exec $StagingContainer sh -lc "find /mnt/mypeople-run -maxdepth 1 -type f -name '*.pid' -delete"
}

try {
    Assert-Preflight
    New-Item -ItemType Directory -Path $transactionRoot -Force | Out-Null
    $principal = $env:USERNAME + ':(OI)(CI)F'
    & icacls $transactionRoot /inheritance:r /grant:r $principal | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Unable to protect the migration evidence directory' }
    Set-Content -LiteralPath $lockPath -Value $stamp -Encoding ASCII
    $lockCreated = $true
    Set-Stage 'planned'

    if (-not $Execute) {
        Write-Output "DRY RUN PASS: plan recorded at $transactionPath"
        return
    }

    if ($resumeState) {
        Set-Stage 'resume-validate'
        if ($resumeState.stage -ne 'candidate-image' -or $resumeState.rollbackStatus -ne 'pass') {
            throw 'Resume manifest is not a rolled-back candidate-image transaction'
        }
        if (-not (Test-MyPeopleDockerObject -Type image -Name $snapshotImage)) {
            throw "Resume snapshot image not found: $snapshotImage"
        }
        $resumeBeforePath = Join-Path (Split-Path $resolvedResumeManifest -Parent) 'before-state.sha256'
        if (-not (Test-Path -LiteralPath $resumeBeforePath)) {
            throw 'Resume transaction has no before-state hash evidence'
        }
        $before = Get-Content -Raw -LiteralPath $resumeBeforePath
        $beforeStable = [string]$resumeState.beforeStableState
        if (-not $beforeStable) { throw 'Resume transaction has no stable state signature' }
        $currentStable = Get-StableStateSignature -Name $Container
        if ($currentStable -ne $beforeStable) {
            throw 'Live state changed since the reusable snapshot was captured'
        }
        $before | Set-Content -LiteralPath (Join-Path $transactionRoot 'before-state.sha256') -Encoding ASCII
        $script:state.beforeStableState = $beforeStable
        Write-MyPeopleTransaction -Path $transactionPath -State $script:state
        $mutationStarted = $true
        Docker stop --time 30 $Container
        Set-Stage 'snapshot-reused'
    } else {
        Set-Stage 'quiesce'
        $before = Invoke-MyPeopleDocker -Arguments @(
            'exec', $Container, 'sh', '-lc',
            'sha256sum /home/mp/mypeople/todos/board.v2.json /home/mp/mypeople/run/roster.json'
        ) -Capture
        $beforeStable = Get-StableStateSignature -Name $Container
        $before | Set-Content -LiteralPath (Join-Path $transactionRoot 'before-state.sha256') -Encoding ASCII
        $script:state.beforeStableState = $beforeStable
        Write-MyPeopleTransaction -Path $transactionPath -State $script:state
        $mutationStarted = $true
        Docker stop --time 30 $Container

        Set-Stage 'snapshot'
        Docker commit $Container $snapshotImage
    }

    Set-Stage 'candidate-image'
    $candidateContainer = "mypeople-candidate-$stamp"
    Docker create --name $candidateContainer --user root $snapshotImage sleep infinity
    try {
        Docker start $candidateContainer
        foreach ($path in @('bin', 'verify', 'memory-gateway', 'plugins', 'docs', 'docker')) {
            $source = Join-Path $root $path
            if (-not (Test-Path -LiteralPath $source)) { throw "Candidate source path missing: $source" }
            Docker cp $source ('{0}:/home/mp/mypeople/' -f $candidateContainer)
        }
        foreach ($path in @('install.sh', 'README.md')) {
            $source = Join-Path $root $path
            Docker cp $source ('{0}:/home/mp/mypeople/{1}' -f $candidateContainer, $path)
        }
        Docker exec -u root $candidateContainer chown -R mp:mp /home/mp/mypeople
        Docker exec -u root $candidateContainer sh -lc "find /home/mp/mypeople/bin -maxdepth 1 -type f -exec chmod 0755 {} +; chmod 0755 /home/mp/mypeople/install.sh"
        Docker exec $candidateContainer bash -lc 'cd /home/mp/mypeople && python3 verify/test_docker_persistence.py && python3 verify/test_runtime_supervisor.py && python3 verify/test_boss_supervisor_backend.py'
        Docker commit $candidateContainer $candidateImage
    } finally {
        & docker.exe rm -f $candidateContainer *> $null
    }

    Set-Stage 'create-volumes'
    foreach ($volume in $contract.Keys) {
        if (Test-MyPeopleDockerObject -Type volume -Name $volume) {
            $script:state.volumeState[$volume] = 'reused-empty-required'
        } else {
            Docker volume create $volume
            $script:state.volumeState[$volume] = 'created'
        }
    }
    Write-MyPeopleTransaction -Path $transactionPath -State $script:state

    Set-Stage 'seed-volumes'
    $staging = "mypeople-seed-$stamp"
    $createArgs = @('create', '--name', $staging, '--user', 'root')
    foreach ($volume in $contract.Keys) {
        $createArgs += @('--mount', "type=volume,src=$volume,dst=/mnt/$volume")
    }
    $createArgs += @($snapshotImage, 'sleep', 'infinity')
    Invoke-MyPeopleDocker -Arguments $createArgs
    Docker start $staging
    try {
        foreach ($entry in $contract.GetEnumerator()) {
            $target = "/mnt/$($entry.Key)"
            $found = Invoke-MyPeopleDocker -Arguments @(
                'exec', $staging, 'sh', '-lc',
                "find '$target' -mindepth 1 -maxdepth 1 -print -quit"
            ) -Capture
            if ($found.Trim()) { throw "Refusing to seed non-empty volume: $($entry.Key)" }
        }
        foreach ($entry in $contract.GetEnumerator()) {
            $source = $entry.Value
            $target = "/mnt/$($entry.Key)"
            Docker exec $staging sh -lc "mkdir -p '$target' && if [ -d '$source' ]; then cp -a '$source/.' '$target/'; fi"
        }
        Remove-StaleRuntimePidFiles $staging
    } finally {
        & docker.exe rm -f $staging *> $null
    }

    Set-Stage 'portable-backup'
    $archiveContainer = "mypeople-archive-$stamp"
    Docker create --name $archiveContainer --user root $snapshotImage sleep infinity
    try {
        Docker start $archiveContainer
        $archiveCommand = @'
set -eu
mkdir -p /tmp/portable/home/mp/mypeople/run
mkdir -p /tmp/portable/home/mp/.codex /tmp/portable/home/mp/.claude
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
        Invoke-MyPeopleDocker -Arguments @(
            'exec', $archiveContainer, 'sh', '-lc', $archiveCommand
        )
        Docker cp ('{0}:/tmp/portable-state.tar.gz' -f $archiveContainer) (Join-Path $transactionRoot 'portable-state.tar.gz')
        $config = Invoke-MyPeopleDocker -Arguments @(
            'exec', $archiveContainer, 'sh', '-lc',
            'cat /home/mp/.config/mypeople/queue.env'
        ) -Capture
        ConvertTo-MyPeopleRedactedConfig $config |
            Set-Content -LiteralPath (Join-Path $transactionRoot 'queue.env.redacted') -Encoding UTF8
    } finally {
        & docker.exe rm -f $archiveContainer *> $null
    }

    $script:state.archiveSha256 = Get-MyPeopleSha256 (Join-Path $transactionRoot 'portable-state.tar.gz')
    $script:state.beforeState = $before
    $script:state.excludedAuthPatterns = @('*auth*', '*credential*', '*token*', '*.key')
    Write-MyPeopleTransaction -Path $transactionPath -State $script:state

    Set-Stage 'preserve-old'
    Docker rename $Container $preservedName

    Set-Stage 'deploy'
    $deployment = Join-Path $stateRoot 'deployment'
    New-Item -ItemType Directory -Path $deployment -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $root 'docker\compose.volume-backed.yml') -Destination (Join-Path $deployment 'compose.volume-backed.yml') -Force
    Copy-Item -LiteralPath (Join-Path $root 'docker\state-volumes.json') -Destination (Join-Path $deployment 'state-volumes.json') -Force
    $composeSeedPath = $script:SeedPath -replace '\\', '/'
    $environmentPath = Join-Path $deployment '.env'
    [IO.File]::WriteAllLines(
        $environmentPath,
        @("MYPEOPLE_IMAGE=$candidateImage", "MYPEOPLE_SEED_PATH=$composeSeedPath"),
        [Text.UTF8Encoding]::new($false)
    )
    $deploymentWritten = $true
    Invoke-MyPeopleDocker -Arguments @(
        'compose', '--project-name', 'mypeople',
        '--env-file', $environmentPath,
        '-f', (Join-Path $deployment 'compose.volume-backed.yml'),
        'up', '-d'
    )

    Set-Stage 'verify'
    Invoke-LauncherVerification -FailureMessage 'Launcher verification failed'
    $pidOne = (& docker.exe exec mypeople ps -o comm= -p 1).Trim()
    if ($LASTEXITCODE -ne 0 -or $pidOne -eq 'sleep') {
        throw "PID 1 is not Docker init: $pidOne"
    }
    $processes = Invoke-MyPeopleDocker -Arguments @(
        'exec', 'mypeople', 'ps', '-eo', 'args='
    ) -Capture
    if (([regex]::Matches($processes, '(?m)^/bin/bash /home/mp/mypeople/bin/runtime-supervisor\.sh$')).Count -ne 1) {
        throw 'Expected exactly one runtime supervisor'
    }
    if (([regex]::Matches($processes, '(?m)^bash /home/mp/mypeople/bin/boss-supervisor\.sh$')).Count -ne 1) {
        throw 'Expected exactly one Boss supervisor'
    }
    $after = Invoke-MyPeopleDocker -Arguments @(
        'exec', 'mypeople', 'sh', '-lc',
        'sha256sum /home/mp/mypeople/todos/board.v2.json /home/mp/mypeople/run/roster.json'
    ) -Capture
    $afterStable = Get-StableStateSignature -Name 'mypeople'
    $after | Set-Content -LiteralPath (Join-Path $transactionRoot 'after-state.sha256') -Encoding ASCII
    if ($beforeStable -ne $afterStable) {
        throw 'Board content or stable roster identity changed during migration'
    }
    $script:state.afterState = $after
    $script:state.afterStableState = $afterStable
    Write-MyPeopleTransaction -Path $transactionPath -State $script:state

    Set-Stage 'restore-drill'
    & (Join-Path $root 'windows\Test-MyPeopleDockerRestore.ps1') -Image $candidateImage -Manifest $transactionPath
    if ($LASTEXITCODE -ne 0) { throw 'Restore drill failed' }

    Set-Stage 'complete'
    Write-Output "MIGRATION PASS: $transactionPath"
} catch {
    $failureRecord = $_
    $script:state.failure = $failureRecord.Exception.Message
    if (Test-Path -LiteralPath $transactionRoot) {
        Write-MyPeopleTransaction -Path $transactionPath -State $script:state
    }
    if ($deploymentWritten) {
        $activeEnvironment = Join-Path $stateRoot 'deployment\.env'
        if (Test-Path -LiteralPath $activeEnvironment) {
            Move-Item -LiteralPath $activeEnvironment -Destination "$activeEnvironment.failed-$stamp" -Force
        }
    }
    if ($Execute -and $mutationStarted) {
        $script:state.rollbackAttempted = $true
        try {
            Invoke-MyPeopleRollback -PreservedName $preservedName
            Invoke-LauncherVerification -FailureMessage 'Rollback launcher verification failed'
            $script:state.rollbackStatus = 'pass'
        } catch {
            $script:state.rollbackStatus = 'failed'
            $script:state.rollbackFailure = $_.Exception.Message
        }
        Write-MyPeopleTransaction -Path $transactionPath -State $script:state
    }
    throw $failureRecord
} finally {
    if ($lockCreated -and (Test-Path -LiteralPath $lockPath)) {
        Remove-Item -LiteralPath $lockPath -Force
    }
}
