param(
    [Parameter(Mandatory)][string]$CandidateImage,
    [ValidateRange(1, 86400)][int]$VerifyTimeoutSeconds = 1800,
    [ValidateRange(1, 1024)][int]$MinimumFreeGiB = 4
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = Split-Path $PSScriptRoot -Parent
Import-Module (Join-Path $PSScriptRoot 'MyPeople.DockerMigration.psm1') -Force

$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$stateRoot = Join-Path $env:LOCALAPPDATA 'MyPeople'
$transactionRoot = Join-Path $stateRoot "backups\docker-upgrade\$stamp"
$transactionPath = Join-Path $transactionRoot 'transaction.json'
$archivePath = Join-Path $transactionRoot 'portable-state.tar.gz'
$operationLockPath = Join-Path $stateRoot 'docker-operation.lock'
$deployment = Join-Path $stateRoot 'deployment'
$environmentPath = Join-Path $deployment '.env'
$composePath = Join-Path $deployment 'compose.volume-backed.yml'
$reviewedCompose = Join-Path $root 'docker\compose.volume-backed.yml'
$isolatedVerifier = Join-Path $root 'verify\Invoke-IsolatedVerify.ps1'
$helper = "mypeople-upgrade-backup-$stamp"
$contract = Get-MyPeopleVolumeContract -Root $root
$operationLock = $null
$helperCreated = $false
$liveStopped = $false
$deploymentFilesChanged = $false
$deploymentMutationStarted = $false
$oldEnvironment = $null
$oldCompose = $null

$script:state = [ordered]@{
    id = $stamp
    stage = 'preflight'
    sourceCommit = ''
    oldImage = ''
    candidateImage = $CandidateImage
    candidateImageId = ''
    deploymentImage = "mypeople-node:upgrade-$stamp"
    rollbackImage = ''
    rollbackImageId = ''
    rollbackPinnedImage = "mypeople-node:rollback-$stamp"
    backupClassification = 'sensitive-local-restore-material'
    providerActivationAttempted = $false
    volumes = @($contract.Keys)
    rollbackAttempted = $false
}

function Set-UpgradeStage {
    param([Parameter(Mandatory)][string]$Name)
    $script:state.stage = $Name
    Write-MyPeopleTransaction -Path $transactionPath -State $script:state
}

function Docker {
    param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments)
    Invoke-MyPeopleDocker -Arguments $Arguments
}

function Docker-Capture {
    param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments)
    Invoke-MyPeopleDocker -Arguments $Arguments -Capture
}

function Invoke-PinnedCompose {
    Invoke-MyPeopleDocker -Arguments @(
        'compose', '--project-name', 'mypeople', '--env-file', $environmentPath,
        '-f', $composePath, 'up', '--detach', '--force-recreate'
    )
}

function Wait-MyPeopleControlPlane {
    param([ValidateRange(1, 600)][int]$TimeoutSeconds = 90)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $todo = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:9933/health' -TimeoutSec 3
            $hud = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:9900/health' -TimeoutSec 3
            $client = [Net.Sockets.TcpClient]::new()
            $connect = $client.ConnectAsync('127.0.0.1', 7681)
            $terminal = $connect.Wait(1500) -and $client.Connected
            $client.Dispose()
            if ($todo.StatusCode -eq 200 -and $hud.StatusCode -eq 200 -and $terminal) { return }
        } catch {}
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)
    throw "MyPeople control plane did not become ready within $TimeoutSeconds seconds."
}

function Get-LiveState {
    $board = ((Docker-Capture exec mypeople sha256sum /home/mp/mypeople/todos/board.v2.json).Trim() -split '\s+')[0]
    $rosterJson = Docker-Capture exec mypeople cat /home/mp/mypeople/run/roster.json
    [ordered]@{
        boardSha256 = $board
        stableRosterSha256 = Get-MyPeopleStableRosterHash -Json $rosterJson
    }
}

