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

    throw 'Execution is not implemented until the backup/deploy contract is complete.'
} catch {
    if (Test-Path -LiteralPath $transactionRoot) {
        $script:state.failure = $_.Exception.Message
        $script:state.stage = 'recovery_failed'
        Write-MyPeopleTransaction -Path $transactionPath -State $script:state
    }
    throw
} finally {
    if ($operationLock) {
        Exit-MyPeopleDockerOperationLock -Path $operationLockPath -Lock $operationLock
    }
}
