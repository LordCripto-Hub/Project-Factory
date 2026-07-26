param(
    [Parameter(Mandatory)][string]$CandidateImage,
    [Parameter(Mandatory)][string]$VerificationReceipt,
    [switch]$Execute,
    [ValidateRange(1, 1024)][int]$MinimumFreeGiB = 4
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = Split-Path $PSScriptRoot -Parent
Import-Module (Join-Path $PSScriptRoot 'MyPeople.DockerMigration.psm1') -Force

if (-not $env:LOCALAPPDATA) { throw 'LOCALAPPDATA is required.' }
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$stateRoot = Join-Path $env:LOCALAPPDATA 'MyPeople'
$transactionRoot = Join-Path $stateRoot "backups\docker-recovery\$stamp"
$transactionPath = Join-Path $transactionRoot 'transaction.json'
$archivePath = Join-Path $transactionRoot 'portable-state.tar.gz'
$operationLockPath = Join-Path $stateRoot 'docker-operation.lock'
$deploymentRoot = Join-Path $stateRoot 'deployment'
$environmentPath = Join-Path $deploymentRoot '.env'
$composePath = Join-Path $deploymentRoot 'compose.volume-backed.yml'
$reviewedCompose = Join-Path $root 'docker\compose.volume-backed.yml'
$contract = Get-MyPeopleVolumeContract -Root $root
$operationLock = $null
$helper = "mypeople-recovery-backup-$stamp"
$helperCreated = $false
$deploymentFilesChanged = $false
$deploymentMutationStarted = $false
$oldEnvironment = $null
$oldCompose = $null

$script:state = [ordered]@{
    schemaVersion = 1
    id = $stamp
    stage = 'preflight'
    mode = if ($Execute) { 'execute' } else { 'plan-only' }
    sourceCommit = ''
    candidateImage = $CandidateImage
    candidateImageId = ''
    verificationReceipt = $VerificationReceipt
    deploymentImage = "mypeople-node:recovery-$stamp"
    volumes = @($contract.Keys)
    comparisonEnvironment = 'MYPEOPLE_MEMORY_COMPARISON_ENABLED=0'
    backupClassification = 'sensitive-local-restore-material'
    beforeBoardSha256 = $null
    beforeStableRosterSha256 = $null
    oldServiceRestored = $false
}

function Protect-RecoveryDirectory {
    param([Parameter(Mandatory)][string]$Path)
    New-Item -ItemType Directory -Path $Path -Force | Out-Null
    $principal = $env:USERNAME + ':(OI)(CI)F'
    & icacls $Path /inheritance:r /grant:r $principal | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Unable to protect recovery evidence: $Path" }
}

function Set-RecoveryStage {
    param([Parameter(Mandatory)][string]$Name)
    $script:state.stage = $Name
    Write-MyPeopleTransaction -Path $transactionPath -State $script:state
}

function Invoke-RecoveryCompose {
    Invoke-MyPeopleDocker -Arguments @(
        'compose', '--project-name', 'mypeople', '--env-file', $environmentPath,
        '-f', $composePath, 'up', '--detach', '--force-recreate'
    )
}

function Wait-RecoveryControlPlane {
    param([ValidateRange(1, 600)][int]$TimeoutSeconds = 120)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $todo = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:9933/health' -TimeoutSec 3
            $hud = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:9900/health' -TimeoutSec 3
            $client = [Net.Sockets.TcpClient]::new()
            $connect = $client.ConnectAsync('127.0.0.1', 7681)
            $terminalReady = $connect.Wait(1500) -and $client.Connected
            $client.Dispose()
            if ($todo.StatusCode -eq 200 -and $hud.StatusCode -eq 200 -and $terminalReady) { return }
        } catch {}
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)
    throw "MyPeople control plane did not become ready within $TimeoutSeconds seconds."
}

function New-RecoveryBackupHelper {
    $create = @('create', '--name', $helper, '--user', 'root')
    foreach ($entry in $contract.GetEnumerator()) {
        $create += @('--mount', "type=volume,src=$($entry.Key),dst=/src/$($entry.Key),readonly")
    }
    $create += @($script:state.deploymentImage, 'sleep', 'infinity')
    Invoke-MyPeopleDocker -Arguments $create
    $script:helperCreated = $true
    Invoke-MyPeopleDocker -Arguments @('start', $helper)
}

