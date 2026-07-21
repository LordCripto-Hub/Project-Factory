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
$secretPath = '/run/mypeople-secrets/MYPEOPLE_MEMORY_CANARY_TOKEN'
$serverUrl = 'http://memory-gate-b:18443/mcp'
$composePath = Join-Path $PSScriptRoot '..\experiments\memory-gate-b\docker\compose.live-canary.yml'

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
    & docker exec $Container /home/mp/mypeople/bin/mp memory-canary disable *> $null
    & docker exec $Container /home/mp/mypeople/bin/memory-profile disable --project project-factory *> $null
    & docker exec $Container sh -c "rm -f $secretPath" *> $null
    & docker network disconnect $networkName $Container *> $null
    & docker compose --project-name $projectName -f $composePath down --volumes *> $null
}

if ($Action -eq 'Status') {
    & docker inspect $Container --format '{{.State.Status}}'
    & docker compose --project-name $projectName -f $composePath ps
    exit $LASTEXITCODE
}
if ($Action -eq 'Disable') {
    try { Disable-Canary } finally { Write-Output 'Memory Gate B canary disabled.' }
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

    [Security.Cryptography.RandomNumberGenerator]::Fill($tokenBytes)
    $token = [Convert]::ToHexString($tokenBytes).ToLowerInvariant()
    & docker volume create $volumeName *> $null
    Invoke-DockerWithSecretInput -Secret $token -Arguments @(
        'run','--rm','-i','-v',"${volumeName}:/secrets",$Image,
        'sh','-c','"umask 077; cat > /secrets/MYPEOPLE_MEMORY_CANARY_TOKEN"'
    )

    $env:MYPEOPLE_MEMORY_CANARY_IMAGE = $Image
    $env:MYPEOPLE_MEMORY_CANARY_SOURCE = [IO.Path]::GetFullPath($MemorySource)
    $env:MYPEOPLE_MEMORY_CANARY_DATASET = [IO.Path]::GetFullPath($Dataset)
    & docker compose --project-name $projectName -f $composePath up -d
    if ($LASTEXITCODE -ne 0) { throw 'Unable to start the memory canary sidecar.' }
    & docker network connect $networkName $Container
    if ($LASTEXITCODE -ne 0) { throw 'Unable to connect MyPeople to the internal canary network.' }
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
