param(
    [string]$Image = $(if ($env:MYPEOPLE_VERIFY_IMAGE) { $env:MYPEOPLE_VERIFY_IMAGE } else { 'mypeople-node:integration-a54d9e3' }),
    [ValidateRange(1, 86400)][int]$TimeoutSeconds = 1800,
    [string]$EvidenceRoot = (Join-Path ([IO.Path]::GetTempPath()) 'mypeople-verify'),
    [string]$SmokeCommand = ''
)

$ErrorActionPreference = 'Stop'
$script:Result = 125
$script:Project = $null
$script:Compose = Join-Path $PSScriptRoot 'compose.isolated.yml'
$script:Root = Split-Path -Parent $PSScriptRoot
$runId = '{0:yyyyMMddTHHmmssZ}-{1}-{2}' -f (Get-Date).ToUniversalTime(), $PID, ([guid]::NewGuid().ToString('N').Substring(0, 8))
$script:Project = "mypeople-verify-$($runId.ToLowerInvariant())"
$script:RunDirectory = Join-Path $EvidenceRoot $runId
$script:OutputPath = Join-Path $script:RunDirectory 'verify.log'

function Invoke-DockerCapture([string[]]$Arguments, [string]$Path) {
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $lines = @(& docker @Arguments 2>&1 | ForEach-Object {
            if ($_ -is [Management.Automation.ErrorRecord]) { $_.Exception.Message } else { $_.ToString() }
        })
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    $lines | Out-File -LiteralPath $Path -Encoding utf8 -Append
    return $exitCode
}

function Stop-IsolatedProject {
    if (-not $script:Project) { return 0 }
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { return 0 }
    return Invoke-DockerCapture @(
        'compose', '--project-name', $script:Project, '-f', $script:Compose,
        'down', '--remove-orphans', '--timeout', '10'
    ) $script:OutputPath
}

try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw 'Docker CLI is required.'
    }
    & docker compose version *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Docker Compose v2 is required.' }

    New-Item -ItemType Directory -Path $script:RunDirectory -Force | Out-Null
    New-Item -ItemType File -Path $script:OutputPath -Force | Out-Null
    $env:MYPEOPLE_VERIFY_IMAGE = $Image
    $env:MP_VERIFY_SOURCE = $script:Root
    $env:MP_VERIFY_EVIDENCE_DIR = $script:RunDirectory
    $env:MP_VERIFY_MODE = 'full'
    $env:MP_VERIFY_SMOKE_COMMAND = ''
    if ($PSBoundParameters.ContainsKey('SmokeCommand')) {
        if ([string]::IsNullOrWhiteSpace($SmokeCommand)) { throw 'SmokeCommand must not be empty when supplied.' }
        $env:MP_VERIFY_MODE = 'smoke'
        $env:MP_VERIFY_SMOKE_COMMAND = $SmokeCommand
    }

    $configCode = Invoke-DockerCapture @(
        'compose', '--project-name', $script:Project, '-f', $script:Compose, 'config', '--quiet'
    ) $script:OutputPath
    if ($configCode -ne 0) { throw 'Isolated Compose validation failed.' }

    $dockerArguments = @(
        'compose', '--project-name', $script:Project, '-f', $script:Compose,
        'run', '--rm', '--no-deps', 'verify'
    )
    $job = Start-Job -ScriptBlock {
        param([string[]]$DockerArguments)
        $ErrorActionPreference = 'Continue'
        $output = @(& docker @DockerArguments 2>&1 | ForEach-Object {
            if ($_ -is [Management.Automation.ErrorRecord]) { $_.Exception.Message } else { $_.ToString() }
        })
        [pscustomobject]@{ ExitCode = $LASTEXITCODE; Output = $output }
    } -ArgumentList (,$dockerArguments)
    $completed = Wait-Job -Job $job -Timeout $TimeoutSeconds
    if (-not $completed) {
        Stop-Job -Job $job
        Remove-Job -Job $job -Force
        $script:Result = 124
    } else {
        $jobResult = Receive-Job -Job $job
        Remove-Job -Job $job
        $jobResult.Output | Tee-Object -FilePath $script:OutputPath -Append | Write-Output
        $script:Result = switch ([int]$jobResult.ExitCode) {
            0 { 0 }
            { $_ -in 125, 126, 127 } { 125 }
            default { 1 }
        }
    }

    if ($script:Result -ne 0) {
        [void](Invoke-DockerCapture @(
            'compose', '--project-name', $script:Project, '-f', $script:Compose, 'ps', '--all'
        ) (Join-Path $script:RunDirectory 'compose-ps.log'))
        [void](Invoke-DockerCapture @(
            'compose', '--project-name', $script:Project, '-f', $script:Compose, 'logs', '--no-color'
        ) (Join-Path $script:RunDirectory 'compose.log'))
    }
} catch {
    New-Item -ItemType Directory -Path $script:RunDirectory -Force | Out-Null
    $_ | Out-String | Out-File -LiteralPath $script:OutputPath -Encoding utf8 -Append
    Write-Error $_ -ErrorAction Continue
    $script:Result = 125
} finally {
    $cleanupCode = Stop-IsolatedProject
    if ($cleanupCode -ne 0 -and $script:Result -eq 0) { $script:Result = 125 }
    Remove-Item Env:MYPEOPLE_VERIFY_IMAGE -ErrorAction SilentlyContinue
    Remove-Item Env:MP_VERIFY_SOURCE -ErrorAction SilentlyContinue
    Remove-Item Env:MP_VERIFY_EVIDENCE_DIR -ErrorAction SilentlyContinue
    Remove-Item Env:MP_VERIFY_MODE -ErrorAction SilentlyContinue
    Remove-Item Env:MP_VERIFY_SMOKE_COMMAND -ErrorAction SilentlyContinue
}

if ($script:Result -eq 0) {
    Remove-Item -LiteralPath $script:RunDirectory -Recurse -Force
    Write-Output 'Isolated MyPeople verification passed.'
} else {
    Write-Error "Isolated MyPeople verification failed with exit $script:Result. Evidence retained at: $script:RunDirectory" -ErrorAction Continue
}
exit $script:Result