function Get-RecoveryVolumeState {
    $board = ((Invoke-MyPeopleDocker -Arguments @(
        'exec', $helper, 'sha256sum', '/src/mypeople-todos/board.v2.json'
    ) -Capture).Trim() -split '\s+')[0]
    $rosterJson = Invoke-MyPeopleDocker -Arguments @(
        'exec', $helper, 'cat', '/src/mypeople-run/roster.json'
    ) -Capture
    return [ordered]@{
        boardSha256 = $board
        stableRosterSha256 = Get-MyPeopleStableRosterHash -Json $rosterJson
    }
}

function Write-RecoveryPortableBackup {
    $archiveCommand = @'
set -eu
mkdir -p /tmp/portable/home/mp/mypeople/run
mkdir -p /tmp/portable/home/mp/.codex /tmp/portable/home/mp/.claude
copy_if_present() { [ ! -e "$1" ] || cp -a "$1" "$2"; }
copy_if_present /src/mypeople-todos /tmp/portable/home/mp/mypeople/todos
copy_if_present /src/mypeople-status /tmp/portable/home/mp/mypeople/status
copy_if_present /src/mypeople-run/roster.json /tmp/portable/home/mp/mypeople/run/
copy_if_present /src/mypeople-run/taskspecs /tmp/portable/home/mp/mypeople/run/
copy_if_present /src/mypeople-run/proofs /tmp/portable/home/mp/mypeople/run/
copy_if_present /src/mypeople-recordings /tmp/portable/home/mp/recordings
copy_if_present /src/mypeople-workspaces /tmp/portable/home/mp/workspaces
copy_if_present /src/mypeople-codex/sessions /tmp/portable/home/mp/.codex/
copy_if_present /src/mypeople-claude/projects /tmp/portable/home/mp/.claude/
find /tmp/portable -type f \( -iname '*auth*' -o -iname '*credential*' -o -iname '*token*' -o -iname '*.key' -o -name '.env' -o -name '.env.*' -o -name '.npmrc' -o -name '.pypirc' -o -name '*.pem' -o -name '*.p12' \) -delete
find /tmp/portable/home/mp/workspaces -path '*/.git/config' -type f -exec sed -i -E '/^[[:space:]]*(extraheader|helper)[[:space:]]*=/Id; s#(url[[:space:]]*=[[:space:]]*https://)[^/@[:space:]]+:[^/@[:space:]]+@#\1#Ig' {} + 2>/dev/null || true
tar -C /tmp/portable -czf /tmp/portable-state.tar.gz .
tar -tzf /tmp/portable-state.tar.gz >/dev/null
'@
    Invoke-MyPeopleDocker -Arguments @('exec', $helper, 'sh', '-lc', $archiveCommand)
    Invoke-MyPeopleDocker -Arguments @('cp', "${helper}:/tmp/portable-state.tar.gz", $archivePath)
    $containerHash = ((Invoke-MyPeopleDocker -Arguments @(
        'exec', $helper, 'sha256sum', '/tmp/portable-state.tar.gz'
    ) -Capture).Trim() -split '\s+')[0]
    $hostHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archivePath).Hash.ToLowerInvariant()
    if ($containerHash -ne $hostHash) { throw 'Portable archive hash changed during Docker copy.' }
    if ((Get-Item -LiteralPath $archivePath).Length -lt 1024) {
        throw 'Portable archive is unexpectedly small.'
    }
    $script:state.archiveSha256 = $hostHash
    $script:state.archiveBytes = (Get-Item -LiteralPath $archivePath).Length
    $script:state.excludedAuthPatterns = @(
        '*auth*', '*credential*', '*token*', '*.key', '.env', '.env.*',
        '.npmrc', '.pypirc', '*.pem', '*.p12'
    )
    Write-MyPeopleTransaction -Path $transactionPath -State $script:state
}

