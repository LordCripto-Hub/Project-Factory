param(
    [Parameter(Mandatory)]
    [ValidateSet('Enable', 'Disable')]
    [string]$Mode,
    [string]$ProjectSlug = 'project-factory',
    [string]$ServerUrl = 'https://mypeople-memory-sandbox.labmkt.workers.dev/mcp',
    [string]$Container = 'mypeople'
)

$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'MyPeople.Memory.psm1') -Force

$enabled = $Mode -eq 'Enable'
if ($enabled) {
    throw 'Persistent memory activation is blocked until the credential broker is isolated from workers. Use Test-MyPeopleMemoryPilot.ps1 for the synthetic E2E.'
}
Set-MyPeopleMemorySettings -Enabled $enabled -ProjectSlug $ProjectSlug -ServerUrl $ServerUrl | Out-Null
Sync-MyPeopleMemoryActivation -Container $Container | Out-Null
if (-not $enabled) {
    Clear-MyPeopleMemoryCredentialInContainer -Container $Container
}
if ($enabled) {
    Write-Output "MyPeople read-only memory enabled for project $ProjectSlug."
} else {
    Write-Output "MyPeople memory disabled for project $ProjectSlug; tmpfs credential cleared."
}