function Assert-LiveMountContract {
    $mounts = Docker-Capture inspect mypeople --format '{{json .Mounts}}' | ConvertFrom-Json
    $volumeMounts = @($mounts | Where-Object Type -eq 'volume')
    if ($volumeMounts.Count -ne $contract.Count) {
        throw "Expected exactly $($contract.Count) live volume mounts; found $($volumeMounts.Count)."
    }
    foreach ($entry in $contract.GetEnumerator()) {
        $matches = @($volumeMounts | Where-Object {
            $_.Type -eq 'volume' -and
            $_.Name -eq $entry.Key -and
            $_.Destination -eq $entry.Value -and
            $_.RW
        })
        if ($matches.Count -ne 1) {
            throw "Live volume mapping is invalid: $($entry.Key) -> $($entry.Value)"
        }
    }
    $seed = @($mounts | Where-Object {
        $_.Type -eq 'bind' -and $_.Destination -eq '/home/mp/mypeople.seed.md' -and -not $_.RW
    })
    if ($seed.Count -ne 1) { throw 'The read-only seed bind is missing.' }
}

function Assert-LiveRuntimeContract {
    Wait-MyPeopleControlPlane
    $actualImage = (Docker-Capture inspect mypeople --format '{{.Config.Image}}').Trim()
    if ($actualImage -ne $script:state.deploymentImage) { throw "Unexpected live image: $actualImage" }
    $actualImageId = (Docker-Capture inspect mypeople --format '{{.Image}}').Trim()
    if ($actualImageId -ne $script:state.candidateImageId) { throw 'The live container does not use the verified candidate image ID.' }
    $pidOne = (Docker-Capture exec mypeople ps -o comm= -p 1).Trim()
    if ($pidOne -eq 'sleep') { throw 'PID 1 regressed to sleep.' }
    $processes = Docker-Capture exec mypeople ps -eo args=
    if (([regex]::Matches($processes, '(?m)^/bin/bash /home/mp/mypeople/bin/runtime-supervisor\.sh$')).Count -ne 1) {
        throw 'Expected exactly one runtime supervisor.'
    }
    if (([regex]::Matches($processes, '(?m)^bash /home/mp/mypeople/bin/boss-supervisor\.sh$')).Count -ne 1) {
        throw 'Expected exactly one Boss supervisor.'
    }
    Assert-LiveMountContract
    Docker exec mypeople tmux has-session -t repo-project-factory
}

function Write-PortableBackup {
    Docker stop --timeout 30 mypeople
    $script:liveStopped = $true

    $create = @('create', '--name', $helper, '--user', 'root')
    foreach ($entry in $contract.GetEnumerator()) {
        $create += @('--mount', "type=volume,src=$($entry.Key),dst=/src/$($entry.Key),readonly")
    }
    $create += @($script:state.rollbackPinnedImage, 'sleep', 'infinity')
    Invoke-MyPeopleDocker -Arguments $create
    $script:helperCreated = $true
    Docker start $helper

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
    Docker exec $helper sh -lc $archiveCommand
    Docker cp "${helper}:/tmp/portable-state.tar.gz" $archivePath

    $redacted = Docker-Capture exec $helper sh -lc 'cat /src/mypeople-config/queue.env 2>/dev/null || true'
    ConvertTo-MyPeopleRedactedConfig $redacted |
        Set-Content -LiteralPath (Join-Path $transactionRoot 'queue.env.redacted') -Encoding UTF8

    $containerHash = ((Docker-Capture exec $helper sha256sum /tmp/portable-state.tar.gz).Trim() -split '\s+')[0]
    $hostHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archivePath).Hash.ToLowerInvariant()
    if ($containerHash -ne $hostHash) { throw 'Portable archive hash changed during Docker copy.' }
    if ((Get-Item -LiteralPath $archivePath).Length -lt 1024) { throw 'Portable archive is unexpectedly small.' }
    $script:state.archiveSha256 = $hostHash
    $script:state.archiveBytes = (Get-Item -LiteralPath $archivePath).Length
    $script:state.excludedAuthPatterns = @(
        '*auth*', '*credential*', '*token*', '*.key', '.env', '.env.*',
        '.npmrc', '.pypirc', '*.pem', '*.p12'
    )
    Write-MyPeopleTransaction -Path $transactionPath -State $script:state

    Docker rm -f $helper
    $script:helperCreated = $false
    Docker start mypeople
    $script:liveStopped = $false
    Wait-MyPeopleControlPlane
}