function Assert-RecoveredRuntime {
    Wait-RecoveryControlPlane
    $actualImageId = (Invoke-MyPeopleDocker -Arguments @(
        'inspect', 'mypeople', '--format', '{{.Image}}'
    ) -Capture).Trim()
    if ($actualImageId -ne $script:state.candidateImageId) {
        throw 'Recovered container does not use the verified image ID.'
    }
    $restartCount = [int](Invoke-MyPeopleDocker -Arguments @(
        'inspect', 'mypeople', '--format', '{{.RestartCount}}'
    ) -Capture).Trim()
    if ($restartCount -ne 0) { throw "Recovered container restarted $restartCount time(s)." }
    $memoryFlag = (Invoke-MyPeopleDocker -Arguments @(
        'exec', 'mypeople', 'printenv', 'MYPEOPLE_MEMORY_COMPARISON_ENABLED'
    ) -Capture).Trim()
    if ($memoryFlag -ne '0') { throw 'Memory comparison must remain disabled during recovery.' }

    $mounts = Invoke-MyPeopleDocker -Arguments @(
        'inspect', 'mypeople', '--format', '{{json .Mounts}}'
    ) -Capture | ConvertFrom-Json
    $volumeMounts = @($mounts | Where-Object Type -eq 'volume')
    if ($volumeMounts.Count -ne $contract.Count) {
        throw "Expected exactly $($contract.Count) state volumes; found $($volumeMounts.Count)."
    }
    foreach ($entry in $contract.GetEnumerator()) {
        $matches = @($volumeMounts | Where-Object {
            $_.Name -eq $entry.Key -and $_.Destination -eq $entry.Value -and $_.RW
        })
        if ($matches.Count -ne 1) { throw "Invalid recovered mount: $($entry.Key)" }
    }
}

function Assert-RecoveryPreflight {
    foreach ($path in @($VerificationReceipt, $environmentPath, $composePath, $reviewedCompose)) {
        if (-not (Test-Path -LiteralPath $path)) { throw "Required recovery input is missing: $path" }
    }
    & docker compose version *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Docker Compose v2 is required.' }
    if (Test-MyPeopleDockerObject -Type container -Name 'mypeople') {
        throw 'Recovery requires the mypeople container to be absent.'
    }
    foreach ($name in $contract.Keys) {
        if (-not (Test-MyPeopleDockerObject -Type volume -Name $name)) {
            throw "Required state volume is missing: $name"
        }
    }
    if (-not (Test-MyPeopleDockerObject -Type image -Name $CandidateImage)) {
        throw "Candidate image not found: $CandidateImage"
    }
    $script:state.candidateImageId = (Invoke-MyPeopleDocker -Arguments @(
        'image', 'inspect', $CandidateImage, '--format', '{{.Id}}'
    ) -Capture).Trim()

    $receipt = Get-Content -Raw -LiteralPath $VerificationReceipt | ConvertFrom-Json
    if ([string]$receipt.status -ne 'pass') { throw 'Verification receipt did not pass.' }
    if ([string]$receipt.imageId -ne $script:state.candidateImageId) {
        throw 'Verification receipt image ID does not match the candidate.'
    }
    if ([string]$receipt.verification -ne 'isolated-packaged-source') {
        throw 'Verification receipt has the wrong verification mode.'
    }
    $script:state.sourceCommit = [string]$receipt.sourceCommit
    if (-not $script:state.sourceCommit) { throw 'Verification receipt has no source commit.' }
    $currentCommit = (& git -C $root rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $currentCommit -ne $script:state.sourceCommit) {
        throw 'Verification receipt source commit does not match this repository.'
    }
    if (& git -C $root status --porcelain) {
        throw 'Source repository must be clean before recovery.'
    }
    $driveName = [IO.Path]::GetPathRoot($stateRoot).Substring(0, 1)
    if ((Get-PSDrive -Name $driveName).Free / 1GB -lt $MinimumFreeGiB) {
        throw "Need at least $MinimumFreeGiB GiB free."
    }
}

