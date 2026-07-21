[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Image,
    [string]$DatasetDirectory = '',
    [ValidateRange(1, 3600)][int]$TimeoutSeconds = 300,
    [string]$EvidenceRoot = (Join-Path ([IO.Path]::GetTempPath()) 'mypeople-taskspec-memory')
)

$ErrorActionPreference = 'Stop'
$ExpectedDatasetName = 'project-factory-history-80dce6f86632'
$ExpectedSourceSha = '80dce6f866329b79061bb1ed6b0594f9fdf2dd45'
$ExpectedRepoSlug = 'LordCripto-Hub/Project-Factory'
$SourceRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($DatasetDirectory)) {
    $DatasetDirectory = Join-Path $SourceRoot 'datasets\project-factory-history-80dce6f86632'
}
$ComposePath = Join-Path $SourceRoot 'docker\compose.taskspec-memory.yml'
$LockPath = Join-Path $SourceRoot 'docker\history-hybrid.dataset-lock.json'
$ProjectName = 'mp-taskspec-' + ([Guid]::NewGuid().ToString('N').Substring(0, 12))
$EvidenceDirectory = Join-Path $EvidenceRoot $ProjectName
$Started = [DateTime]::UtcNow
$Stopwatch = [Diagnostics.Stopwatch]::StartNew()
$ExitCode = 125
$PrimaryExitCode = 125
$LogicalDigest = $null
$ImageId = $null
$Job = $null
$ComposeStarted = $false
$CleanupVerified = $false
$LiveBefore = $null
$LiveAfter = $null
$LiveUnchanged = $false

function Test-DockerCommand {
    param([string[]]$Arguments, [string]$Description)
    & docker @Arguments *> $null
    $CommandExitCode = $LASTEXITCODE
    if ($CommandExitCode -ne 0) {
        throw "$Description failed"
    }
}

function Get-LiveMyPeopleState {
    $InspectOutput = & docker inspect --format '{{.Id}}|{{.State.StartedAt}}|{{.RestartCount}}|{{.State.Running}}' mypeople 2>$null
    $InspectExitCode = $LASTEXITCODE
    if ($InspectExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($InspectOutput)) {
        throw 'live mypeople container is unavailable'
    }
    $Parts = ([string]($InspectOutput | Select-Object -First 1)).Trim().Split('|')
    if ($Parts.Count -ne 4) {
        throw 'live mypeople state is malformed'
    }
    return [ordered]@{
        id = $Parts[0]
        started_at = $Parts[1]
        restart_count = [int]$Parts[2]
        running = [bool]::Parse($Parts[3])
    }
}

function Test-SameLiveState {
    param($Before, $After)
    return (
        $Before.id -eq $After.id -and
        $Before.started_at -eq $After.started_at -and
        $Before.restart_count -eq $After.restart_count -and
        $Before.running -eq $After.running
    )
}

