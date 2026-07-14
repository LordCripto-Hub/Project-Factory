param([string]$Container = 'mypeople')

$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'MyPeople.ProviderProfiles.psm1') -Force

function Test-RuntimeDirectory {
    param([Parameter(Mandatory)][string]$Path)
    $arguments = @('exec', $Container, 'test', '-d', $Path)
    $process = Start-Process -FilePath 'docker' -ArgumentList $arguments -WindowStyle Hidden -PassThru
    if (-not $process.WaitForExit(10000)) {
        try { $process.Kill() } catch { }
        return $false
    }
    return $process.ExitCode -eq 0
}

$bindings = Get-MyPeopleProviderBindings
$profiles = Get-MyPeopleProviderProfiles
$rows = @()
foreach ($property in @($profiles.PSObject.Properties)) {
    $profile = $property.Value
    $profileId = [string]$property.Name
    $provider = [string]$profile.provider
    $adapter = Get-MyPeopleProviderAdapter -Provider $provider
    $environment = & $adapter.RuntimeEnvironment $profileId
    $profileDirectory = Get-MyPeopleProfilePath -Provider $provider -Profile $profileId
    $runtime = if (Test-RuntimeDirectory -Path ([string]$environment.CODEX_HOME)) { 'installed' } else { 'missing' }
    $rows += [pscustomobject]@{
        profile = $profileId
        provider = $provider
        stored = [IO.Directory]::Exists($profileDirectory)
        runtime = $runtime
        validation = 'not-run'
    }
}

[pscustomobject]@{
    globalProfile = [string]$bindings.globalProfile
    agentProfiles = $bindings.agentProfiles
    profiles = $rows
} | ConvertTo-Json -Depth 8
