$ErrorActionPreference = 'Stop'
$installDirectory = Join-Path $env:LOCALAPPDATA 'MyPeople\launcher'
New-Item -ItemType Directory -Path $installDirectory -Force | Out-Null

foreach ($name in @(
    'Start-MyPeople.ps1',
    'MyPeople.ProviderProfiles.psm1',
    'MyPeople.Memory.psm1',
    'Set-MyPeopleMemoryCredential.ps1',
    'Set-MyPeopleMemoryActivation.ps1',
    'Test-MyPeopleMemoryPilot.ps1',
    'Publish-MyPeopleProject.ps1'
)) {
    $source = Join-Path $PSScriptRoot $name
    if (-not (Test-Path -LiteralPath $source)) { throw "Launcher file missing: $source" }
    $destination = Join-Path $installDirectory $name
    if (-not [IO.Path]::GetFullPath($source).Equals(
        [IO.Path]::GetFullPath($destination),
        [StringComparison]::OrdinalIgnoreCase
    )) {
        Copy-Item -LiteralPath $source -Destination $destination -Force
    }
}

$deploymentDirectory = Join-Path $env:LOCALAPPDATA 'MyPeople\deployment'
$environmentPath = Join-Path $deploymentDirectory '.env'
if (Test-Path -LiteralPath $environmentPath) {
    $projectRoot = Split-Path $PSScriptRoot -Parent
    foreach ($name in @('compose.volume-backed.yml', 'compose.tailscale.yml', 'state-volumes.json')) {
        $source = Join-Path $projectRoot "docker\$name"
        if (-not (Test-Path -LiteralPath $source)) {
            throw "Deployment file missing: $source"
        }
        Copy-Item -LiteralPath $source -Destination $deploymentDirectory -Force
    }
}

$launcher = Join-Path $installDirectory 'Start-MyPeople.ps1'

$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop 'MyPeople.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$launcher`""
$shortcut.WorkingDirectory = Split-Path -Parent $launcher
$shortcut.Description = 'Start MyPeople in Docker and open Priorities'
$dockerDesktop = 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
$shortcut.IconLocation = if (Test-Path -LiteralPath $dockerDesktop) { "$dockerDesktop,0" } else { "$env:SystemRoot\System32\shell32.dll,25" }
$shortcut.Save()

Write-Host "MyPeople shortcut installed: $shortcutPath"