try {
    Test-DockerCommand -Arguments @('compose', 'version') -Description 'docker compose version'

    $ImageInspectOutput = & docker image inspect --format '{{.Id}}' $Image 2>$null
    $ImageInspectExitCode = $LASTEXITCODE
    $ImageId = $ImageInspectOutput | Select-Object -First 1
    if ($ImageInspectExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($ImageId)) {
        throw 'docker image inspect failed'
    }

    $ResolvedDataset = (Resolve-Path -LiteralPath $DatasetDirectory).Path
    if ((Split-Path -Leaf $ResolvedDataset) -ne $ExpectedDatasetName) {
        throw 'dataset directory name is not the approved final dataset'
    }

    $Lock = Get-Content -LiteralPath $LockPath -Raw | ConvertFrom-Json
    if ($Lock.dataset_dir -ne $ExpectedDatasetName -or
        $Lock.source_sha -ne $ExpectedSourceSha -or
        $Lock.repo_slug -ne $ExpectedRepoSlug) {
        throw 'dataset lock identity does not match the approved contract'
    }
    foreach ($Property in $Lock.files.PSObject.Properties) {
        $DatasetFile = Join-Path $ResolvedDataset $Property.Name
        $ActualHash = (Get-FileHash -LiteralPath $DatasetFile -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($ActualHash -ne [string]$Property.Value) {
            throw "dataset checksum mismatch: $($Property.Name)"
        }
    }
    $ValidationPath = Join-Path $ResolvedDataset 'validation.json'
    $Validation = Get-Content -LiteralPath $ValidationPath -Raw | ConvertFrom-Json
    if (-not [bool]$Validation.passed) {
        throw 'dataset validation status is not passed'
    }

    $LiveBefore = Get-LiveMyPeopleState

    New-Item -ItemType Directory -Path $EvidenceRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $EvidenceDirectory | Out-Null
    if (Get-ChildItem -LiteralPath $EvidenceDirectory -Force | Select-Object -First 1) {
        throw 'new evidence directory is not empty'
    }

    $env:MYPEOPLE_TASKSPEC_IMAGE = $Image
    $env:MYPEOPLE_TASKSPEC_DATASET_NAME = $ExpectedDatasetName
    $env:EXPECTED_SOURCE_SHA = $ExpectedSourceSha
    $env:MP_TASKSPEC_SOURCE = $SourceRoot
    $env:MP_TASKSPEC_DATASET = $ResolvedDataset
    $env:MP_TASKSPEC_EVIDENCE = $EvidenceDirectory

    $ComposeStarted = $true
    $Job = Start-Job -ArgumentList @(
        $ComposePath,
        $ProjectName,
        $Image,
        $ExpectedDatasetName,
        $ExpectedSourceSha,
        $SourceRoot,
        $ResolvedDataset,
        $EvidenceDirectory
    ) -ScriptBlock {
        param(
            $Compose,
            $Project,
            $ImageRef,
            $DatasetName,
            $SourceSha,
            $Source,
            $Dataset,
            $Evidence
        )
        $env:MYPEOPLE_TASKSPEC_IMAGE = $ImageRef
        $env:MYPEOPLE_TASKSPEC_DATASET_NAME = $DatasetName
        $env:EXPECTED_SOURCE_SHA = $SourceSha
        $env:MP_TASKSPEC_SOURCE = $Source
        $env:MP_TASKSPEC_DATASET = $Dataset
        $env:MP_TASKSPEC_EVIDENCE = $Evidence
        $Output = (& docker compose --progress quiet -p $Project -f $Compose run --rm --no-deps taskspec-memory 2>&1 | Out-String)
        $ContainerExitCode = $LASTEXITCODE
        [pscustomobject]@{
            TaskSpecMemoryExitCode = $ContainerExitCode
            TaskSpecMemoryOutput = $Output
        }
    }

    if (-not (Wait-Job -Job $Job -Timeout $TimeoutSeconds)) {
        Stop-Job -Job $Job -ErrorAction SilentlyContinue
        $ExitCode = 124
    } else {
        $Payload = @(Receive-Job -Job $Job)
        $Record = $Payload |
            Where-Object { $_.PSObject.Properties.Name -contains 'TaskSpecMemoryExitCode' } |
            Select-Object -Last 1
        if ($null -eq $Record) {
            throw 'Docker job returned no exit record'
        }
        if (-not [string]::IsNullOrWhiteSpace($Record.TaskSpecMemoryOutput)) {
            Write-Output $Record.TaskSpecMemoryOutput.TrimEnd()
        }
        $ExitCode = [int]$Record.TaskSpecMemoryExitCode
    }

    if ($ExitCode -eq 0) {
        $ResultPath = Join-Path $EvidenceDirectory 'taskspec-memory-result.json'
        if (-not (Test-Path -LiteralPath $ResultPath)) {
            throw 'gate exited successfully without a logical result'
        }
        $Result = Get-Content -LiteralPath $ResultPath -Raw | ConvertFrom-Json
        $LogicalDigest = [string]$Result.logical_digest
        if ([string]::IsNullOrWhiteSpace($LogicalDigest)) {
            throw 'logical result has no digest'
        }
        $PromotionGates = @($Result.promotion_gates.PSObject.Properties)
        if ($PromotionGates.Count -eq 0) {
            throw 'promotion gate set is missing'
        }
        foreach ($Property in $PromotionGates) {
            if (-not [bool]$Property.Value) {
                throw "promotion gate failed: $($Property.Name)"
            }
        }
    }
} catch {
    Write-Error -ErrorRecord $_ -ErrorAction Continue
    if ($ExitCode -ne 124) {
        $ExitCode = 125
    }
} finally {
    $PrimaryExitCode = $ExitCode
    if ($null -ne $Job) {
        Remove-Job -Job $Job -Force -ErrorAction SilentlyContinue
    }
    $PreviousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = 'SilentlyContinue'
    try {
        if ($ComposeStarted -and (Test-Path -LiteralPath $ComposePath)) {
            & docker compose -p $ProjectName -f $ComposePath down --remove-orphans --timeout '10' 2>$null | Out-Null
        }
        $RemainingContainers = @(& docker ps -aq --filter "label=com.docker.compose.project=$ProjectName")
        $RemainingNetworks = @(& docker network ls -q --filter "label=com.docker.compose.project=$ProjectName")
        $CleanupVerified = (
            @($RemainingContainers | Where-Object { $_ }).Count -eq 0 -and
            @($RemainingNetworks | Where-Object { $_ }).Count -eq 0
        )
    } finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
        $ExitCode = $PrimaryExitCode
        $Stopwatch.Stop()
    }
}

if ($null -ne $LiveBefore) {
    try {
        $LiveAfter = Get-LiveMyPeopleState
        $LiveUnchanged = Test-SameLiveState $LiveBefore $LiveAfter
    } catch {
        Write-Error -ErrorRecord $_ -ErrorAction Continue
        $LiveUnchanged = $false
    }
}
if (-not $CleanupVerified -or -not $LiveUnchanged) {
    $ExitCode = 125
}

if (Test-Path -LiteralPath $EvidenceDirectory) {
    $Receipt = [ordered]@{
        schema_version = 1
        ImageReference = $Image
        ImageId = ([string]$ImageId).Trim()
        dataset_name = $ExpectedDatasetName
        source_sha = $ExpectedSourceSha
        logical_digest = $LogicalDigest
        started_utc = $Started.ToString('o')
        finished_utc = [DateTime]::UtcNow.ToString('o')
        elapsed_seconds = [Math]::Round($Stopwatch.Elapsed.TotalSeconds, 3)
        exit_code = $ExitCode
        cleanup_verified = $CleanupVerified
        live_mypeople_before = $LiveBefore
        live_mypeople_after = $LiveAfter
        live_mypeople_unchanged = $LiveUnchanged
    }
    $ReceiptJson = $Receipt | ConvertTo-Json -Depth 6
    $Utf8NoBom = New-Object Text.UTF8Encoding($false)
    [IO.File]::WriteAllText(
        (Join-Path $EvidenceDirectory 'container-receipt.json'),
        $ReceiptJson + [Environment]::NewLine,
        $Utf8NoBom
    )
    Write-Output "EvidenceDirectory=$EvidenceDirectory"
}

exit $ExitCode
