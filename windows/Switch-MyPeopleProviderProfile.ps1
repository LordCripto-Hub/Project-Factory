param(
    [string]$Profile = '',
    [string]$Agent = '',
    [switch]$InheritGlobal,
    [int]$TimeoutSeconds = 120
)

$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'MyPeople.ProviderProfiles.psm1') -Force

$container = 'mypeople'
$sessionTool = '/home/mp/mypeople/bin/provider-session'
$transactionId = [Guid]::NewGuid().ToString('N')
$logRoot = Join-Path $env:LOCALAPPDATA 'MyPeople\state'
$logPath = Join-Path $logRoot 'provider-switch.log'
$prepared = $false
$agentsStopped = $false
$adapter = $null
$previousBindings = $null
$profilesToRestore = @()
$phase = 'preflight'
$targetLabel = 'unresolved'

function Write-SwitchLog {
    param([Parameter(Mandatory)][string]$Message)
    [IO.Directory]::CreateDirectory($logRoot) | Out-Null
    $line = '{0:yyyy-MM-dd HH:mm:ss} profile={1} agent={2} phase={3}' -f (
        Get-Date
    ), $targetLabel, $(if ($Agent) { $Agent } else { 'global' }), $Message
    Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
}

function ConvertTo-SwitchMap {
    param($Value)
    $result = [ordered]@{}
    if ($null -eq $Value) { return $result }
    if ($Value -is [Collections.IDictionary]) {
        foreach ($key in $Value.Keys) { $result[[string]$key] = $Value[$key] }
        return $result
    }
    foreach ($property in $Value.PSObject.Properties) {
        $result[$property.Name] = $property.Value
    }
    return $result
}

function Get-HostTargetProfiles {
    param(
        [Parameter(Mandatory)]$Bindings,
        [Parameter(Mandatory)][string[]]$SelectedAgentIds,
        [switch]$AllowEmptySelection
    )
    $agentProfiles = ConvertTo-SwitchMap $Bindings.agentProfiles
    if ($SelectedAgentIds.Count -eq 0) {
        if (-not $AllowEmptySelection) {
            throw 'Prepared provider transaction selected no agents.'
        }
        $values = @([string]$Bindings.globalProfile)
    } else {
        $values = foreach ($selectedAgentId in $SelectedAgentIds) {
            if ($agentProfiles.Contains($selectedAgentId)) {
                [string]$agentProfiles[$selectedAgentId]
            } else {
                [string]$Bindings.globalProfile
            }
        }
    }
    $result = @(
        $values |
            ForEach-Object { Test-MyPeopleProfileId -Profile ([string]$_) } |
            Sort-Object -Unique
    )
    if ($result.Count -eq 0) {
        throw 'Host provider bindings have no target profiles.'
    }
    return $result
}

function Invoke-ProviderSession {
    param(
        [Parameter(Mandatory)][string]$Operation,
        [Parameter(Mandatory)][string]$Transaction,
        [string]$SelectedAgent = '',
        [string]$TargetProfile = ''
    )
    $arguments = @(
        'exec',
        $container,
        $sessionTool,
        $Operation,
        '--transaction',
        $Transaction
    )
    if ($Operation -eq 'prepare' -and $SelectedAgent) {
        $arguments += @('--agent', $SelectedAgent)
    }
    if ($Operation -eq 'prepare') {
        if ([string]::IsNullOrWhiteSpace($TargetProfile)) {
            throw 'Target profile is required for provider-session prepare.'
        }
        $arguments += @('--profile', $TargetProfile)
    }
    $outputPath = [IO.Path]::GetTempFileName()
    $errorPath = [IO.Path]::GetTempFileName()
    try {
        $startArguments = @{
            FilePath = 'docker'
            ArgumentList = $arguments
            WindowStyle = 'Hidden'
            PassThru = $true
            RedirectStandardOutput = $outputPath
            RedirectStandardError = $errorPath
        }
        $process = Start-Process @startArguments
        $null = $process.Handle
        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            throw "Provider session phase timed out: $Operation"
        }
        $process.WaitForExit()
        $process.Refresh()
        if ($process.ExitCode -ne 0) {
            $detail = [IO.File]::ReadAllText($errorPath).Trim()
            if ([string]::IsNullOrWhiteSpace($detail)) {
                $detail = [IO.File]::ReadAllText($outputPath).Trim()
            }
            $detail = ($detail -replace '[\r\n]+', ' ').Trim()
            if ($detail.Length -gt 1000) { $detail = $detail.Substring(0, 1000) }
            throw "Provider session phase failed: ${Operation}: $detail"
        }
        return [IO.File]::ReadAllText($outputPath).Trim()
    } finally {
        Remove-Item -LiteralPath $outputPath, $errorPath -Force -ErrorAction SilentlyContinue
    }
}

