$ErrorActionPreference = 'Stop'
$previousLocalAppData = $env:LOCALAPPDATA
$previousPath = $env:PATH
$previousDockerLog = $env:MYPEOPLE_MEMORY_DOCKER_LOG
$temporaryRoot = Join-Path ([IO.Path]::GetTempPath()) ('mypeople-memory-test-' + [Guid]::NewGuid().ToString('N'))

try {
    $env:LOCALAPPDATA = $temporaryRoot
    Import-Module (Join-Path $PSScriptRoot '..\windows\MyPeople.Memory.psm1') -Force
    $plain = [Text.Encoding]::UTF8.GetBytes('fixture-memory-token')
    Save-MyPeopleMemoryCredentialBytes -CredentialBytes $plain | Out-Null
    $restored = Get-MyPeopleMemoryCredentialBytes
    if (-not [Linq.Enumerable]::SequenceEqual([byte[]]$plain, [byte[]]$restored)) {
        throw 'DPAPI round trip did not preserve credential bytes.'
    }
    $cipherPath = Get-MyPeopleMemoryCredentialPath
    $cipher = [IO.File]::ReadAllBytes($cipherPath)
    $cipherText = [Text.Encoding]::UTF8.GetString($cipher)
    if ($cipherText.Contains('fixture-memory-token')) {
        throw 'Plaintext credential was found in the DPAPI file.'
    }
    Set-MyPeopleMemorySettings -Enabled $false -ProjectSlug 'project-factory' -ServerUrl 'https://mypeople-memory-sandbox.labmkt.workers.dev/mcp' | Out-Null
    $settings = Get-MyPeopleMemorySettings
    if ($settings.enabled -ne $false -or $settings.projectSlug -ne 'project-factory') {
        throw 'Memory settings round trip failed.'
    }
    $settingsJson = $settings | ConvertTo-Json -Depth 8
    if ($settingsJson.Contains('fixture-memory-token')) {
        throw 'Plaintext credential leaked into settings.'
    }
    $untrustedUrlRejected = $false
    try {
        Set-MyPeopleMemorySettings -Enabled $true -ProjectSlug 'pilot-alpha' -ServerUrl 'https://attacker.example/mcp' | Out-Null
    } catch {
        $untrustedUrlRejected = $true
    }
    if (-not $untrustedUrlRejected) {
        throw 'The pilot credential was not pinned to the trusted MCP URL.'
    }
    $fakeBin = Join-Path $temporaryRoot 'fake-bin'
    [IO.Directory]::CreateDirectory($fakeBin) | Out-Null
    $dockerLog = Join-Path $temporaryRoot 'docker.log'
    $fakeDocker = @'
@echo off
echo %*>>"%MYPEOPLE_MEMORY_DOCKER_LOG%"
echo %* | findstr /c:"memory-profile disable" >nul
if not errorlevel 1 exit /b 7
exit /b 0
'@
    [IO.File]::WriteAllText(
        (Join-Path $fakeBin 'docker.cmd'),
        $fakeDocker,
        [Text.Encoding]::ASCII
    )
    $env:MYPEOPLE_MEMORY_DOCKER_LOG = $dockerLog
    $env:PATH = $fakeBin + [IO.Path]::PathSeparator + $previousPath
    $failedClosed = $false
    try {
        Sync-MyPeopleMemoryActivation -Container 'mypeople-test' | Out-Null
    } catch {
        $failedClosed = $true
    }
    if (-not $failedClosed) {
        throw 'A failed profile disable did not fail closed.'
    }
    $dockerCalls = [IO.File]::ReadAllText($dockerLog)
    if (-not $dockerCalls.Contains('unlink')) {
        throw 'The tmpfs credential was not cleared after profile disable failed.'
    }
    Write-Output 'PASS Windows memory DPAPI contract'
} finally {
    $env:LOCALAPPDATA = $previousLocalAppData
    $env:PATH = $previousPath
    $env:MYPEOPLE_MEMORY_DOCKER_LOG = $previousDockerLog
    if (Test-Path -LiteralPath $temporaryRoot) {
        Remove-Item -LiteralPath $temporaryRoot -Recurse -Force
    }
}
