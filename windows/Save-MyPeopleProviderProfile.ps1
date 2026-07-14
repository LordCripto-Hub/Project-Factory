param(
    [ValidateSet('codex')][string]$Provider = 'codex',
    [Parameter(Mandatory)][string]$Profile,
    [switch]$FromCurrentWindowsLogin
)

$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'MyPeople.ProviderProfiles.psm1') -Force

if (-not $FromCurrentWindowsLogin) {
    throw 'Use -FromCurrentWindowsLogin to import the active provider login.'
}

$safeProfile = Test-MyPeopleProfileId -Profile $Profile
$adapter = Get-MyPeopleProviderAdapter -Provider $Provider
$validationCommand = 'codex login status'
Write-Verbose "Validating source with $validationCommand"
& $adapter.InspectSource $safeProfile | Out-Null

$sourceDirectory = Join-Path $env:USERPROFILE '.codex'
$sourceAuth = Join-Path $sourceDirectory 'auth.json'
if (-not [IO.File]::Exists($sourceAuth)) {
    throw 'The current Codex login does not contain an authentication file.'
}

& $adapter.SaveProfile $safeProfile $sourceAuth | Out-Null
Write-Output "Saved provider profile: $safeProfile ($Provider)"