try {
    if ($TimeoutSeconds -lt 1) { throw 'TimeoutSeconds must be positive.' }
    if ($InheritGlobal) {
        if ($Profile) { throw 'Profile cannot be combined with InheritGlobal.' }
        if (-not $Agent) { throw 'Agent is required with InheritGlobal.' }
        $safeProfile = ''
        $targetLabel = 'inherit-global'
    } else {
        if ([string]::IsNullOrWhiteSpace($Profile)) { throw 'Profile is required.' }
        $safeProfile = Test-MyPeopleProfileId -Profile $Profile
        $targetLabel = $safeProfile
    }
    if ($Agent -and $Agent -notmatch '^[^\s/]+/[^\s/:]+:[^\s/:]+$') {
        throw 'Invalid agent ID.'
    }
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw 'Docker CLI is not available.'
    }

    $previousBindings = Get-MyPeopleProviderBindings
    $newAgents = ConvertTo-SwitchMap $previousBindings.agentProfiles
    $newBindings = [ordered]@{
        globalProfile = [string]$previousBindings.globalProfile
        agentProfiles = $newAgents
    }
    if ($InheritGlobal) {
        [void]$newAgents.Remove($Agent)
    } elseif ($Agent) {
        $newAgents[$Agent] = $safeProfile
    } else {
        $newBindings.globalProfile = $safeProfile
    }
    $targetProfile = if ($InheritGlobal) {
        [string]$newBindings.globalProfile
    } else {
        $safeProfile
    }

    $profiles = Get-MyPeopleProviderProfiles
    $targetProperty = $profiles.PSObject.Properties[$targetProfile]
    if ($null -eq $targetProperty -or -not $targetProperty.Value.enabled) {
        throw "Host provider profile is unavailable: $targetProfile"
    }
    $provider = [string]$targetProperty.Value.provider
    $adapter = Get-MyPeopleProviderAdapter -Provider $provider
    $targetPath = Get-MyPeopleProfilePath -Provider $provider -Profile $targetProfile
    if (-not [IO.File]::Exists((Join-Path $targetPath 'auth.json'))) {
        throw "Host provider credential is missing: $targetProfile"
    }

    $phase = 'provider-session prepare'
    Write-SwitchLog $phase
    $prepareOutput = Invoke-ProviderSession -Operation 'prepare' -Transaction $transactionId -SelectedAgent $Agent -TargetProfile $targetProfile
    $prepared = $true
    $prepareReceipt = $prepareOutput | ConvertFrom-Json
    $selectedAgentIds = @(
        $prepareReceipt.selectedAgentIds |
            ForEach-Object {
                $candidateAgentId = [string]$_
                if ($candidateAgentId -notmatch '^[^\s/]+/[^\s/:]+:[^\s/:]+$') {
                    throw 'Prepared provider transaction returned an invalid agent ID.'
                }
                $candidateAgentId
            }
    )
    if ($Agent -and ($selectedAgentIds.Count -ne 1 -or $selectedAgentIds[0] -ne $Agent)) {
        throw 'Prepared provider transaction selected the wrong agent.'
    }

    $profilesToActivate = @(
        Get-HostTargetProfiles -Bindings $newBindings -SelectedAgentIds $selectedAgentIds -AllowEmptySelection:(-not [bool]$Agent)
    )
    $profilesToRestore = @(
        Get-HostTargetProfiles -Bindings $previousBindings -SelectedAgentIds $selectedAgentIds -AllowEmptySelection:(-not [bool]$Agent)
    )
    foreach ($profileToActivate in $profilesToActivate) {
        $candidateProperty = $profiles.PSObject.Properties[$profileToActivate]
        if ($null -eq $candidateProperty -or -not $candidateProperty.Value.enabled) {
            throw "Host provider profile is unavailable: $profileToActivate"
        }
        $candidateProvider = [string]$candidateProperty.Value.provider
        if ($candidateProvider -ne $provider) {
            throw "Host provider profile has an incompatible provider: $profileToActivate"
        }
        $candidatePath = Get-MyPeopleProfilePath -Provider $provider -Profile $profileToActivate
        if (-not [IO.File]::Exists((Join-Path $candidatePath 'auth.json'))) {
            throw "Host provider credential is missing: $profileToActivate"
        }
    }

    $handoffDirectory = Join-Path (Join-Path $env:LOCALAPPDATA 'MyPeople\handoffs') $transactionId
    Protect-MyPeopleDirectory -Path $handoffDirectory | Out-Null
    $handoffSource = "${container}:/home/mp/mypeople/run/provider-transactions/$transactionId/handoffs.json"
    & docker cp $handoffSource (Join-Path $handoffDirectory 'handoffs.json') | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Unable to copy the provider switch handoff.' }

    $phase = 'provider-session stop'
    Write-SwitchLog $phase
    $agentsStopped = $true
    Invoke-ProviderSession -Operation 'stop' -Transaction $transactionId | Out-Null

    foreach ($profileToActivate in $profilesToActivate) {
        $phase = "activate provider profile $profileToActivate"
        Write-SwitchLog $phase
        & $adapter.ActivateProfile $profileToActivate $container | Out-Null

        $phase = "validate provider runtime $profileToActivate"
        Write-SwitchLog $phase
        & $adapter.ValidateRuntime $profileToActivate $container | Out-Null
    }

    $phase = 'persist provider bindings'
    Write-SwitchLog $phase
    Set-MyPeopleProviderBindings -Bindings $newBindings -Container $container

    $phase = 'provider-session revive'
    Write-SwitchLog $phase
    Invoke-ProviderSession -Operation 'revive' -Transaction $transactionId | Out-Null

    $phase = 'provider-session verify'
    Write-SwitchLog $phase
    Invoke-ProviderSession -Operation 'verify' -Transaction $transactionId | Out-Null

    $phase = 'provider-session commit'
    Write-SwitchLog $phase
    Invoke-ProviderSession -Operation 'commit' -Transaction $transactionId | Out-Null
    Write-Output "Provider binding active: $targetLabel ($(if ($Agent) { $Agent } else { 'global' }))"
} catch {
    $failedPhase = $phase
    $failureMessage = $_.Exception.Message
    if ($prepared) {
        if ($agentsStopped) {
            if ($null -ne $adapter) {
                foreach ($profileToRestore in $profilesToRestore) {
                    try { & $adapter.RestorePrevious $profileToRestore $container | Out-Null } catch {}
                }
            }
            if ($null -ne $previousBindings) {
                try { Set-MyPeopleProviderBindings -Bindings $previousBindings -Container $container } catch {}
            }
            $phase = 'provider-session rollback'
        } else {
            $phase = 'provider-session abort'
        }
        Write-SwitchLog $phase
        try {
            if ($agentsStopped) {
                Invoke-ProviderSession -Operation 'rollback' -Transaction $transactionId | Out-Null
            } else {
                Invoke-ProviderSession -Operation 'abort' -Transaction $transactionId | Out-Null
            }
        } catch {}
    }
    Write-Error "Provider switch failed during $failedPhase for target ${targetLabel}: $failureMessage"
    exit 1
}