try {
    $operationLock = Enter-MyPeopleDockerOperationLock `
        -Path $operationLockPath -Owner "recovery:$stamp"
    Assert-RecoveryPreflight
    Protect-RecoveryDirectory -Path $transactionRoot
    Set-RecoveryStage 'candidate-verified'
    if (-not $Execute) {
        Set-RecoveryStage 'planned'
        Write-Output "RECOVERY PLAN PASS: $transactionPath"
        return
    }

    Invoke-MyPeopleDocker -Arguments @('tag', $script:state.candidateImageId, $script:state.deploymentImage)
    $pinnedImageId = (Invoke-MyPeopleDocker -Arguments @(
        'image', 'inspect', $script:state.deploymentImage, '--format', '{{.Id}}'
    ) -Capture).Trim()
    if ($pinnedImageId -ne $script:state.candidateImageId) { throw 'Unable to pin candidate image ID.' }

    New-RecoveryBackupHelper
    $before = Get-RecoveryVolumeState
    $script:state.beforeBoardSha256 = $before.boardSha256
    $script:state.beforeStableRosterSha256 = $before.stableRosterSha256
    Set-RecoveryStage 'portable-backup'
    Write-RecoveryPortableBackup
    Invoke-MyPeopleDocker -Arguments @('rm', '-f', $helper)
    $script:helperCreated = $false

    $oldEnvironment = Get-Content -Raw -LiteralPath $environmentPath
    $oldCompose = Get-Content -Raw -LiteralPath $composePath
    $imageBindings = [regex]::Matches($oldEnvironment, '(?m)^MYPEOPLE_IMAGE=.*$')
    if ($imageBindings.Count -ne 1) { throw 'Deployment environment must contain exactly one image binding.' }
    $candidateEnvironment = [regex]::Replace(
        $oldEnvironment,
        '(?m)^MYPEOPLE_IMAGE=.*$',
        "MYPEOPLE_IMAGE=$($script:state.deploymentImage)"
    )
    Copy-Item -LiteralPath $reviewedCompose -Destination $composePath -Force
    [IO.File]::WriteAllText($environmentPath, $candidateEnvironment, [Text.UTF8Encoding]::new($false))
    $script:deploymentFilesChanged = $true

    Set-RecoveryStage 'deploy'
    $script:deploymentMutationStarted = $true
    Invoke-RecoveryCompose
    Assert-RecoveredRuntime

    $afterBoard = ((Invoke-MyPeopleDocker -Arguments @(
        'exec', 'mypeople', 'sha256sum', '/home/mp/mypeople/todos/board.v2.json'
    ) -Capture).Trim() -split '\s+')[0]
    $afterRosterJson = Invoke-MyPeopleDocker -Arguments @(
        'exec', 'mypeople', 'cat', '/home/mp/mypeople/run/roster.json'
    ) -Capture
    $afterRoster = Get-MyPeopleStableRosterHash -Json $afterRosterJson
    if ($afterBoard -ne $before.boardSha256) { throw 'Board content changed during recovery.' }
    if ($afterRoster -ne $before.stableRosterSha256) { throw 'Stable roster identity changed during recovery.' }
    $script:state.afterBoardSha256 = $afterBoard
    $script:state.afterStableRosterSha256 = $afterRoster
    Set-RecoveryStage 'complete'
    Write-Output "RECOVERY PASS: $transactionPath"
} catch {
    $failure = $_
    if (Test-Path -LiteralPath $transactionRoot) {
        $script:state.failure = $failure.Exception.Message
        $script:state.stage = 'recovery_failed'
        if ($script:deploymentMutationStarted -and (Test-MyPeopleDockerObject -Type container -Name 'mypeople')) {
            try { Invoke-MyPeopleDocker -Arguments @('rm', '-f', 'mypeople') } catch {
                $script:state.containerRemovalFailure = $_.Exception.Message
            }
        }
        if ($script:deploymentFilesChanged -and $null -ne $oldEnvironment -and $null -ne $oldCompose) {
            try {
                [IO.File]::WriteAllText($environmentPath, $oldEnvironment, [Text.UTF8Encoding]::new($false))
                [IO.File]::WriteAllText($composePath, $oldCompose, [Text.UTF8Encoding]::new($false))
                $script:state.deploymentFileRestoreStatus = 'pass'
            } catch {
                $script:state.deploymentFileRestoreStatus = 'failed'
                $script:state.deploymentFileRestoreFailure = $_.Exception.Message
            }
        }
        $script:state.oldServiceRestored = $false
        Write-MyPeopleTransaction -Path $transactionPath -State $script:state
    }
    throw $failure
} finally {
    if ($helperCreated -and (Test-MyPeopleDockerObject -Type container -Name $helper)) {
        & docker rm -f $helper *> $null
    }
    if ($operationLock) {
        Exit-MyPeopleDockerOperationLock -Path $operationLockPath -Lock $operationLock
    }
}
