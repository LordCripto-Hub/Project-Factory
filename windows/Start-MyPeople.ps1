param(
    [switch]$NoBrowser,
    [int]$DockerTimeoutSeconds = 180,
    [int]$ServiceTimeoutSeconds = 90
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$stateDir = Join-Path $env:LOCALAPPDATA 'MyPeople'
$logPath = Join-Path $stateDir 'launcher.log'
New-Item -ItemType Directory -Path $stateDir -Force | Out-Null

function Write-LauncherLog([string]$Message) {
    $line = '{0:yyyy-MM-dd HH:mm:ss} {1}' -f (Get-Date), $Message
    Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
}

function Show-LauncherError([string]$Message) {
    Write-LauncherLog "ERROR $Message"
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show(
        "$Message`n`nLog: $logPath",
        'MyPeople could not start',
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error
    ) | Out-Null
}

function Test-DockerEngine {
    try {
        & docker info *> $null
        return $LASTEXITCODE -eq 0
    } catch { return $false }
}

function Wait-Until([scriptblock]$Probe, [int]$TimeoutSeconds, [string]$Description) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        if (& $Probe) { return }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    throw "Timeout while waiting for $Description ($TimeoutSeconds s)."
}

try {
    Write-LauncherLog 'START one-click launcher'
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw 'Docker CLI is not installed or is not available in PATH.'
    }

    if (-not (Test-DockerEngine)) {
        $dockerDesktop = 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
        if (-not (Test-Path -LiteralPath $dockerDesktop)) {
            throw "Docker Desktop.exe was not found at $dockerDesktop"
        }
        Write-LauncherLog 'Starting Docker Desktop'
        Start-Process -FilePath $dockerDesktop
        Wait-Until { Test-DockerEngine } $DockerTimeoutSeconds 'Docker Desktop'
    }

    & docker inspect mypeople *> $null
    if ($LASTEXITCODE -ne 0) {
        throw 'The mypeople container does not exist. The launcher will not recreate it because that could destroy state; restore or install the container first.'
    }

    $running = (& docker inspect -f '{{.State.Running}}' mypeople 2>$null).Trim()
    if ($running -ne 'true') {
        Write-LauncherLog 'docker start mypeople'
        & docker start mypeople | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'docker start mypeople failed.' }
    }

    Write-LauncherLog 'docker exec mypeople mypeople up --detach'
    & docker exec mypeople /home/mp/mypeople/bin/mypeople up --detach
    if ($LASTEXITCODE -ne 0) { throw 'mypeople up --detach failed inside the container.' }

    Wait-Until {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri 'http://localhost:9933/health' -TimeoutSec 3
            return $response.StatusCode -eq 200 -and $response.Content -match '"status"\s*:\s*"ok"'
        } catch { return $false }
    } $ServiceTimeoutSeconds 'Priorities'

    Wait-Until {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri 'http://localhost:9900/health' -TimeoutSec 3
            return $response.StatusCode -eq 200 -and $response.Content -match '"status"\s*:\s*"ok"'
        } catch { return $false }
    } $ServiceTimeoutSeconds 'Queue/HUD'

    Wait-Until {
        try {
            $client = [Net.Sockets.TcpClient]::new()
            $task = $client.ConnectAsync('127.0.0.1', 7681)
            $ok = $task.Wait(1500) -and $client.Connected
            $client.Dispose()
            return $ok
        } catch { return $false }
    } 30 'terminal web'

    Write-LauncherLog 'READY http://localhost:9933/'
    if (-not $NoBrowser) { Start-Process 'http://localhost:9933/' }
} catch {
    Show-LauncherError $_.Exception.Message
    exit 1
}