function Assert-Preflight {
    if (-not $env:LOCALAPPDATA) { throw 'LOCALAPPDATA is required.' }
    foreach ($path in @($environmentPath, $composePath, $reviewedCompose, $isolatedVerifier)) {
        if (-not (Test-Path -LiteralPath $path)) { throw "Required upgrade input is missing: $path" }
    }
    & docker compose version *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Docker Compose v2 is required.' }
    & docker image inspect $CandidateImage *> $null
    if ($LASTEXITCODE -ne 0) { throw "Candidate image not found: $CandidateImage" }
    $script:state.candidateImageId = (Docker-Capture image inspect $CandidateImage --format '{{.Id}}').Trim()
    if (& git -C $root status --porcelain) { throw 'Source repository must be clean before an image upgrade.' }
    $script:state.sourceCommit = (& git -C $root rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $script:state.sourceCommit) { throw 'Unable to resolve the source commit.' }
    $running = (Docker-Capture inspect mypeople --format '{{.State.Running}}').Trim()
    if ($running -ne 'true') { throw 'The live MyPeople container must be running.' }
    $script:state.oldImage = (Docker-Capture inspect mypeople --format '{{.Config.Image}}').Trim()
    $script:state.rollbackImage = $script:state.oldImage
    $script:state.rollbackImageId = (Docker-Capture inspect mypeople --format '{{.Image}}').Trim()
    if ($script:state.rollbackImageId -eq $script:state.candidateImageId) { throw 'Candidate image is already live.' }
    Docker tag $script:state.candidateImageId $script:state.deploymentImage
    Docker tag $script:state.rollbackImageId $script:state.rollbackPinnedImage
    if ((Docker-Capture image inspect $script:state.deploymentImage --format '{{.Id}}').Trim() -ne $script:state.candidateImageId) {
        throw 'Unable to pin the candidate image ID.'
    }
    if ((Docker-Capture image inspect $script:state.rollbackPinnedImage --format '{{.Id}}').Trim() -ne $script:state.rollbackImageId) {
        throw 'Unable to pin the rollback image ID.'
    }
    $driveName = [IO.Path]::GetPathRoot($stateRoot).Substring(0, 1)
    if ((Get-PSDrive -Name $driveName).Free / 1GB -lt $MinimumFreeGiB) {
        throw "Need at least $MinimumFreeGiB GiB free."
    }
    Wait-MyPeopleControlPlane
    Assert-LiveMountContract
}

