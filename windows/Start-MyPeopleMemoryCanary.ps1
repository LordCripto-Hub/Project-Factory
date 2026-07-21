param(
    [Parameter(Mandatory)]
    [ValidateSet('Enable', 'Disable', 'Status')]
    [string]$Action,
    [string]$MemorySource,
    [string]$Dataset,
    [string]$Image,
    [string]$Container = 'mypeople'
)

$ErrorActionPreference = 'Stop'
$projectName = 'memory-gate-b-live-canary'
$networkName = 'mypeople-memory-canary-internal'
$volumeName = 'mypeople-memory-canary-secret'
$secretDirectory = '/run/mypeople-secrets'
$secretPath = "$secretDirectory/MYPEOPLE_MEMORY_CANARY_TOKEN"
$serverUrl = 'http://memory-gate-b:18443/mcp'
$composePath = Join-Path $PSScriptRoot '..\experiments\memory-gate-b\docker\compose.live-canary.yml'

function Set-ComposeParseDefaults {
    if ([string]::IsNullOrWhiteSpace($env:MYPEOPLE_MEMORY_CANARY_IMAGE)) {
        $env:MYPEOPLE_MEMORY_CANARY_IMAGE = 'memory-canary-cleanup-only'
    }
    if ([string]::IsNullOrWhiteSpace($env:MYPEOPLE_MEMORY_CANARY_SOURCE)) {
        $env:MYPEOPLE_MEMORY_CANARY_SOURCE = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\experiments\memory-gate-b'))
    }
    if ([string]::IsNullOrWhiteSpace($env:MYPEOPLE_MEMORY_CANARY_DATASET)) {
        $env:MYPEOPLE_MEMORY_CANARY_DATASET = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\experiments\memory-gate-b\datasets\project-factory-history-80dce6f86632'))
    }
}

function Invoke-DockerWithSecretInput {
    param([Parameter(Mandatory)][string[]]$Arguments, [Parameter(Mandatory)][string]$Secret)
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = (Get-Command docker -ErrorAction Stop).Source
    $start.Arguments = ($Arguments -join ' ')
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardInput = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $start
    if (-not $process.Start()) { throw 'Unable to start Docker secret injection.' }
    $process.StandardInput.Write($Secret)
    $process.StandardInput.Close()
    $process.StandardOutput.ReadToEnd() | Out-Null
    $errorText = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) { throw "Docker secret injection failed: $errorText" }
}

function Disable-Canary {
    Set-ComposeParseDefaults
    $failures = [Collections.Generic.List[string]]::new()
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & docker inspect $Container *> $null
        $containerExists = $LASTEXITCODE -eq 0
        if ($containerExists) {
            & docker exec $Container /home/mp/mypeople/bin/mp memory-canary disable *> $null
            if ($LASTEXITCODE -ne 0) { $failures.Add('runtime-control') }
            $profileOutput = (& docker exec $Container /home/mp/mypeople/bin/memory-profile disable --project project-factory 2>&1 | Out-String)
            if ($LASTEXITCODE -ne 0 -and $profileOutput -notmatch 'profile_not_found') { $failures.Add('project-profile') }
            & docker exec --user 0:0 $Container sh -c "rm -rf $secretDirectory" *> $null
            if ($LASTEXITCODE -ne 0) { $failures.Add('main-container-token') }
            $networkOutput = (& docker network disconnect $networkName $Container 2>&1 | Out-String)
            if ($LASTEXITCODE -ne 0 -and $networkOutput -notmatch 'not connected|not found|No such') { $failures.Add('network-disconnect') }
        }
        & docker compose --project-name $projectName -f $composePath down --volumes *> $null
        if ($LASTEXITCODE -ne 0) { $failures.Add('compose-resources') }
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($failures.Count -gt 0) {
        throw "Memory Gate B cleanup incomplete: $($failures -join ', ')."
    }
}

if ($Action -eq 'Status') {
    Set-ComposeParseDefaults
    & docker inspect $Container --format '{{.State.Status}}'
    & docker compose --project-name $projectName -f $composePath ps
    exit $LASTEXITCODE
}
if ($Action -eq 'Disable') {
    Disable-Canary
    Write-Output 'Memory Gate B canary disabled.'
    exit 0
}

