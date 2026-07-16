param(
    [switch]$NoBrowser,
    [switch]$NonInteractive,
    [int]$DockerTimeoutSeconds = 180,
    [int]$ServiceTimeoutSeconds = 90
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Import-Module (Join-Path $PSScriptRoot 'MyPeople.ProviderProfiles.psm1') -Force
Import-Module (Join-Path $PSScriptRoot 'MyPeople.Memory.psm1') -Force
$stateDir = Join-Path $env:LOCALAPPDATA 'MyPeople'
$logPath = Join-Path $stateDir 'launcher.log'
New-Item -ItemType Directory -Path $stateDir -Force | Out-Null

function Write-LauncherLog([string]$Message) {
    $line = '{0:yyyy-MM-dd HH:mm:ss} {1}' -f (Get-Date), $Message
    Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
}

function Show-LauncherError([string]$Message) {
    Write-LauncherLog "ERROR $Message"
    if (-not $NonInteractive) {
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show(
            "$Message`n`nLog: $logPath",
            'MyPeople could not start',
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Error
        ) | Out-Null
    } else {
        Write-Output "ERROR $Message"
    }
}

function Show-LauncherWarning([string]$Message) {
    Write-LauncherLog "WARNING $Message"
    if ($NonInteractive) {
        Write-Output "WARNING $Message"
        return
    }
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show(
        $Message,
        'MyPeople started without agents',
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Warning
    ) | Out-Null
}

$providerReady = $false
$providerWarning = ''

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

function Set-LegacyProviderLaunchGate {
    param([Parameter(Mandatory)][string]$Container)
    $temporary = Join-Path $env:TEMP ("mypeople-provider-launch-{0}.json" -f [guid]::NewGuid().ToString('N'))
    $record = [ordered]@{
        schemaVersion = 1
        paused = $true
        reason = 'launcher_bootstrap'
        pausedAt = [DateTime]::UtcNow.ToString('o')
    }
    try {
        [IO.File]::WriteAllText(
            $temporary,
            (($record | ConvertTo-Json -Compress) + [Environment]::NewLine),
            [Text.UTF8Encoding]::new($false)
        )
        & docker cp $temporary "${Container}:/home/mp/mypeople/run/provider-launch.paused" | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Unable to establish the legacy provider launch gate.' }
    } finally {
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
    }
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

    $deploymentDirectory = Join-Path $env:LOCALAPPDATA 'MyPeople\deployment'
    $composePath = Join-Path $deploymentDirectory 'compose.volume-backed.yml'
    $environmentPath = Join-Path $deploymentDirectory '.env'
    $hasCompose = Test-Path -LiteralPath $composePath
    $hasEnvironment = Test-Path -LiteralPath $environmentPath
    if ($hasCompose -xor $hasEnvironment) {
        throw 'The pinned MyPeople deployment is incomplete; both Compose and .env are required.'
    }

    if ($hasCompose -and $hasEnvironment) {
        Write-LauncherLog 'Establish provider launch gate before pinned deployment startup'
        & docker compose --project-name mypeople --env-file $environmentPath -f $composePath run --rm --no-deps provider-launch-gate | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Unable to establish the provider launch gate.' }
        Write-LauncherLog 'docker compose pinned deployment up'
        & docker compose --project-name mypeople --env-file $environmentPath -f $composePath up -d
        if ($LASTEXITCODE -ne 0) { throw 'Pinned docker compose up failed.' }
    } else {
        & docker inspect mypeople *> $null
        if ($LASTEXITCODE -ne 0) {
            throw 'The mypeople container and pinned deployment manifest are both missing.'
        }
        Set-LegacyProviderLaunchGate -Container 'mypeople'
        $running = (& docker inspect -f '{{.State.Running}}' mypeople 2>$null).Trim()
        if ($running -ne 'true') {
            Write-LauncherLog 'docker start mypeople'
            & docker start mypeople | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'docker start mypeople failed.' }
        }
    }

    Write-LauncherLog 'Rehydrate bounded memory credential state'
    Sync-MyPeopleMemoryActivation -Container 'mypeople' | Out-Null

    $bindings = Get-MyPeopleProviderBindings
    $activeProfile = [string]$bindings.globalProfile
    if ($activeProfile) {
        try {
            $profiles = Get-MyPeopleProviderProfiles
            $profileProperty = $profiles.PSObject.Properties[$activeProfile]
            if ($null -eq $profileProperty -or -not $profileProperty.Value.enabled) {
                throw 'The configured provider profile is missing or disabled.'
            }
            $adapter = Get-MyPeopleProviderAdapter -Provider ([string]$profileProperty.Value.provider)
            Write-LauncherLog "Rehydrate provider profile $activeProfile"
            & $adapter.ActivateProfile $activeProfile 'mypeople' | Out-Null
            & $adapter.ValidateRuntime $activeProfile 'mypeople' | Out-Null
            $providerReady = $true
        } catch {
            $providerWarning = 'The provider could not be validated. MyPeople is available, but new agents remain paused. Refresh the saved provider profile and run the shortcut again.'
        }
    } else {
        Write-LauncherLog 'No provider binding configured'
        $providerWarning = 'No global provider profile is configured. MyPeople is available, but new agents remain paused.'
    }

    if ($providerReady) {
        Write-LauncherLog 'Resume provider launches'
        & docker exec mypeople /home/mp/mypeople/bin/mp providers-resume | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Unable to resume provider launches.' }
    } else {
        Write-LauncherLog 'Pause provider launches for degraded startup'
        & docker exec mypeople /home/mp/mypeople/bin/mp providers-pause --reason launcher_provider_unavailable | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Unable to pause provider launches safely.' }
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

    if ($providerReady) {
        Wait-Until {
            try {
                $statusOutput = @(& docker exec mypeople /home/mp/mypeople/bin/mp status 2>$null)
                $statusExitCode = $LASTEXITCODE
                $statusText = $statusOutput -join "`n"
                return $statusExitCode -eq 0 `
                    -and $statusText -match 'main:Boss \[alive\]' `
                    -and $statusText -match 'nightwatch:Nightwatch \[alive\]'
            } catch { return $false }
        } $ServiceTimeoutSeconds 'Boss and Nightwatch'
        Write-LauncherLog 'READY http://localhost:9933/'
    } else {
        Write-LauncherLog 'READY DEGRADED http://localhost:9933/'
    }

    if (-not $NoBrowser) { Start-Process 'http://localhost:9933/' }
    if ($providerWarning) { Show-LauncherWarning $providerWarning }
} catch {
    Show-LauncherError $_.Exception.Message
    exit 1
}
