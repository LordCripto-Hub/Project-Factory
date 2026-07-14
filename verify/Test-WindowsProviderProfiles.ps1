$ErrorActionPreference = 'Stop'

$originalLocalAppData = $env:LOCALAPPDATA
$smokeRoot = Join-Path 'C:\tmp' ('mypeople-provider-smoke-' + [Guid]::NewGuid().ToString('N'))
$resolvedSmoke = [IO.Path]::GetFullPath($smokeRoot)
$allowedRoot = [IO.Path]::GetFullPath('C:\tmp') + [IO.Path]::DirectorySeparatorChar
if (-not $resolvedSmoke.StartsWith($allowedRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Unsafe provider profile smoke path.'
}

try {
    [IO.Directory]::CreateDirectory($resolvedSmoke) | Out-Null
    $env:LOCALAPPDATA = $resolvedSmoke
    Import-Module (Join-Path $PSScriptRoot '..\windows\MyPeople.ProviderProfiles.psm1') -Force
    $store = Initialize-MyPeopleProfileStore
    $fixture = Join-Path $resolvedSmoke 'fixture.json'
    [IO.File]::WriteAllBytes($fixture, [Text.Encoding]::UTF8.GetBytes('{}'))
    $metadata = Save-MyPeopleCodexCredential -Profile 'codex-smoke' -SourceAuth $fixture
    $profilePath = Get-MyPeopleProfilePath -Provider 'codex' -Profile 'codex-smoke'
    $stored = Join-Path $profilePath 'auth.json'
    if (-not [IO.Directory]::Exists($store)) { throw 'Profile store was not created.' }
    if (-not [IO.File]::Exists($stored)) { throw 'Credential byte copy failed.' }
    $expected = [Convert]::ToBase64String([IO.File]::ReadAllBytes($fixture))
    $actual = [Convert]::ToBase64String([IO.File]::ReadAllBytes($stored))
    if ($actual -ne $expected) { throw 'Credential bytes changed during storage.' }
    if ($metadata.provider -ne 'codex') { throw 'Provider metadata was not preserved.' }
    Write-Output 'PASS Windows provider profile ACL, byte copy, and metadata smoke'
} finally {
    Remove-Module MyPeople.ProviderProfiles -ErrorAction SilentlyContinue
    $env:LOCALAPPDATA = $originalLocalAppData
    if ([IO.Directory]::Exists($resolvedSmoke)) {
        Remove-Item -LiteralPath $resolvedSmoke -Recurse -Force
    }
}
