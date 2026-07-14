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
$adapter = $null
$previousBindings = $null
$previousEffectiveProfile = ''
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

function Invoke-ProviderSession {
    param(
        [Parameter(Mandatory)][string]$Operation,
        [Parameter(Mandatory)][string]$Transaction,
        [string]$SelectedAgent = ''
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
    $startArguments = @{
        FilePath = 'docker'
        ArgumentList = $arguments
        WindowStyle = 'Hidden'
        PassThru = $true
    }
    $process = Start-Process @startArguments
    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        throw "Provider session phase timed out: $Operation"
    }
    if ($process.ExitCode -ne 0) {
        throw "Provider session phase failed: $Operation"
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

    if (-not $InheritGlobal) {
        $profiles = Get-MyPeopleProviderProfiles
        $profileProperty = $profiles.PSObject.Properties[$safeProfile]
        if ($null -eq $profileProperty) { throw 'Provider profile does not exist.' }
        $profileMetadata = $profileProperty.Value
        if (-not $profileMetadata.enabled) { throw 'Provider profile is disabled.' }
        $provider = [string]$profileMetadata.provider
        $adapter = Get-MyPeopleProviderAdapter -Provider $provider
        $savedProfilePath = Get-MyPeopleProfilePath -Provider $provider -Profile $safeProfile
        if (-not [IO.File]::Exists((Join-Path $savedProfilePath 'auth.json'))) {
            throw 'Saved provider credential is missing.'
        }
    }

    $previousBindings = Get-MyPeopleProviderBindings
    $previousAgents = ConvertTo-SwitchMap $previousBindings.agentProfiles
    if ($Agent -and $previousAgents.Contains($Agent)) {
        $previousEffectiveProfile = [string]$previousAgents[$Agent]
    } else {
        $previousEffectiveProfile = [string]$previousBindings.globalProfile
    }

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

    $phase = 'provider-session prepare'
    Write-SwitchLog $phase
    Invoke-ProviderSession -Operation 'prepare' -Transaction $transactionId -SelectedAgent $Agent
    $prepared = $true

    $handoffDirectory = Join-Path (Join-Path $env:LOCALAPPDATA 'MyPeople\handoffs') $transactionId
    Protect-MyPeopleDirectory -Path $handoffDirectory | Out-Null
    $handoffSource = "${container}:/home/mp/mypeople/run/provider-transactions/$transactionId/handoffs.json"
    & docker cp $handoffSource (Join-Path $handoffDirectory 'handoffs.json') | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Unable to copy the provider switch handoff.' }

    $phase = 'provider-session stop'
    Write-SwitchLog $phase
    Invoke-ProviderSession -Operation 'stop' -Transaction $transactionId

    if (-not $InheritGlobal) {
        $phase = 'activate provider profile'
        Write-SwitchLog $phase
        & $adapter.ActivateProfile $safeProfile $container | Out-Null

        $phase = 'validate provider runtime'
        Write-SwitchLog $phase
        & $adapter.ValidateRuntime $safeProfile $container | Out-Null
    }

    $phase = 'persist provider bindings'
    Write-SwitchLog $phase
    Set-MyPeopleProviderBindings -Bindings $newBindings -Container $container

    $phase = 'provider-session revive'
    Write-SwitchLog $phase
    Invoke-ProviderSession -Operation 'revive' -Transaction $transactionId

    $phase = 'provider-session verify'
    Write-SwitchLog $phase
    Invoke-ProviderSession -Operation 'verify' -Transaction $transactionId

    $phase = 'provider-session commit'
    Write-SwitchLog $phase
    Invoke-ProviderSession -Operation 'commit' -Transaction $transactionId
    Write-Output "Provider binding active: $targetLabel ($(if ($Agent) { $Agent } else { 'global' }))"
} catch {
    $failedPhase = $phase
    $failureMessage = $_.Exception.Message
    if ($prepared) {
        if ($null -ne $adapter -and $previousEffectiveProfile) {
            try { & $adapter.RestorePrevious $previousEffectiveProfile $container | Out-Null } catch {}
        }
        if ($null -ne $previousBindings) {
            try { Set-MyPeopleProviderBindings -Bindings $previousBindings -Container $container } catch {}
        }
        $phase = 'provider-session rollback'
        Write-SwitchLog $phase
        try {
            Invoke-ProviderSession -Operation 'rollback' -Transaction $transactionId
        } catch {}
    }
    Write-Error "Provider switch failed during $failedPhase for target ${targetLabel}: $failureMessage"
    exit 1
}