$enabled = $false
$tokenBytes = [byte[]]::new(32)
$token = $null
try {
    & docker inspect $Container *> $null
    if ($LASTEXITCODE -ne 0) { throw 'The MyPeople container does not exist.' }
    $running = (& docker inspect $Container --format '{{.State.Running}}').Trim()
    if ($running -ne 'true') { throw 'The MyPeople container must already be running.' }
    if (-not (Test-Path -LiteralPath $MemorySource -PathType Container)) {
        throw 'MemorySource must be an existing directory.'
    }
    if (-not (Test-Path -LiteralPath $Dataset -PathType Container)) {
        throw 'Dataset must be an existing directory.'
    }
    if ([string]::IsNullOrWhiteSpace($Image)) { throw 'Image is required.' }

    $random = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $random.GetBytes($tokenBytes) } finally { $random.Dispose() }
    $token = [BitConverter]::ToString($tokenBytes).Replace('-', '').ToLowerInvariant()
    & docker volume create $volumeName *> $null
    Invoke-DockerWithSecretInput -Secret $token -Arguments @(
        'run','--rm','-i','--user','0:0','-v',"${volumeName}:/secrets",$Image,
        'sh','-c','"umask 077; cat > /secrets/MYPEOPLE_MEMORY_CANARY_TOKEN; chown 1000:1000 /secrets/MYPEOPLE_MEMORY_CANARY_TOKEN"'
    )

    $env:MYPEOPLE_MEMORY_CANARY_IMAGE = $Image
    $env:MYPEOPLE_MEMORY_CANARY_SOURCE = [IO.Path]::GetFullPath($MemorySource)
    $env:MYPEOPLE_MEMORY_CANARY_DATASET = [IO.Path]::GetFullPath($Dataset)
    & docker compose --project-name $projectName -f $composePath up -d
    if ($LASTEXITCODE -ne 0) { throw 'Unable to start the memory canary sidecar.' }
    & docker network connect $networkName $Container
    if ($LASTEXITCODE -ne 0) { throw 'Unable to connect MyPeople to the internal canary network.' }
    & docker exec --user 0:0 $Container sh -c "umask 077; mkdir -p $secretDirectory; chown 1000:1000 $secretDirectory; chmod 700 $secretDirectory"
    if ($LASTEXITCODE -ne 0) { throw 'Unable to prepare the ephemeral canary secret directory.' }
    Invoke-DockerWithSecretInput -Secret $token -Arguments @(
        'exec','-i',$Container,'sh','-c',
        ('"umask 077; cat > {0}"' -f $secretPath)
    )

    $deadline = (Get-Date).AddSeconds(60)
    do {
        $health = (& docker inspect "${projectName}-memory-gate-b-1" --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' 2>$null).Trim()
        if ($health -eq 'healthy') { break }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)
    if ($health -ne 'healthy') { throw 'The memory canary sidecar did not become healthy.' }

    & docker exec $Container /home/mp/mypeople/bin/memory-profile enable --project project-factory --server-url $serverUrl --secret-path $secretPath
    if ($LASTEXITCODE -ne 0) { throw 'Unable to activate the project memory profile.' }
    & docker exec $Container /home/mp/mypeople/bin/mp memory-canary enable --project project-factory
    if ($LASTEXITCODE -ne 0) { throw 'Unable to enable the memory canary control.' }
    $enabled = $true
    Write-Output 'Memory Gate B canary enabled on the internal Docker network.'
} finally {
    if (-not $enabled) { Disable-Canary }
    if ($tokenBytes) { [Array]::Clear($tokenBytes, 0, $tokenBytes.Length) }
    $token = $null
    Remove-Item Env:MYPEOPLE_MEMORY_CANARY_IMAGE -ErrorAction SilentlyContinue
    Remove-Item Env:MYPEOPLE_MEMORY_CANARY_SOURCE -ErrorAction SilentlyContinue
    Remove-Item Env:MYPEOPLE_MEMORY_CANARY_DATASET -ErrorAction SilentlyContinue
}