try {
    $operationLock = Enter-MyPeopleDockerOperationLock -Path $operationLockPath -Owner "upgrade:$stamp"
    Assert-Preflight
    New-Item -ItemType Directory -Path $transactionRoot -Force | Out-Null
    $principal = $env:USERNAME + ':(OI)(CI)F'
    & icacls $transactionRoot /inheritance:r /grant:r $principal | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Unable to protect the upgrade evidence directory.' }
    Set-UpgradeStage 'planned'

    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $isolatedVerifier `
        -Image $script:state.deploymentImage -TimeoutSeconds $VerifyTimeoutSeconds -UsePackagedSource
    if ($LASTEXITCODE -ne 0) { throw 'Candidate image failed isolated verification.' }
    $verifiedImageId = (Docker-Capture image inspect $script:state.deploymentImage --format '{{.Id}}').Trim()
    if ($verifiedImageId -ne $script:state.candidateImageId) { throw 'Candidate image changed during isolated verification.' }
    Set-UpgradeStage 'candidate-verified'

    $before = Get-LiveState
    $script:state.beforeBoardSha256 = $before.boardSha256
    $script:state.beforeStableRosterSha256 = $before.stableRosterSha256
    Write-MyPeopleTransaction -Path $transactionPath -State $script:state

    Set-UpgradeStage 'portable-backup'
    Write-PortableBackup

    $oldEnvironment = Get-Content -Raw -LiteralPath $environmentPath
    $oldCompose = Get-Content -Raw -LiteralPath $composePath
    $deploymentFilesChanged = $true
    ConvertTo-MyPeopleRedactedConfig $oldEnvironment |
        Set-Content -LiteralPath (Join-Path $transactionRoot '.env.previous.redacted') -Encoding UTF8
    Copy-Item -LiteralPath $composePath -Destination (Join-Path $transactionRoot 'compose.previous.yml')
    Copy-Item -LiteralPath $reviewedCompose -Destination $composePath -Force
    $candidateEnvironment = [regex]::Replace(
        $oldEnvironment,
        '(?m)^MYPEOPLE_IMAGE=.*$',
        "MYPEOPLE_IMAGE=$($script:state.deploymentImage)"
    )
    if ($candidateEnvironment -eq $oldEnvironment) { throw 'Pinned deployment has no image binding.' }
    [IO.File]::WriteAllText($environmentPath, $candidateEnvironment, [Text.UTF8Encoding]::new($false))

    Set-UpgradeStage 'deploy'
    $pinnedCandidateId = (Docker-Capture image inspect $script:state.deploymentImage --format '{{.Id}}').Trim()
    if ($pinnedCandidateId -ne $script:state.candidateImageId) { throw 'Pinned candidate image changed before deployment.' }
    $deploymentMutationStarted = $true
    Invoke-PinnedCompose
    Assert-LiveRuntimeContract

    $after = Get-LiveState
    if ($after.boardSha256 -ne $before.boardSha256) { throw 'Board content changed during the image upgrade.' }
    if ($after.stableRosterSha256 -ne $before.stableRosterSha256) { throw 'Stable roster identity changed during the image upgrade.' }
    $script:state.afterBoardSha256 = $after.boardSha256
    $script:state.afterStableRosterSha256 = $after.stableRosterSha256
    $script:state.liveImage = $script:state.deploymentImage
    Set-UpgradeStage 'complete'
    Write-Output "UPGRADE PASS: $transactionPath"
} catch {
    $failure = $_
    $script:state.failure = $failure.Exception.Message
    if ($deploymentFilesChanged -and $oldEnvironment -and $oldCompose) {
        try {
            if ($deploymentMutationStarted) {
                $script:state.rollbackAttempted = $true
                $rollbackEnvironment = [regex]::Replace(
                    $oldEnvironment,
                    '(?m)^MYPEOPLE_IMAGE=.*$',
                    "MYPEOPLE_IMAGE=$($script:state.rollbackPinnedImage)"
                )
                [IO.File]::WriteAllText($environmentPath, $rollbackEnvironment, [Text.UTF8Encoding]::new($false))
                [IO.File]::WriteAllText($composePath, $oldCompose, [Text.UTF8Encoding]::new($false))
                Invoke-PinnedCompose
                Wait-MyPeopleControlPlane
                $restored = (Docker-Capture inspect mypeople --format '{{.Config.Image}}').Trim()
                if ($restored -ne $script:state.rollbackPinnedImage) { throw "Rollback selected the wrong image: $restored" }
                $restoredId = (Docker-Capture inspect mypeople --format '{{.Image}}').Trim()
                if ($restoredId -ne $script:state.rollbackImageId) { throw 'Rollback selected the wrong image ID.' }
                Assert-LiveMountContract
                $rollbackState = Get-LiveState
                if (
                    $rollbackState.boardSha256 -ne $before.boardSha256 -or
                    $rollbackState.stableRosterSha256 -ne $before.stableRosterSha256
                ) {
                    $script:state.rollbackStatus = 'recovery-required'
                    throw 'Rollback restored the runtime image but durable state differs from the pre-upgrade hashes; restore from the protected archive.'
                }
                $script:state.rollbackStatus = 'pass'
            } else {
                [IO.File]::WriteAllText($environmentPath, $oldEnvironment, [Text.UTF8Encoding]::new($false))
                [IO.File]::WriteAllText($composePath, $oldCompose, [Text.UTF8Encoding]::new($false))
                $script:state.deploymentFileRestoreStatus = 'pass'
            }
        } catch {
            if ($deploymentMutationStarted) {
                if ($script:state.rollbackStatus -ne 'recovery-required') {
                    $script:state.rollbackStatus = 'failed'
                }
                $script:state.rollbackFailure = $_.Exception.Message
            } else {
                $script:state.deploymentFileRestoreStatus = 'failed'
                $script:state.deploymentFileRestoreFailure = $_.Exception.Message
            }
        }
    }
    if (Test-Path -LiteralPath $transactionRoot) {
        Write-MyPeopleTransaction -Path $transactionPath -State $script:state
    }
    throw $failure
} finally {
    if ($helperCreated) { & docker rm -f $helper *> $null }
    if ($liveStopped) { & docker start mypeople *> $null }
    if ($operationLock) {
        Exit-MyPeopleDockerOperationLock -Path $operationLockPath -Lock $operationLock
    }
}
